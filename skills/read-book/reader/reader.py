#!/usr/bin/env python3
"""Book Reader: a local EPUB/PDF reader that Claude opens in Claude Code's side panel.

  reader.py open [QUERY | PATH] [--last]   start the server if needed, find the book, print JSON with its URL
  reader.py list [QUERY]                    list the books in the library
  reader.py status                          what is open now: book, position, text on screen, last selection
  reader.py add PATH                        add a book file, or a folder of books, to the library
  reader.py folders                         show the folders the library is built from
  reader.py start | stop | restart | serve  manage the local server (serve runs it in the foreground)
"""

import difflib
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"
DATA_DIR = Path.home() / "Library" / "Application Support" / "Book Reader"
STATE_FILE = DATA_DIR / "state.json"
CONFIG_FILE = DATA_DIR / "config.json"
PID_FILE = DATA_DIR / "server.pid"
LOG_FILE = DATA_DIR / "server.log"
LOC_DIR = DATA_DIR / "locations"
PORT = int(os.environ.get("BOOK_READER_PORT", "47210"))
BASE_URL = f"http://localhost:{PORT}"

DEFAULT_FOLDERS = [
    "~/Documents/personal/books",  # one folder per book: the book file, its chapter index, its receipt
    "~/Library/Mobile Documents/iCloud~com~apple~iBooks/Documents",
    "~/Books",
]
FORMATS = {".epub": "epub", ".pdf": "pdf"}
ID_DIR = re.compile(r"^(?:book|pdf)-([0-9a-f]{12})$")
MD5_IN_NAME = re.compile(r"([0-9a-f]{32})")
SF_DATALESS = 0x40000000  # macOS: file is in iCloud and not downloaded yet
SCAN_DEPTH = 3

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".gif": "image/gif",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".json": "application/json",
    ".bcmap": "application/octet-stream",
    ".pfb": "application/octet-stream",
    ".ttf": "font/ttf",
    ".epub": "application/epub+zip",
    ".pdf": "application/pdf",
}


def code_version():
    """Changes whenever the reader's code changes, so `start` can replace a stale server."""
    h = hashlib.sha1()
    for p in [Path(__file__)] + sorted(WEB_DIR.glob("*.*")):
        try:
            st = p.stat()
            h.update(f"{p.name}:{st.st_mtime_ns}:{st.st_size}".encode())
        except OSError:
            pass
    return h.hexdigest()[:10]


# ---------------------------------------------------------------- state & config

_lock = threading.RLock()


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def load_state():
    with _lock:
        s = _read_json(STATE_FILE, {})
        for k in ("progress", "meta", "added"):
            s.setdefault(k, {} if k != "added" else [])
        s.setdefault("settings", {})
        return s


def update_state(fn):
    with _lock:
        s = load_state()
        fn(s)
        _write_json(STATE_FILE, s)
        return s


def load_config():
    cfg = _read_json(CONFIG_FILE, None)
    if not cfg:
        cfg = {"folders": DEFAULT_FOLDERS}
        _write_json(CONFIG_FILE, cfg)
    return cfg


# ---------------------------------------------------------------- library

def is_dataless(path):
    try:
        return bool(os.stat(path).st_flags & SF_DATALESS)
    except (OSError, AttributeError):
        return False


def book_key(path, size):
    """A stable id: the 12-hex id the personal library uses, else name + size (survives moves)."""
    m = ID_DIR.match(path.parent.name)
    if m:
        return m.group(1)
    m = MD5_IN_NAME.search(path.name.lower())
    if m:
        return m.group(1)[:12]
    return hashlib.sha1(f"{path.name.lower()}|{size}".encode()).hexdigest()[:12]


def index_title(folder):
    if is_dataless(folder / "INDEX.md"):
        return None
    try:
        with open(folder / "INDEX.md", encoding="utf-8") as f:
            for line in f:
                if line.startswith("# "):
                    t = line[2:].strip()
                    return re.sub(r"\.pdf$", "", t, flags=re.I)
    except OSError:
        pass
    return None


