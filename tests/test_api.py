"""Contract checks for the local HTTP boundary."""

import http.client
import io
import json
import shutil
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import webapp


class APITests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), webapp.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, body, content_type="application/json", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        connection.request("POST", path, body, {"Content-Type": content_type, **(headers or {})})
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def get(self, path):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        connection.request("GET", path)
        response = connection.getresponse()
        result = response.status, response.read()
        connection.close()
        return result

    def test_json_cannot_supply_server_file_paths(self):
        for field in ("files", "_upload_dir"):
            with self.subTest(field=field):
                status, result = self.request("/api/v1/conversions", json.dumps({field: "/tmp/private"}))
                self.assertEqual(status, 400)
                self.assertIn("Local files", result["error"])

    def test_cross_origin_request_is_rejected(self):
        status, result = self.request("/api/v1/conversions", "{}", headers={"Origin": "https://example.org"})
        self.assertEqual(status, 400)
        self.assertIn("Cross-origin", result["error"])

    def test_conversion_requires_a_url_and_selected_chapters(self):
        for payload in ({}, {"url": "https://example.org/series"}):
            with self.subTest(payload=payload):
                status, result = self.request("/api/v1/conversions", json.dumps(payload))
                self.assertEqual(status, 400)
                self.assertIn("error", result)

    def test_invalid_output_option_is_rejected_before_queuing(self):
        payload = {"url": "https://example.org/series", "chapters": [{"url": "https://example.org/1"}],
                   "format": "unexpected"}
        status, result = self.request("/api/v1/conversions", json.dumps(payload))
        self.assertEqual(status, 400)
        self.assertIn("Invalid format", result["error"])

    def test_multipart_upload_passes_only_server_created_paths(self):
        boundary = "test-boundary"
        body = b"".join(
            b"--" + boundary.encode() + b"\r\nContent-Disposition: form-data; name=\"files\"; filename=\"" + name + b"\"\r\nContent-Type: image/png\r\n\r\n" + content + b"\r\n"
            for name, content in ((b"one.png", b"first"), (b"two.png", b"second"))
        ) + b"--test-boundary\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\nA & B\r\n--test-boundary--\r\n"
        done = threading.Event()
        captured = {}

        def receive(job_id, payload, upload_dir):
            try:
                captured["title"] = payload["title"]
                captured["files"] = [Path(path).read_bytes() for path in payload["files"]]
                captured["inside"] = all(str(path).startswith(str(upload_dir)) for path in payload["files"])
            finally:
                shutil.rmtree(upload_dir)
                done.set()

        with patch.object(webapp, "convert_job", receive):
            status, result = self.request("/api/v1/conversions", body, "multipart/form-data; boundary=test-boundary")
            self.assertTrue(done.wait(2))
        self.assertEqual(status, 200)
        self.assertIn("job_id", result)
        self.assertEqual(captured["title"], "A & B")
        self.assertEqual(captured["files"], [b"first", b"second"])
        self.assertTrue(captured["inside"])

    def test_streamed_upload_preserves_large_binary_part(self):
        content = b"x" * 140_000 + b"\r\n--boundary-not-a-delimiter\r\n" + b"y" * 140_000
        body = (b"--boundary\r\nContent-Disposition: form-data; name=\"files\"; filename=\"large.png\"\r\n\r\n"
                + content + b"\r\n--boundary--\r\n")
        with tempfile.TemporaryDirectory() as directory:
            fields = {"title": ""}
            paths = webapp.read_multipart_upload(io.BytesIO(body), len(body),
                                                 "multipart/form-data; boundary=boundary", Path(directory), fields)
            self.assertEqual(len(paths), 1)
            self.assertEqual(Path(paths[0]).read_bytes(), content)

    def test_malformed_upload_is_rejected(self):
        body = b"--boundary\r\nContent-Disposition: form-data; name=\"title\"\r\n\r\nmissing close"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "Incomplete upload"):
                webapp.read_multipart_upload(io.BytesIO(body), len(body),
                                             "multipart/form-data; boundary=boundary", Path(directory), {"title": ""})

    def test_full_queue_keeps_running_jobs_retrievable(self):
        with patch.dict(webapp.JOBS, {"first": {"status": "working"}, "second": {"status": "working"}}, clear=True), \
             patch.object(webapp, "MAX_JOBS", 2), \
             patch.object(threading.Thread, "start"):
            self.assertIsNone(webapp.queue_job({}, None))
            self.assertEqual(set(webapp.JOBS), {"first", "second"})
            webapp.JOBS["first"]["status"] = "done"
            new_job = webapp.queue_job({}, None)
            self.assertIsNotNone(new_job)
            self.assertEqual(set(webapp.JOBS), {"second", new_job})

    def test_download_link_selects_the_requested_book(self):
        with tempfile.TemporaryDirectory() as directory:
            exports = Path(directory) / "exports"
            first = exports / "Book_A" / ("a" * 32) / "files" / "book.cbz"
            second = exports / "Book_A" / ("b" * 32) / "files" / "book.cbz"
            for path, content in ((first, b"A"), (second, b"B")):
                path.parent.mkdir(parents=True)
                path.write_bytes(content)
            with patch.object(webapp, "EXPORTS", exports):
                self.assertEqual(self.get(webapp.download_url(first)), (200, b"A"))
                self.assertEqual(self.get(webapp.download_url(second)), (200, b"B"))
                self.assertEqual(self.get("/downloads/Book_A/../files/book.cbz")[0], 404)


if __name__ == "__main__":
    unittest.main()
