"""Offline behavioral tests. All works and network responses here are synthetic."""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

import annas_books as app


def epub(encryption=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="content.opf"/></rootfiles></container>')
        archive.writestr("content.opf", '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">original-test</dc:identifier><dc:title>Original Test</dc:title><dc:language>en</dc:language></metadata><manifest><item id="text" href="text.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="text"/></spine></package>')
        archive.writestr("text.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Original Test</title></head><body><p>Original fixture created for this test.</p></body></html>')
        if encryption:
            archive.writestr("META-INF/encryption.xml", '<encryption xmlns:e="http://www.w3.org/2001/04/xmlenc#"><e:EncryptedData><e:EncryptionMethod Algorithm="' + encryption + '"/></e:EncryptedData></encryption>')
    return stream.getvalue()


def book(payload):
    digest = hashlib.md5(payload).hexdigest()
    return {"request": {"title": "Original Test", "language": "en", "format": "epub"},
            "match": {"title": "Original Test", "author": "Fixture Author", "language": "en",
                      "format": "epub", "md5": digest, "url": "https://annas-archive.gd/md5/" + digest},
            "review": {"confirmed": True, "note": "Original synthetic fixture; reviewed for this test."},
            "access": {"basis": "permission", "confirmed_by": "user", "evidence": "Original work generated for this offline test."}}


class Response(io.BytesIO):
    def __init__(self, body=b"", status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}


class BookTests(unittest.TestCase):
    def setUp(self):
        self.payload = epub()
        self.book = book(self.payload)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dest = Path(self.temp.name)

    def plan(self, selected=None):
        return {"version": 1, "books": [selected or self.book]}

    def test_plan_and_isbn_equivalence(self):
        self.book["request"]["isbn"] = "0-306-40615-2"
        self.book["match"]["isbn"] = "9780306406157"
        self.assertEqual(len(app.validate_plan(self.plan())), 1)
        with self.assertRaises(app.BookError):
            app.isbn13("9780306406158")

    def test_edition_constraints_reject_wrong_or_unknown(self):
        for field in ("language", "edition", "year", "translator", "volume", "format"):
            with self.subTest(field=field):
                candidate = copy.deepcopy(self.book)
                candidate["request"][field] = "specified"
                candidate["match"][field] = "different"
                with self.assertRaises(app.BookError):
                    app.validate_plan(self.plan(candidate))
                candidate["match"].pop(field)
                with self.assertRaises(app.BookError):
                    app.validate_plan(self.plan(candidate))

    def test_identity_and_access_gates(self):
        for change in (lambda x: x.pop("access"),
                       lambda x: x["access"].update(basis="membership"),
                       lambda x: x["access"].update(evidence=""),
                       lambda x: x["access"].update(basis="public-domain"),
                       lambda x: x["review"].update(confirmed=False)):
            candidate = copy.deepcopy(self.book)
            change(candidate)
            with self.assertRaises(app.BookError):
                app.validate_plan(self.plan(candidate))

    def test_invalid_plan_has_no_key_or_network_side_effect(self):
        self.book["access"]["basis"] = "available-online"
        with patch.object(app, "load_key") as key, patch.object(app, "request_once") as network:
            with self.assertRaises(app.BookError):
                app.fetch([self.book], self.dest, app.DOMAINS[1])
            key.assert_not_called()
            network.assert_not_called()

    def test_invalid_source_or_unsupported_format(self):
        for url in ("https://annas-archive.gd.evil.test/md5/" + self.book["match"]["md5"],
                    self.book["match"]["url"] + "?key=do-not-store"):
            candidate = copy.deepcopy(self.book)
            candidate["match"]["url"] = url
            with self.assertRaises(app.BookError):
                app.validate_plan(self.plan(candidate))
        self.book["match"]["format"] = "azw"
        with self.assertRaises(app.BookError):
            app.validate_plan(self.plan())

    def test_duplicate_md5_rejected(self):
        with self.assertRaises(app.BookError):
            app.validate_plan({"version": 1, "books": [self.book, self.book]})

    def test_key_environment_removed_and_never_passed_as_argument(self):
        with patch.dict(os.environ, {app.KEY_ENV: "offline-secret"}):
            with patch.object(app.subprocess, "run") as run:
                self.assertEqual(app.load_key(), "offline-secret")
                self.assertNotIn(app.KEY_ENV, os.environ)
                run.assert_not_called()
        with patch.dict(os.environ, {}, clear=True), patch.object(app.sys, "platform", "darwin"):
            with patch.object(app.subprocess, "run", return_value=Mock(returncode=0, stdout=b"offline-secret\n")) as run:
                self.assertEqual(app.load_key(), "offline-secret")
                self.assertNotIn("offline-secret", str(run.call_args))

    def test_missing_key_gives_no_raw_subprocess_output(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(app.sys, "platform", "darwin"):
            with patch.object(app.subprocess, "run", return_value=Mock(returncode=1, stdout=b"secret", stderr=b"sensitive-stderr-marker")):
                with self.assertRaises(app.BookError) as caught:
                    app.load_key()
                self.assertNotIn("sensitive-stderr-marker", str(caught.exception))

    def test_api_success_and_encoded_key(self):
        data = json.dumps({"download_url": "https://cdn.example/book?token=signed", "account_fast_download_info": {}}).encode()
        with patch.object(app, "request_once", return_value=Response(data)) as request, patch.object(app, "public_https"):
            self.assertTrue(app.get_fast_url(app.DOMAINS[1], self.book["match"]["md5"], "a+b&c").startswith("https://cdn.example"))
            self.assertIn("key=a%2Bb%26c", request.call_args.args[0])
            self.assertEqual(request.call_count, 1)

    def test_api_failures_never_retry_or_expose_body(self):
        for status, raw in ((302, b"offline-secret"), (401, b"offline-secret"),
                            (429, b"offline-secret"), (204, b""),
                            (200, b'{"error":"offline-secret","download_url":null}'),
                            (200, b"<html>offline-secret</html>")):
            with self.subTest(status=status, raw=raw), patch.object(app, "request_once", return_value=Response(raw, status)) as request:
                with self.assertRaises(app.BookError) as caught:
                    app.get_fast_url(app.DOMAINS[1], self.book["match"]["md5"], "offline-secret")
                self.assertNotIn("offline-secret", str(caught.exception))
                self.assertEqual(request.call_count, 1)

    def test_refuse_key_echo_in_download_url(self):
        raw = b'{"download_url":"https://cdn.example/?token=offline%2Dsecret"}'
        with patch.object(app, "request_once", return_value=Response(raw)):
            with self.assertRaises(app.BookError):
                app.get_fast_url(app.DOMAINS[1], self.book["match"]["md5"], "offline-secret")

    def test_private_or_non_https_urls_rejected(self):
        addresses = [(2, 1, 6, "", ("127.0.0.1", 443))]
        for url in ("http://cdn.example/a", "https://user:pw@cdn.example/a", "https://cdn.example:80/a", "https://cdn.example/a"):
            with self.subTest(url=url), patch.object(app.socket, "getaddrinfo", return_value=addresses):
                with self.assertRaises(app.BookError):
                    app.public_https(url)

    def test_fake_ip_range_only_with_opt_in(self):
        fake = [(2, 1, 6, "", ("198.18.5.104", 443))]
        loopback = [(2, 1, 6, "", ("127.0.0.1", 443))]
        with patch.object(app.socket, "getaddrinfo", return_value=fake):
            with self.assertRaises(app.BookError):
                app.public_https("https://cdn.example/a")
            with patch.object(app, "ALLOW_FAKE_IP", True):
                app.public_https("https://cdn.example/a")
        with patch.object(app, "ALLOW_FAKE_IP", True), patch.object(app.socket, "getaddrinfo", return_value=loopback):
            with self.assertRaises(app.BookError):
                app.public_https("https://cdn.example/a")

    def test_redirect_validation(self):
        with patch.object(app, "public_https") as guard:
            def validate(url):
                if url.startswith("http:"):
                    raise app.BookError("Unsafe URL")
            guard.side_effect = validate
            with patch.object(app, "request_once", return_value=Response(status=302, headers={"Location": "http://localhost/private"})) as request:
                with self.assertRaises(app.BookError):
                    app.download("https://cdn.example/start", self.dest / "partial", "offline-secret")
                self.assertEqual(request.call_count, 1)

    def test_html_wrong_hash_and_partial_download_rejected(self):
        path = self.dest / "book"
        for payload in (b"<html>challenge</html>", b"truncated"):
            path.write_bytes(payload)
            with self.assertRaises(app.BookError):
                app.validate_file(path, self.book["match"])
        fake_match = copy.deepcopy(self.book["match"])
        fake_match["md5"] = hashlib.md5(b"<html>challenge</html>").hexdigest()
        path.write_bytes(b"<html>challenge</html>")
        with self.assertRaises(app.BookError):
            app.validate_file(path, fake_match)

    def test_epub_drm_and_font_obfuscation(self):
        path = self.dest / "book.epub"
        for algorithm, allowed in (("urn:example:drm", False), ("http://www.idpf.org/2008/embedding", True)):
            payload = epub(algorithm)
            path.write_bytes(payload)
            match = book(payload)["match"]
            if allowed:
                app.validate_file(path, match)
            else:
                with self.assertRaises(app.BookError):
                    app.validate_file(path, match)

    def test_full_flow_cache_receipt_and_handoff(self):
        def network(url, timeout=30):
            if "/dyn/api/" in url:
                return Response(b'{"download_url":"https://cdn.example/book?signature=ephemeral"}')
            return Response(self.payload, headers={"Content-Length": str(len(self.payload))})
        with patch.dict(os.environ, {app.KEY_ENV: "offline-secret"}), patch.object(app, "request_once", side_effect=network) as request, patch.object(app, "public_https"), patch.object(app, "handoff") as handoff, contextlib.redirect_stdout(io.StringIO()) as output:
            results = app.fetch([self.book], self.dest, app.DOMAINS[1], True)
            app.fetch([self.book], self.dest, app.DOMAINS[1], True)
            self.assertEqual(request.call_count, 2)
            self.assertEqual(handoff.call_count, 1)
            self.assertNotIn(app.KEY_ENV, os.environ)
        path = Path(results[0]["path"])
        self.assertEqual(path.read_bytes(), self.payload)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        receipt = next(self.dest.glob(".receipt-*.json"))
        self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
        text = receipt.read_text() + output.getvalue()
        for private in ("offline-secret", "ephemeral", "cdn.example", "account_fast_download_info"):
            self.assertNotIn(private, text)
        self.assertEqual(json.loads(receipt.read_text())["books_handoff"], "submitted")

    def test_bad_download_cleans_partial_and_never_imports(self):
        with patch.object(app, "load_key", return_value="offline-secret"), patch.object(app, "get_fast_url", return_value="https://cdn.example/file"), patch.object(app, "public_https"), patch.object(app, "request_once", return_value=Response(b"wrong")), patch.object(app, "handoff") as handoff:
            with self.assertRaises(app.BookError):
                app.fetch([self.book], self.dest, app.DOMAINS[1], True)
            handoff.assert_not_called()
        self.assertEqual(list(self.dest.iterdir()), [])

    def test_size_limit_and_truncated_stream(self):
        for response in (Response(b"123", headers={"Content-Length": "10"}), Response(b"123456")):
            with patch.object(app, "public_https"), patch.object(app, "request_once", return_value=response):
                with self.assertRaises(app.BookError):
                    app.download("https://cdn.example/f", self.dest / "partial", "offline-secret", max_bytes=5)

    def test_existing_file_not_overwritten(self):
        path = self.dest / ("Original Test--" + self.book["match"]["md5"] + ".epub")
        path.write_bytes(b"keep this")
        with patch.object(app, "load_key") as key:
            with self.assertRaises(app.BookError):
                app.fetch([self.book], self.dest, app.DOMAINS[1])
            key.assert_not_called()
        self.assertEqual(path.read_bytes(), b"keep this")

    def test_handoff_failure_keeps_download_and_receipt(self):
        def write_fixture(url, path, secret, limit):
            path.write_bytes(self.payload)
        with patch.object(app, "load_key", return_value="offline-secret"), patch.object(app, "get_fast_url", return_value="https://cdn.example/f"), patch.object(app, "download", side_effect=write_fixture), patch.object(app, "handoff", side_effect=app.BookError("App unavailable")):
            with self.assertRaises(app.BookError):
                app.fetch([self.book], self.dest, app.DOMAINS[1], True)
        self.assertEqual(len(list(self.dest.glob("*.epub"))), 1)
        receipt = json.loads(next(self.dest.glob(".receipt-*.json")).read_text())
        self.assertNotIn("books_handoff", receipt)

    def test_handoff_uses_bundle_id_and_separate_file_argument(self):
        with patch.object(app.sys, "platform", "darwin"), patch.object(app.subprocess, "run", return_value=Mock(returncode=0)) as run:
            app.handoff(self.dest / "a book.epub")
            self.assertEqual(run.call_args.args[0], ["/usr/bin/open", "-b", "com.apple.iBooksX", str(self.dest / "a book.epub")])

    def test_local_download_default_and_explicit_false_do_not_launch_books(self):
        path = self.dest / ("Original Test--" + self.book["match"]["md5"] + ".epub")
        path.write_bytes(self.payload)
        with patch.object(app, "load_key") as key, patch.object(app, "handoff") as handoff, contextlib.redirect_stdout(io.StringIO()):
            first = app.fetch([self.book], self.dest, app.DOMAINS[1])
            second = app.fetch([self.book], self.dest, app.DOMAINS[1], import_books=False)
            self.assertEqual(first[0]["status"], "downloaded")
            self.assertEqual(second[0]["status"], "downloaded")
            handoff.assert_not_called()
            key.assert_not_called()
        self.assertEqual(path.read_bytes(), self.payload)


if __name__ == "__main__":
    unittest.main()