def tidy_name(stem):
    stem = re.sub(r"--?[0-9a-f]{32}$", "", stem)
    stem = re.sub(r"\s+--\s+.*$", "", stem)  # "Title -- Author -- year -- ..." download names
    return stem.replace("_", " ").strip() or "Untitled"


NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def local_bytes(path):
    """A file's bytes, or None when it is still in iCloud (reading it would stall on a download)."""
    if is_dataless(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def epub_reader(path):
    """read(name) -> bytes for a packed .epub file or an unpacked .epub folder (as Apple Books keeps them)."""
    if path.is_dir():
        def read(name):
            data = local_bytes(path / name)
            if data is None:
                raise TimeoutError("in iCloud")
            return data
        return read, None
    z = zipfile.ZipFile(path)
    return z.read, z


def clean_href(href):
    parts = []
    for seg in href.split("/"):
        if seg == "..":
            if parts:
                parts.pop()
        elif seg and seg != ".":
            parts.append(seg)
    return unquote("/".join(parts))


def epub_meta(path):
    """Title, author and cover href (inside the book) from the EPUB's package file."""
    out = {}
    read, z = epub_reader(path)
    try:
        container = ET.fromstring(read("META-INF/container.xml"))
        rootfile = container.find(".//c:rootfile", NS).get("full-path")
        opf = ET.fromstring(read(rootfile))
    finally:
        if z:
            z.close()
    base = rootfile.rsplit("/", 1)[0] + "/" if "/" in rootfile else ""
    t = opf.find(".//dc:title", NS)
    a = opf.findall(".//dc:creator", NS)
    if t is not None and (t.text or "").strip():
        out["title"] = " ".join(t.text.split())
    if a:
        out["author"] = ", ".join(" ".join((x.text or "").split()) for x in a if (x.text or "").strip())
    items = opf.findall(".//opf:manifest/opf:item", NS)
    cover = None
    for it in items:
        if "cover-image" in (it.get("properties") or ""):
            cover = it.get("href")
    if not cover:
        meta = opf.find(".//opf:metadata/opf:meta[@name='cover']", NS)
        if meta is not None:
            for it in items:
                if it.get("id") == meta.get("content"):
                    cover = it.get("href")
    if not cover:
        for it in items:
            if (it.get("media-type") or "").startswith("image/") and "cover" in (
                (it.get("id") or "") + (it.get("href") or "")
            ).lower():
                cover = it.get("href")
                break
    if cover:
        out["cover"] = clean_href(base + cover)
    return out


_library = {"at": 0, "books": {}}


def scan_paths(cfg, state):
    """Book files, and unpacked .epub folders, in the configured folders (never walking into a book)."""
    seen = []
    for folder in cfg.get("folders", []):
        root = Path(os.path.expanduser(folder))
        if not root.is_dir():
            continue
        root_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            here = Path(dirpath)
            keep = []
            for d in dirnames:
                if d.startswith("."):
                    continue
                if d.lower().endswith(".epub"):
                    seen.append(here / d)
                elif len(here.parts) - root_depth < SCAN_DEPTH - 1 and not is_dataless(here / d):
                    keep.append(d)
            dirnames[:] = keep
            for fn in filenames:
                p = here / fn
                if p.suffix.lower() in FORMATS and not fn.startswith("."):
                    seen.append(p)
    for added in state.get("added", []):
        p = Path(added)
        if p.exists():
            seen.append(p)
    return seen


def build_library(force=False):
    with _lock:
        if not force and time.time() - _library["at"] < 20 and _library["books"]:
            return _library["books"]
        cfg = load_config()
        state = load_state()
        meta_cache = state["meta"]
        titles_by_key = {}
        books = {}
        dirty = False
        for p in scan_paths(cfg, state):
            try:
                st = p.stat()
            except OSError:
                continue
            unpacked = p.is_dir()
            size = 0 if unpacked else st.st_size
            key = book_key(p, size if not unpacked else "dir")
            cloud = bool(getattr(st, "st_flags", 0) & SF_DATALESS)
            if unpacked and not cloud:
                cloud = is_dataless(p / "META-INF" / "container.xml") if (p / "META-INF").is_dir() else True
            t = None
            if ID_DIR.match(p.parent.name) or (p.parent / "INDEX.md").is_file():
                # The personal library keeps a title in INDEX.md, sometimes only in the sibling
                # folder of the same id in another library folder.
                t = index_title(p.parent)
                for folder in cfg.get("folders", []):
                    if t:
                        break
                    other = Path(os.path.expanduser(folder)) / p.parent.name
                    if other != p.parent and other.is_dir():
                        t = index_title(other)
            if t:
                titles_by_key.setdefault(key, t)
            fmt = FORMATS[p.suffix.lower()]
            sp = str(p)
            m = meta_cache.get(sp)
            if not m or m.get("mtime") != st.st_mtime or m.get("size") != size or m.get("error"):
                m = {"mtime": st.st_mtime, "size": size}
                if fmt == "epub" and not cloud:
                    try:
                        m.update(epub_meta(p))
                    except Exception as e:  # damaged, unusual or still-in-iCloud EPUB: fall back to the name
                        m["error"] = type(e).__name__
                if not cloud and not m.get("error"):
                    meta_cache[sp] = m
                    dirty = True
            books.setdefault(key, []).append({
                "id": key,
                "path": sp,
                "format": fmt,
                "unpacked": unpacked,
                "title": m.get("title"),
                "author": m.get("author"),
                "cover": m.get("cover"),
                "size": size,
                "cloud": cloud,
            })
        progress = state["progress"]
        merged = {}
        for key, copies in books.items():
            # Prefer a copy that is downloaded, then a packed file, then the first folder listed.
            copies.sort(key=lambda b: (b["cloud"], b["unpacked"]))
            best = dict(copies[0])
            for c in copies[1:]:
                for k in ("title", "author"):
                    best[k] = best[k] or c[k]
            raw = best["title"] or titles_by_key.get(key) or tidy_name(Path(best["path"]).stem)
            best["names"] = {" ".join(norm(raw)), " ".join(norm(clean_title(raw)))} - {""}
            best["title"] = clean_title(raw) or raw
            best["author"] = clean_author(best["author"])
            if best["cloud"]:
                best["cover"] = None
            merged[key] = best
        # The same book often sits in several places under different ids (Apple Books, the
        # personal library): show it once, keeping the copy that has reading progress.
        parent = {k: k for k in merged}

        def find(k):
            while parent[k] != k:
                parent[k] = parent[parent[k]]
                k = parent[k]
            return k

        owner = {}
        for b in merged.values():
            for n in b.pop("names"):
                nk = (n, b["format"])
                if nk in owner:
                    parent[find(b["id"])] = find(owner[nk])
                else:
                    owner[nk] = b["id"]
        groups = {}
        for b in merged.values():
            groups.setdefault(find(b["id"]), []).append(b)
        roots = [str(Path(os.path.expanduser(f)).resolve()) for f in cfg.get("folders", [])]

        def folder_rank(b):
            p = str(Path(b["path"]).resolve())
            return next((i for i, r in enumerate(roots) if p.startswith(r + os.sep)), len(roots))

        final = {}
        for copies in groups.values():
            # The id: the one with reading progress, else one with a learning index (book-<id>).
            copies.sort(key=lambda b: (-(progress.get(b["id"], {}).get("updated") or 0),
                                       not ID_DIR.match(Path(b["path"]).parent.name), b["cloud"], b["unpacked"]))
            book = dict(copies[0])
            # The file: a downloaded copy from the first folder listed (~/Documents/personal/books).
            src = min(copies, key=lambda b: (b["cloud"], folder_rank(b), b["unpacked"]))
            if src is not copies[0]:
                book.update({k: src[k] for k in ("path", "unpacked", "size", "cloud")})
                book["cover"] = None if src["cloud"] else (src["cover"] or book["cover"])
            final[book["id"]] = book
            for other in copies[1:]:
                book.setdefault("aliases", []).append(other["id"])
        if dirty:
            live = {b["path"] for c in books.values() for b in c}
            update_state(lambda s: s.update(meta={k: v for k, v in meta_cache.items() if k in live}))
        _library.update(at=time.time(), books=final, all=merged)
        return final


def get_book(book_id):
    """A book by id, including ids of duplicate copies that the library shows only once."""
    books = build_library()
    if book_id not in books and book_id not in _library.get("all", {}):
        books = build_library(force=True)
    return books.get(book_id) or _library.get("all", {}).get(book_id)


def public(book, state=None):
    state = state or load_state()
    pr = state["progress"].get(book["id"], {})
    return {
        "id": book["id"],
        "title": book["title"],
        "author": book.get("author"),
        "format": book["format"],
        "size": book["size"],
        "cloud": book["cloud"],
        "hasCover": bool(book.get("cover")),
        "unpacked": book.get("unpacked", False),
        "progress": {k: pr.get(k) for k in ("location", "percent", "label", "page", "pages", "updated") if k in pr},
        "url": f"{BASE_URL}/read/{book['id']}",
        "index": chapter_index(book),
    }


def chapter_index(book):
    """The book's chapter text and index (INDEX.md) beside its file, if it has one."""
    p = Path(book["path"])
    for d in (p.parent, p) if p.is_dir() else (p.parent,):
        if (d / "INDEX.md").is_file():
            return str(d / "INDEX.md")
    return None


def norm(s):
    return re.sub(r"[^\w\s]", " ", re.sub(r"['’]", "", (s or "").lower())).split()


def clean_title(t):
    """Drop store watermarks such as "(for Jane Doe)" or "(for True Epub)" from a title."""
    t = re.sub(r"\s*\(for [^)]*\)\s*$", "", t or "").strip()
    return t or None


def clean_author(a):
    if not a:
        return None
    parts = [x.strip() for x in re.split(r"[;\n]", a) if x.strip()]
    a = ", ".join(parts)
    return None if a.lower() in ("unknown", "author", "") else a


def search(query, books):
    q = norm(query)
    if not q:
        return []
    qs = " ".join(q)
    scored = []
    for b in books.values():
        hay = norm(b["title"]) + norm(b.get("author")) + norm(Path(b["path"]).stem)
        hay_s = " ".join(hay)
        title_s = " ".join(norm(b["title"]))
        hits = sum(1 for t in q if any(h.startswith(t) for h in hay))
        score = hits / len(q)
        if title_s == qs:
            score += 2
        elif title_s.startswith(qs):
            score += 1
        elif qs in hay_s:
            score += 0.5
        if score < 1:
            score = max(score, difflib.SequenceMatcher(None, qs, title_s).ratio() * 0.9)
        if score >= 0.6:
            scored.append((score, b))
    scored.sort(key=lambda x: (-x[0], x[1]["title"].lower()))
    return scored


# ---------------------------------------------------------------- HTTP server

class Handler(BaseHTTPRequestHandler):
    server_version = "BookReader/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _host_ok(self):
        host = (self.headers.get("Host") or "").lower()
        return host in (f"localhost:{PORT}", f"127.0.0.1:{PORT}", f"[::1]:{PORT}")

    def _send(self, code, body=b"", ctype="application/json", headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data, code=200):
        self._send(code, data, headers={"Cache-Control": "no-store"})

    def _file(self, path, ctype, cache="no-cache"):
        size = path.stat().st_size
        start, end = 0, size - 1
        rng = self.headers.get("Range")
        code = 200
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
            if m:
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                elif m.group(2):
                    start = max(0, size - int(m.group(2)))
                end = min(end, size - 1)
                if start > end:
                    self._send(416, b"", headers={"Content-Range": f"bytes */{size}"})
                    return
                code = 206
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", cache)
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            while left > 0:
                chunk = f.read(min(256 * 1024, left))
                if not chunk:
                    break
                self.wfile.write(chunk)
                left -= len(chunk)

    def _body(self):
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return None
        n = int(self.headers.get("Content-Length") or 0)
        if n > 5_000_000:
            return None
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return None

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad host"})
        try:
            self._get(urlparse(self.path))
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _get(self, u):
        p = u.path
        if p in ("/", "/index.html") or re.match(r"^/read/[0-9a-f]{12}$", p):
            return self._file(WEB_DIR / "index.html", MIME[".html"])
        if p.startswith("/static/"):
            target = (WEB_DIR / p[len("/static/"):]).resolve()
            if WEB_DIR.resolve() not in target.parents or not target.is_file():
                return self._send(404, {"error": "not found"})
            cache = "max-age=604800" if "/vendor/" in p else "no-cache"
            return self._file(target, MIME.get(target.suffix.lower(), "application/octet-stream"), cache)
        if p == "/api/ping":
            return self._json({"ok": True, "app": "book-reader", "version": self.server.version})
        if p == "/api/library":
            force = "refresh" in parse_qs(u.query)
            books = build_library(force=force)
            state = load_state()
            items = [public(b, state) for b in books.values()]
            items.sort(key=lambda b: (-(b["progress"].get("updated") or 0), b["title"].lower()))
            return self._json({"books": items, "current": state.get("current"), "folders": load_config()["folders"]})
        if p == "/api/settings":
            return self._json(load_state()["settings"])
        if p == "/api/state":
            return self._json(status_data())
        m = re.match(r"^/api/book/([0-9a-f]{12})(/file|/cover|/locations|/epub/.*)?$", p)
        if m:
            book = get_book(m.group(1))
            if not book:
                return self._json({"error": "unknown book"}, 404)
            part = m.group(2)
            if not part:
                return self._json(public(book))
            if part == "/file" and not book.get("unpacked"):
                return self._file(Path(book["path"]), MIME["." + book["format"]], "no-cache")
            if part.startswith("/epub/") and book.get("unpacked"):
                # The files of an unpacked .epub folder, which epub.js reads one by one.
                root = Path(book["path"]).resolve()
                target = (root / unquote(part[len("/epub/"):])).resolve()
                if root not in target.parents or not target.is_file():
                    return self._send(404, {"error": "not found"})
                ctype = MIME.get(target.suffix.lower()) or {
                    ".xhtml": "application/xhtml+xml", ".opf": "application/oebps-package+xml",
                    ".ncx": "application/x-dtbncx+xml", ".xml": "application/xml",
                    ".otf": "font/otf", ".woff": "font/woff", ".woff2": "font/woff2",
                }.get(target.suffix.lower(), "application/octet-stream")
                return self._file(target, ctype, "max-age=3600")
            if part == "/cover":
                if not book.get("cover"):
                    return self._send(404, {"error": "no cover"})
                try:
                    read, z = epub_reader(Path(book["path"]))
                    try:
                        data = read(book["cover"])
                    finally:
                        if z:
                            z.close()
                except (KeyError, OSError, zipfile.BadZipFile):
                    return self._send(404, {"error": "no cover"})
                ctype = MIME.get(Path(book["cover"]).suffix.lower(), "image/jpeg")
                return self._send(200, data, ctype, {"Cache-Control": "max-age=86400"})
            if part == "/locations":
                data = _read_json(LOC_DIR / f"{book['id']}.json", None)
                return self._json(data or {})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad host"})
        body = self._body()
        if body is None:
            return self._json({"error": "send JSON"}, 400)
        p = urlparse(self.path).path
        now = time.time()
        m = re.match(r"^/api/book/([0-9a-f]{12})/(progress|locations)$", p)
        if m:
            book_id, what = m.groups()
            if not get_book(book_id):
                return self._json({"error": "unknown book"}, 404)
            if what == "locations":
                _write_json(LOC_DIR / f"{book_id}.json", {"locations": body.get("locations"), "chars": body.get("chars")})
                return self._json({"ok": True})

            def save(s):
                pr = {k: body.get(k) for k in ("location", "percent", "label", "page", "pages") if k in body}
                pr["updated"] = now
                s["progress"][book_id] = {**s["progress"].get(book_id, {}), **pr}
                s["current"] = book_id
                text = (body.get("text") or "")[:6000]
                s["visible"] = {"id": book_id, "text": text, "label": body.get("label"), "updated": now}

            update_state(save)
            return self._json({"ok": True})
        if p == "/api/selection":
            text = (body.get("text") or "").strip()[:6000]
            book_id = body.get("id")
            if text and get_book(book_id or ""):
                update_state(lambda s: s.update(selection={"id": book_id, "text": text, "label": body.get("label"), "updated": now}))
            return self._json({"ok": True})
        if p == "/api/settings":
            allowed = {"theme", "fontSize", "font", "lineHeight", "flow", "pdfFlow", "pdfZoom"}
            update_state(lambda s: s["settings"].update({k: v for k, v in body.items() if k in allowed}))
            return self._json({"ok": True})
        return self._json({"error": "not found"}, 404)


def serve():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    httpd.daemon_threads = True
    httpd.version = code_version()
    PID_FILE.write_text(str(os.getpid()))
    def on_term(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, on_term)
    print(f"Book Reader on {BASE_URL} (pid {os.getpid()})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            if PID_FILE.read_text().strip() == str(os.getpid()):
                PID_FILE.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------- CLI

def ping():
    try:
        with urllib.request.urlopen(f"{BASE_URL}/api/ping", timeout=1.5) as r:
            data = json.loads(r.read())
            return data if data.get("app") == "book-reader" else None
    except Exception:
        return None


def stop():
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        for _ in range(30):
            time.sleep(0.1)
            if not ping():
                break
    except (OSError, ValueError):
        pass


def start():
    running = ping()
    if running and running.get("version") == code_version():
        return
    if running:
        stop()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log = open(LOG_FILE, "ab")
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "serve"],
        stdin=subprocess.DEVNULL, stdout=log, stderr=log,
        cwd=str(DATA_DIR), start_new_session=True, close_fds=True,
    )
    for _ in range(60):
        time.sleep(0.1)
        if ping():
            return
    sys.exit(f"The reader server did not start. Log: {LOG_FILE}")


