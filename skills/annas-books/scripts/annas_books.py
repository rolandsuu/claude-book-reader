#!/usr/bin/env python3
"""Public search links, reviewed acquisition plans, private fast-download client."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

DOMAINS = ("annas-archive.pk", "annas-archive.gd", "annas-archive.gl")
KEY_ENV = "ANNAS_ARCHIVE_API_KEY"
KEY_SERVICE = "codex.annas-books"
KEY_ACCOUNT = "fast-download"
MD5 = re.compile(r"[0-9a-f]{32}")
MAX_JSON = 256 * 1024
MAX_BYTES = 1024 * 1024 * 1024
# A local proxy in fake-IP mode (Clash, Surge, Stash...) resolves every hostname into
# this benchmark range. Accepted only when the CLI's --allow-fake-ip flag sets
# ALLOW_FAKE_IP; every other non-global address stays rejected.
FAKE_IP_NET = ipaddress.ip_network("198.18.0.0/15")
ALLOW_FAKE_IP = False


class BookError(Exception):
    """Only fixed, non-secret messages should escape to the CLI."""


def norm(value):
    return " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split())


def isbn13(value):
    text = re.sub(r"[\s-]", "", str(value)).upper()
    if len(text) == 10 and re.fullmatch(r"\d{9}[\dX]", text):
        digits = [int(x) if x != "X" else 10 for x in text]
        if sum((10 - i) * n for i, n in enumerate(digits)) % 11:
            raise BookError("Invalid ISBN checksum.")
        text = "978" + text[:9]
        text += str((-sum(int(x) * (1 if i % 2 == 0 else 3)
                              for i, x in enumerate(text))) % 10)
    if not re.fullmatch(r"97[89]\d{10}", text) or sum(
        int(x) * (1 if i % 2 == 0 else 3) for i, x in enumerate(text)
    ) % 10:
        raise BookError("Invalid ISBN checksum or length.")
    return text


def validate_plan(plan):
    if not isinstance(plan, dict) or plan.get("version") != 1:
        raise BookError("Plan must have version 1.")
    books = plan.get("books")
    if not isinstance(books, list) or not books:
        raise BookError("Plan requires a nonempty books list.")
    seen = set()
    for book in books:
        if not isinstance(book, dict):
            raise BookError("Each book must be an object.")
        request, match = book.get("request"), book.get("match")
        review, access = book.get("review"), book.get("access")
        if not all(isinstance(x, dict) for x in (request, match, review, access)):
            raise BookError("Each book needs request, match, review and access objects.")
        for key in ("title", "author", "language", "format", "url", "md5"):
            if not isinstance(match.get(key), str) or not match[key].strip():
                raise BookError("Matched title, author, language, format, URL and MD5 are required.")
        if not isinstance(request.get("title"), str) or not request["title"].strip():
            raise BookError("Requested title is required.")
        if match["format"] not in ("epub", "pdf"):
            raise BookError("Only EPUB and PDF files are supported.")
        digest = match["md5"]
        if not MD5.fullmatch(digest) or digest in seen:
            raise BookError("Invalid or duplicate MD5 in plan.")
        seen.add(digest)
        url = urllib.parse.urlsplit(match["url"])
        if (url.scheme != "https" or url.netloc not in DOMAINS or url.query
                or url.fragment or url.path != "/md5/" + digest):
            raise BookError("Book URL must be an exact HTTPS MD5 detail URL on an approved mirror.")
        if review.get("confirmed") is not True or not str(review.get("note", "")).strip():
            raise BookError("An explicit identity review and note are required.")
        for key in ("language", "edition", "year", "translator", "volume", "format"):
            if request.get(key) not in (None, ""):
                if match.get(key) in (None, "") or norm(request[key]) != norm(match[key]):
                    raise BookError("Requested metadata is missing or conflicts: " + key)
        if match.get("isbn"):
            isbn13(match["isbn"])
        if request.get("isbn") and (not match.get("isbn") or
                                    isbn13(request["isbn"]) != isbn13(match["isbn"])):
            raise BookError("Requested ISBN is missing or differs from the selected edition.")
        if access.get("basis") not in ("public-domain", "open-license", "permission"):
            raise BookError("A supported lawful-access basis is required for every book.")
        if access.get("confirmed_by") not in ("user", "source") or not isinstance(
                access.get("evidence"), str) or not access["evidence"].strip():
            raise BookError("Record the access source or explicit user statement.")
        if access["basis"] == "public-domain" and not str(access.get("territory", "")).strip():
            raise BookError("Public-domain access requires the applicable territory.")
        if "size_bytes" in match and (type(match["size_bytes"]) is not int or match["size_bytes"] <= 0):
            raise BookError("size_bytes must be a positive integer when provided.")
    return books


def load_plan(path):
    try:
        plan = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, http.client.HTTPException):
        raise BookError("Cannot read a valid JSON plan.") from None
    return validate_plan(plan)


def load_key():
    # Remove the environment copy before launching any child application.
    secret = os.environ.pop(KEY_ENV, "").strip()
    if not secret and sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["/usr/bin/security", "find-generic-password", "-s", KEY_SERVICE,
                 "-a", KEY_ACCOUNT, "-w"], capture_output=True, timeout=30, check=False)
            if result.returncode == 0:
                secret = result.stdout.decode("utf-8").strip()
        except (OSError, subprocess.SubprocessError, UnicodeError):
            pass
    if not secret:
        raise BookError("No API key available. Configure Keychain or ANNAS_ARCHIVE_API_KEY privately.")
    if any(ord(c) < 32 for c in secret):
        raise BookError("API key contains invalid control characters.")
    return secret


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def allowed_address(text):
    address = ipaddress.ip_address(text)
    return address.is_global or (ALLOW_FAKE_IP and address in FAKE_IP_NET)


def public_https(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)
                or parsed.fragment or any(ord(c) < 33 for c in url)):
            raise ValueError()
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not allowed_address(addr[4][0]) for addr in addresses):
            raise ValueError()
    except (ValueError, OSError):
        raise BookError("Download URL must resolve to a public HTTPS server on port 443.") from None


def request_once(url, timeout=30):
    # No browser cookies, proxy credentials, Referer, or automatic redirects.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "Codex-AnnasBooks/1.0"})
    try:
        return opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as response:
        return response
    except (OSError, ValueError) as error:
        # Name only the host and the error class: never the path, query, key or signature.
        host = urllib.parse.urlsplit(url).hostname or "unknown host"
        cause = type(getattr(error, "reason", error)).__name__
        raise BookError("Network request to %s failed (%s); no automatic retry was made." % (host, cause)) from None


def get_fast_url(domain, digest, secret):
    if domain not in DOMAINS or not MD5.fullmatch(digest):
        raise BookError("Invalid API domain or file identifier.")
    url = "https://" + domain + "/dyn/api/fast_download.json?" + urllib.parse.urlencode(
        {"md5": digest, "key": secret})
    # An authenticated request is never redirected, even to another mirror.
    with request_once(url) as response:
        status = response.status
        if status not in (200, 204):
            raise BookError("Fast-download API failed (HTTP %d); check membership/quota/connectivity privately. No retry was made." % status)
        raw = response.read(MAX_JSON + 1)
        if len(raw) > MAX_JSON:
            raise BookError("API response exceeds the allowed size.")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        raise BookError("API returned no usable JSON (including a possible empty HTTP 204).") from None
    if not isinstance(data, dict) or data.get("error") or not isinstance(data.get("download_url"), str):
        raise BookError("API returned an error or an unsupported response schema; inspect documentation without credentials.")
    download_url = data["download_url"]
    if secret in urllib.parse.unquote(download_url):
        raise BookError("Refusing a download URL containing the account key.")
    public_https(download_url)
    return download_url


def download(url, path, secret, max_bytes=MAX_BYTES):
    for _ in range(6):
        public_https(url)
        if secret in urllib.parse.unquote(url):
            raise BookError("Refusing to forward the account key to a download server.")
        with request_once(url, timeout=60) as response:
            if response.status in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    raise BookError("Download redirect has no destination.")
                url = urllib.parse.urljoin(url, location)
                continue
            if response.status != 200:
                raise BookError("File download failed (HTTP %d); no retry was made." % response.status)
            size = response.headers.get("Content-Length")
            if size and (not size.isdigit() or int(size) > max_bytes):
                raise BookError("Invalid or excessive download size.")
            total = 0
            deadline = time.monotonic() + 900
            with path.open("wb") as target:
                while True:
                    if time.monotonic() > deadline:
                        raise BookError("Download exceeded the 15-minute time limit.")
                    chunk = response.read(128 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        raise BookError("Download exceeds the configured size limit.")
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
            if not total or (size and total != int(size)):
                raise BookError("File download is empty or incomplete.")
            return
    raise BookError("Too many download redirects.")


def bounded_xml(archive, name):
    info = archive.getinfo(name)
    if info.file_size > 2 * 1024 * 1024:
        raise BookError("EPUB metadata exceeds the allowed size.")
    raw = archive.read(name)
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise BookError("EPUB metadata has unsupported XML declarations.")
    return ET.fromstring(raw)


def validate_file(path, match):
    if path.is_symlink() or not path.is_file():
        raise BookError("Expected a regular, non-symlink book file.")
    digest = hashlib.md5()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(128 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != match["md5"]:
        raise BookError("File MD5 does not match the selected record; file will not be imported.")
    if match.get("size_bytes") and path.stat().st_size != match["size_bytes"]:
        raise BookError("File size differs from the selected record.")
    if match["format"] == "pdf":
        with path.open("rb") as stream:
            head = stream.read(1024)
            stream.seek(max(0, path.stat().st_size - 2048))
            tail = stream.read()
        if not head.startswith(b"%PDF-") or b"%%EOF" not in tail:
            raise BookError("File does not have a valid PDF envelope.")
        # This is a structural sanity check, not a full PDF parser or malware scanner.
        return
    try:
        with zipfile.ZipFile(path) as archive:
            if len(archive.infolist()) > 20000 or sum(x.file_size for x in archive.infolist()) > 2 * MAX_BYTES:
                raise BookError("EPUB archive exceeds the allowed expanded size or entry count.")
            if archive.getinfo("mimetype").file_size > 100 or archive.read("mimetype") != b"application/epub+zip":
                raise BookError("File is not an EPUB archive.")
            container = bounded_xml(archive, "META-INF/container.xml")
            rootfiles = container.findall(".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile")
            if not rootfiles or not rootfiles[0].get("full-path"):
                raise BookError("EPUB has no package document.")
            package = bounded_xml(archive, rootfiles[0].get("full-path"))
            if package.tag != "{http://www.idpf.org/2007/opf}package":
                raise BookError("EPUB package document is invalid.")
            # Font obfuscation is valid EPUB; other encryption requires manual review.
            if "META-INF/encryption.xml" in archive.namelist():
                encryption = bounded_xml(archive, "META-INF/encryption.xml")
                methods = encryption.findall(".//{http://www.w3.org/2001/04/xmlenc#}EncryptionMethod")
                allowed = {"http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC"}
                if not methods or any(m.get("Algorithm") not in allowed for m in methods):
                    raise BookError("EPUB encryption requires review; DRM removal is not supported.")
    except (zipfile.BadZipFile, KeyError, ET.ParseError, RuntimeError, NotImplementedError):
        raise BookError("EPUB structure cannot be validated.") from None


def atomic_json(path, data):
    fd, temporary = tempfile.mkstemp(prefix=".receipt-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def handoff(path):
    if sys.platform != "darwin":
        raise BookError("Books handoff requires macOS; the verified download has been retained.")
    try:
        result = subprocess.run(["/usr/bin/open", "-b", "com.apple.iBooksX", str(path)],
                                capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        raise BookError("Books handoff failed; use Books > File > Import for the saved file.") from None
    if result.returncode:
        raise BookError("Books handoff failed; use Books > File > Import for the saved file.")


def fetch(books, dest, domain, import_books=False, max_bytes=MAX_BYTES):
    # Validate again for callers outside the CLI; no credential access before this gate.
    validate_plan({"version": 1, "books": books})
    if max_bytes <= 0:
        raise BookError("Download size limit must be positive.")
    dest = Path(dest).expanduser().resolve()
    dest.mkdir(mode=0o700, parents=True, exist_ok=True)
    secret = None
    results = []
    for book in books:
        match = book["match"]
        slug = re.sub(r"[^\w .()-]", "_", match["title"]).strip(" .")[:80] or "book"
        path = dest / (slug + "--" + match["md5"] + "." + match["format"])
        receipt_path = dest / (".receipt-" + match["md5"] + ".json")
        receipt = {}
        if receipt_path.is_symlink():
            raise BookError("Refusing a symlink receipt.")
        if receipt_path.exists():
            try:
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                if not isinstance(receipt, dict):
                    raise ValueError()
            except (OSError, ValueError):
                raise BookError("Cannot read existing receipt; inspect it before retrying.") from None
        new_download = False
        if path.exists() or path.is_symlink():
            validate_file(path, match)
        else:
            if match.get("size_bytes", 0) > max_bytes:
                raise BookError("Selected file exceeds the configured download size limit.")
            if secret is None:
                secret = load_key()
            url = get_fast_url(domain, match["md5"], secret)
            fd, partial = tempfile.mkstemp(prefix=".download-", suffix=".part", dir=dest)
            os.close(fd)
            partial = Path(partial)
            try:
                download(url, partial, secret, max_bytes)
                validate_file(partial, match)
                # Atomic publish without overwriting a file that appeared meanwhile.
                os.link(partial, path)
                new_download = True
            finally:
                partial.unlink(missing_ok=True)
            receipt = {}
        # Store only stable metadata, never the key, account info or signed URL.
        receipt.update({"version": 1, "md5": match["md5"], "path": str(path),
                        "source": match["url"], "format": match["format"],
                        "download": "verified", "access": book["access"]})
        for field in ("title", "author", "language", "edition", "year", "translator", "volume", "isbn"):
            if field in match:
                receipt[field] = match[field]
        # Discovery time of a legacy receipt is not the original acquisition time.
        if new_download:
            receipt["acquired_at"] = datetime.now(timezone.utc).isoformat()
        else:
            receipt.setdefault("acquired_at", None)
        atomic_json(receipt_path, receipt)
        if import_books and receipt.get("books_handoff") != "submitted":
            # Also remove an inherited key on cache-only runs before opening Books.
            os.environ.pop(KEY_ENV, None)
            handoff(path)
            receipt["books_handoff"] = "submitted"
            atomic_json(receipt_path, receipt)
        result = {"title": match["title"], "path": str(path),
                  "status": "handoff submitted; verify in Books" if receipt.get("books_handoff") == "submitted" else "downloaded"}
        results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    search = commands.add_parser("search-links", help="Generate public searches on all three mirrors; no network")
    search.add_argument("--query", required=True)
    check = commands.add_parser("check-plan", help="Validate a reviewed plan without network or credentials")
    check.add_argument("--plan", required=True, type=Path)
    get = commands.add_parser("fetch", help="Download reviewed authorized files to the local knowledge library")
    get.add_argument("--plan", required=True, type=Path)
    get.add_argument("--domain", choices=DOMAINS, default="annas-archive.gd")
    get.add_argument("--dest", type=Path, default=Path.home() / "Documents/personal/books")
    get.add_argument("--import-books", action="store_true", default=False,
                     help="Optional Apple Books handoff; use only when explicitly requested")
    get.add_argument("--max-mib", type=int, default=1024)
    get.add_argument("--allow-fake-ip", action="store_true", default=False,
                     help="Accept 198.18.0.0/15 addresses from a local fake-IP proxy; other private addresses stay rejected")
    args = parser.parse_args()
    global ALLOW_FAKE_IP
    ALLOW_FAKE_IP = getattr(args, "allow_fake_ip", False)
    try:
        if args.command == "search-links":
            if not args.query.strip():
                raise BookError("Search query cannot be empty.")
            print(json.dumps(["https://" + d + "/search?" + urllib.parse.urlencode({"q": args.query})
                              for d in DOMAINS], ensure_ascii=False, indent=2))
        elif args.command == "check-plan":
            books = load_plan(args.plan)
            print(json.dumps({"valid": True, "books": len(books)}))
        else:
            fetch(load_plan(args.plan), args.dest, args.domain, args.import_books, args.max_mib * 1024 * 1024)
    except BookError as error:
        print("Error: " + str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, http.client.HTTPException):
        # Do not expose URLs/headers/response content through exception messages.
        print("Error: Operation failed. Saved files were retained; no automatic retry was made.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted; do not repeat an authenticated request without checking quota.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
