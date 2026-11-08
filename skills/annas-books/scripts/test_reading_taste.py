"""Synthetic offline tests; no app or personal reading data access."""
import copy
import tempfile
from pathlib import Path
import unittest

import reading_taste as tracker


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.data = tracker.empty()
        self.event = {"observed_at": "2026-10-17T21:00:00+08:00", "app": "Fixture Reader",
                      "device": "Fixture Mac", "source": "ui", "evidence": "Synthetic library row",
                      "book_id": "library:fixture", "metadata": {"title": "Original Fixture"},
                      "presence": "present", "progress_percent": 16, "minutes": None}

    def test_unknown_acquisition_and_idempotent_snapshots(self):
        tracker.ingest_observation(self.data, self.event)
        tracker.ingest_observation(self.data, self.event)
        self.assertEqual(len(self.data["observations"]), 1)
        row = tracker.summary(self.data)["books"][0]
        self.assertEqual(row["acquisition_provenance"], "unknown")
        self.assertIsNone(row["latest_observation"]["minutes"])
        self.assertEqual(self.data["settings"]["schedule_status"], "not_configured")

    def test_invalid_values_and_aggregate_time_cannot_be_per_book(self):
        for update in ({"progress_percent": 101}, {"minutes": -1}, {"minutes": float("nan")},
                       {"minutes": True}, {"observed_at": "2026-10-17T21:00:00"},
                       {"minutes": 5, "minutes_scope": "app_day", "period": "2026-10-17"}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                tracker.ingest_observation(tracker.empty(), dict(self.event, **update))

    def test_app_time_retains_snapshots_without_summing(self):
        event = {key: value for key, value in self.event.items() if key not in
                 ("book_id", "metadata", "presence", "progress_percent")}
        event.update(minutes=5, minutes_scope="app_day", period="2026-10-17")
        tracker.ingest_observation(self.data, event)
        tracker.ingest_observation(self.data, event)
        event.update(minutes=6, observed_at="2026-10-17T22:00:00+08:00")
        tracker.ingest_observation(self.data, event)
        self.assertEqual([x["minutes"] for x in tracker.summary(self.data)["app_reading_time"]], [5, 6])
        self.assertFalse(self.data["books"])

    def test_receipt_dedup_handoff_never_establishes_presence(self):
        receipt = {"md5": "a" * 32, "source": "https://example.com/original",
                   "path": "/fixture/book.epub", "title": "Original Fixture", "download": "verified",
                   "books_handoff": "submitted", "secret": "must-not-be-copied"}
        for _ in range(2):
            tracker.ingest_receipt(self.data, receipt, "/fixture/receipt.json")
        row = tracker.summary(self.data)["books"][0]
        self.assertEqual(len(row["acquisitions"]), 1)
        self.assertIsNone(row["latest_observation"])
        self.assertNotIn("must-not-be-copied", str(self.data))
        self.assertIsNone(row["acquisitions"][0]["recorded_at"])

    def test_fetch_receipt_numeric_year_and_volume_become_text(self):
        # annas_books.py writes plan fields as-is, so a year arrives as an integer.
        receipt = {"md5": "b" * 32, "source": "https://example.com/original", "path": "/fixture/book.epub",
                   "title": "Original Fixture", "download": "verified", "year": 2020, "volume": 2}
        identity = tracker.ingest_receipt(self.data, receipt, "/fixture/receipt.json")
        meta = self.data["books"][identity]["metadata"]
        self.assertEqual((meta["year"], meta["volume"]), ("2020", "2"))
        for bad in ({"year": True}, {"year": 0}, {"year": 2020.0}, {"year": ""}, {"title": 5}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                tracker.ingest_receipt(tracker.empty(), dict(receipt, **bad), "/fixture/receipt.json")

    def test_latest_uses_observation_time_and_preserves_regression(self):
        tracker.ingest_observation(self.data, dict(self.event, observed_at="2026-10-18T21:00:00+08:00", progress_percent=8))
        tracker.ingest_observation(self.data, self.event)
        self.assertEqual(tracker.summary(self.data)["books"][0]["latest_observation"]["progress_percent"], 8)
        self.assertEqual(len(self.data["observations"]), 2)

    def test_invalid_batch_does_not_commit_and_file_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tracker.json"
            with tracker.store(path):
                pass
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                with tracker.store(path) as data:
                    tracker.ingest_observation(data, self.event)
                    tracker.ingest_observation(data, dict(self.event, progress_percent=-1))
            self.assertEqual(before, path.read_bytes())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_inferred_taste_requires_tentative_observation_evidence(self):
        event_id = tracker.ingest_observation(self.data, self.event)
        entry = {"statement": "May enjoy fixture books", "basis": "inferred", "confidence": "confirmed",
                 "evidence": [event_id], "book_ids": ["library:fixture"], "updated_at": self.event["observed_at"]}
        with self.assertRaises(ValueError):
            tracker.ingest_preference(self.data, entry)
        entry["confidence"] = "tentative"
        tracker.ingest_preference(self.data, entry)
        self.assertEqual(len(self.data["preferences"]), 1)


if __name__ == "__main__":
    unittest.main()