def ago(ts):
    if not ts:
        return "never"
    d = time.time() - ts
    if d < 90:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if d < 86400:
        return f"{int(d // 3600)} h ago"
    return f"{int(d // 86400)} days ago"


def status_data():
    s = load_state()
    cur = s.get("current")
    book = get_book(cur) if cur else None
    out = {"current": public(book, s) if book else None}
    vis = s.get("visible") or {}
    if book and vis.get("id") == cur:
        out["visible"] = vis
    sel = s.get("selection") or {}
    if sel.get("text"):
        b = get_book(sel.get("id") or "")
        out["selection"] = {**sel, "title": b["title"] if b else None}
    return out


def print_status():
    d = status_data()
    b = d.get("current")
    if not b:
        print("Nothing has been opened in the reader yet.")
        return
    pr = b["progress"]
    pct = f"{pr['percent'] * 100:.1f}%" if isinstance(pr.get("percent"), (int, float)) else "?"
    print(f"Book: {b['title']}" + (f" by {b['author']}" if b.get("author") else "") + f" ({b['format'].upper()}, id {b['id']})")
    where = pr.get("label") or ""
    if pr.get("page") and pr.get("pages"):
        where = f"page {pr['page']} of {pr['pages']}" + (f", {where}" if where and "page" not in where.lower() else "")
    print(f"Position: {where} at {pct}, updated {ago(pr.get('updated'))}")
    print(f"URL: {b['url']}")
    if b.get("index"):
        print(f"Chapter text and index: {b['index'].replace(str(Path.home()), '~')}")
    sel = d.get("selection")
    if sel:
        print(f"\nLast selected text ({ago(sel['updated'])}, in {sel.get('title') or 'another book'}):")
        print(sel["text"])
    vis = d.get("visible")
    if vis and vis.get("text"):
        print(f"\nText on screen ({ago(vis['updated'])}):")
        print(vis["text"])


