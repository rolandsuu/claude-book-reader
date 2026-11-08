#!/usr/bin/env python3
"""Local acquisition ledger and evidence-backed reading snapshots. No collector or scheduler."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit

DEFAULT_STORE = Path.home() / "Documents/personal/learning/reading-taste/tracker.json"
META = ("title", "author", "language", "format", "edition", "year", "translator", "volume", "isbn")


def now():
    return datetime.now(timezone.utc).isoformat()


def empty():
    return {"version": 1, "settings": {"app": None, "source": None,
            "source_confirmed": False, "cadence": None, "timezone": None,
            "schedule_status": "not_configured"}, "books": {}, "observations": [], "preferences": []}


def read_json(path):
    path = Path(path).expanduser()
    if path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("Refusing symlink or oversized JSON input")
    return json.loads(path.read_text(encoding="utf-8"))


@contextmanager
def store(path):
    path = Path(path).expanduser().absolute()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError("Refusing symlink store")
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = read_json(path) if path.exists() else empty()
        if data.get("version") != 1:
            raise ValueError("Unsupported tracker version")
        yield data
        handle, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tracker-")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                json.dump(data, out, ensure_ascii=False, indent=2, allow_nan=False)
                out.write("\n")
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, path)
        finally:
            Path(tmp).unlink(missing_ok=True)


def text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected nonempty text")
    return value


def timestamp(value):
    parsed = datetime.fromisoformat(text(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Observation time requires a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def metadata(value):
    # annas_books.py copies plan fields into receipts as-is, so year and volume can be
    # positive integers; store them as text like every other metadata field.
    result = {}
    for key in META:
        if key in value:
            item = value[key]
            if key in ("year", "volume") and type(item) is int and item > 0:
                item = str(item)
            result[key] = text(item)
    return result


def ingest_receipt(data, receipt, receipt_path):
    if receipt.get("download") != "verified":
        raise ValueError("Receipt does not record a verified acquisition")
    algorithm = "sha256" if "sha256" in receipt else "md5"
    digest = receipt.get(algorithm, "")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{" + ("64" if algorithm == "sha256" else "32") + r"}", digest):
        raise ValueError("Receipt needs a file identity")
    source = urlsplit(text(receipt.get("source")))
    if source.scheme != "https" or not source.netloc or source.query or source.username or source.fragment:
        raise ValueError("Use a public HTTPS metadata source without credentials or query parameters")
    identity = algorithm + ":" + digest
    book = data["books"].setdefault(identity, {"metadata": {}, "acquisitions": []})
    book["metadata"].update(metadata(receipt))
    record = {"receipt_path": str(Path(receipt_path).absolute()), "source": receipt["source"],
              "file_path": text(receipt.get("path")), "recorded_at": receipt.get("acquired_at"),
              "discovered_at": now(), "download": "verified", "books_handoff": receipt.get("books_handoff", "unknown")}
    # A repeat sync updates the handoff, retaining original discovery time.
    previous = next((x for x in book["acquisitions"] if x["receipt_path"] == record["receipt_path"]), None)
    if previous:
        record["discovered_at"] = previous["discovered_at"]
        previous.update(record)
    else:
        book["acquisitions"].append(record)
    return identity


def ingest_observation(data, event):
    allowed = {"observed_at", "app", "device", "source", "evidence", "book_id", "metadata",
               "presence", "progress_percent", "minutes", "minutes_scope", "period", "feedback", "note"}
    if set(event) - allowed:
        raise ValueError("Unknown observation fields")
    event = dict(event)
    event["observed_at"] = timestamp(event.get("observed_at"))
    for key in ("app", "device", "evidence"):
        text(event.get(key))
    if event.get("source") not in ("ui", "user", "documented_api", "user_export"):
        raise ValueError("Unsupported observation source")
    if event.get("presence", "unknown") not in ("present", "absent", "unknown"):
        raise ValueError("Invalid presence")
    for key, upper in (("progress_percent", 100), ("minutes", float("inf"))):
        value = event.get(key)
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= upper):
            raise ValueError("Invalid progress or minutes")
    identity = event.get("book_id")
    scope = event.get("minutes_scope")
    if event.get("minutes") is not None:
        if scope not in ("book_cumulative", "book_session", "app_day"):
            raise ValueError("Minutes require an explicit scope")
        if (scope == "app_day") != (identity is None):
            raise ValueError("Do not assign app-wide time to a book")
        text(event.get("period"))
    if not identity and (event.get("progress_percent") is not None or "presence" in event or "feedback" in event):
        raise ValueError("Book fields require a book identity")
    if event.get("feedback") not in (None, "liked", "disliked", "neutral", "paused", "finished"):
        raise ValueError("Invalid feedback")
    if identity:
        text(identity)
        meta = metadata(event.pop("metadata", {}))
        if identity not in data["books"]:
            text(meta.get("title"))
        book = data["books"].setdefault(identity, {"metadata": {}, "acquisitions": []})
        book["metadata"].update(meta)
    encoded = json.dumps(event, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    event["id"] = hashlib.sha256(encoded).hexdigest()
    if not any(x["id"] == event["id"] for x in data["observations"]):
        data["observations"].append(event)
    return event["id"]


def summary(data):
    result = {"settings": data["settings"], "books": [], "app_reading_time": [], "preferences": data["preferences"]}
    events = sorted(data["observations"], key=lambda x: x["observed_at"])
    for identity, book in data["books"].items():
        matching = [x for x in events if x.get("book_id") == identity]
        row = {"book_id": identity, **book, "acquisition_provenance": "recorded" if book["acquisitions"] else "unknown",
               "latest_observation": matching[-1] if matching else None}
        result["books"].append(row)
    result["app_reading_time"] = [x for x in events if x.get("minutes_scope") == "app_day"]
    return result


def ingest_preference(data, entry):
    fields = {"statement", "basis", "confidence", "evidence", "book_ids", "updated_at"}
    if set(entry) != fields:
        raise ValueError("Preference requires statement, basis, confidence, evidence, book_ids and updated_at")
    text(entry["statement"])
    if (entry["basis"], entry["confidence"]) not in (("explicit", "confirmed"), ("inferred", "tentative")):
        raise ValueError("Only explicit preferences can be confirmed")
    if not isinstance(entry["evidence"], list) or not entry["evidence"]:
        raise ValueError("Preference requires supporting evidence")
    for item in entry["evidence"]:
        text(item)
        if entry["basis"] == "inferred" and not any(x["id"] == item for x in data["observations"]):
            raise ValueError("Inferred preferences must cite recorded observations")
    if not isinstance(entry["book_ids"], list) or any(x not in data["books"] for x in entry["book_ids"]):
        raise ValueError("Unknown supporting book")
    entry = dict(entry, updated_at=timestamp(entry["updated_at"]))
    if entry not in data["preferences"]:
        data["preferences"].append(entry)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("summary")
    receipts = commands.add_parser("receipts")
    receipts.add_argument("paths", type=Path, nargs="+")
    observe = commands.add_parser("observe")
    observe.add_argument("--input", type=Path, required=True)
    preference = commands.add_parser("preference")
    preference.add_argument("--input", type=Path, required=True)
    try:
        if args := parser.parse_args():
            if args.command == "summary":
                print(json.dumps(summary(read_json(args.store)), ensure_ascii=False, indent=2))
                return
            with store(args.store) as data:
                if args.command == "receipts":
                    for path in args.paths:
                        ingest_receipt(data, read_json(path), path)
                elif args.command == "observe":
                    events = read_json(args.input)
                    for event in events if isinstance(events, list) else [events]:
                        ingest_observation(data, event)
                elif args.command == "preference":
                    ingest_preference(data, read_json(args.input))
            print(json.dumps({"status": "saved", "store": str(args.store), "schedule": "not configured by this helper"}))
    except (ValueError, TypeError, KeyError, OSError):
        parser.exit(1, "Invalid or inaccessible tracker input; inspect local files.\n")


if __name__ == "__main__":
    main()