def add_path(arg):
    p = Path(os.path.expanduser(arg)).resolve()
    if p.is_dir() and p.suffix.lower() != ".epub":
        cfg = load_config()
        if str(p) not in [str(Path(os.path.expanduser(f)).resolve()) for f in cfg["folders"]]:
            cfg["folders"].append(str(p))
            _write_json(CONFIG_FILE, cfg)
        build_library(force=True)
        return None
    if p.exists() and p.suffix.lower() in FORMATS:
        update_state(lambda s: s["added"].append(str(p)) if str(p) not in s["added"] else None)
        build_library(force=True)
        return get_book(book_key(p, "dir" if p.is_dir() else p.stat().st_size))
    sys.exit(f"Not an EPUB or PDF file, or a folder: {p}")


def main(argv):
    cmd = argv[0] if argv else "open"
    rest = argv[1:]
    if cmd == "serve":
        serve()
    elif cmd == "start":
        start()
        print(json.dumps({"ok": True, "url": BASE_URL + "/"}))
    elif cmd == "stop":
        stop()
        print("stopped")
    elif cmd == "restart":
        stop()
        start()
        print(json.dumps({"ok": True, "url": BASE_URL + "/"}))
    elif cmd == "status":
        print_status()
    elif cmd == "folders":
        for f in load_config()["folders"]:
            print(f, "" if Path(os.path.expanduser(f)).is_dir() else "(missing)")
    elif cmd == "add":
        if not rest:
            sys.exit("usage: reader.py add PATH")
        book = add_path(" ".join(rest))
        print(json.dumps(public(book) if book else {"ok": True, "folders": load_config()["folders"]}, ensure_ascii=False, indent=1))
    elif cmd == "list":
        books = build_library(force=True)
        state = load_state()
        rows = [b for _, b in search(" ".join(rest), books)] if rest else sorted(
            books.values(), key=lambda b: (-(state["progress"].get(b["id"], {}).get("updated") or 0), b["title"].lower()))
        for b in rows:
            pr = state["progress"].get(b["id"], {})
            pct = f"{pr['percent'] * 100:.0f}%" if isinstance(pr.get("percent"), (int, float)) else "-"
            print(f"{b['id']}  {b['format']:4}  {pct:>4}  {b['title']}" + (f" / {b['author']}" if b.get("author") else ""))
        print(f"\n{len(rows)} book(s)")
    elif cmd == "open":
        start()
        state = load_state()
        query = " ".join(a for a in rest if a != "--last").strip()
        if "--last" in rest or not query:
            cur = state.get("current")
            book = get_book(cur) if cur and "--last" in rest else None
            if book:
                print(json.dumps({"url": public(book)["url"], "book": public(book)}, ensure_ascii=False, indent=1))
            else:
                last = get_book(cur) if cur else None
                print(json.dumps({"url": BASE_URL + "/", "view": "library", "lastRead": public(last) if last else None}, ensure_ascii=False, indent=1))
            return
        path = Path(os.path.expanduser(query))
        if path.exists():
            book = add_path(query)
            if book:
                print(json.dumps({"url": public(book)["url"], "book": public(book)}, ensure_ascii=False, indent=1))
            else:
                print(json.dumps({"url": BASE_URL + "/", "view": "library", "addedFolder": str(path)}, ensure_ascii=False, indent=1))
            return
        books = build_library(force=True)
        found = search(query, books)
        if not found:
            print(json.dumps({"error": "no match", "query": query, "url": BASE_URL + "/"}, ensure_ascii=False, indent=1))
        elif len(found) == 1 or found[0][0] - found[1][0] >= 0.5:
            b = public(found[0][1], state)
            print(json.dumps({"url": b["url"], "book": b}, ensure_ascii=False, indent=1))
        else:
            print(json.dumps({"ambiguous": True, "query": query,
                              "matches": [{"id": b["id"], "title": b["title"], "author": b.get("author"),
                                           "format": b["format"], "url": f"{BASE_URL}/read/{b['id']}"}
                                          for _, b in found[:8]]}, ensure_ascii=False, indent=1))
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
