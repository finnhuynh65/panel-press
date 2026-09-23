"""Checks for the bounded Vercel API boundary."""

import http.client
import json
import os
import tempfile
import threading
import types
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from api import index as hosted


class HostedAPITests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), hosted.handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        connection.request(method, path, body, headers or {})
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_scan_returns_preview_with_configured_cors_origin(self):
        preview = {'title': 'Book', 'chapters': [], 'preview': [], 'ready': False, 'suggestions': []}
        with patch.dict(os.environ, {'PANEL_WEB_ORIGIN': 'https://web.example'}), \
             patch.object(hosted.webapp, 'scan_preview', return_value=preview):
            status, headers, body = self.request('POST', '/api/v1/scans',
                json.dumps({'url': 'https://example.org/series'}),
                {'Content-Type': 'application/json', 'Origin': 'https://web.example'})
        self.assertEqual(status, 200)
        self.assertEqual(headers['Access-Control-Allow-Origin'], 'https://web.example')
        self.assertEqual(json.loads(body), preview)

    def test_hosted_conversion_caps_chapters(self):
        with patch.dict(os.environ, {'BLOB_READ_WRITE_TOKEN': 'test'}):
            with self.assertRaisesRegex(ValueError, '1 to 3 chapters'):
                hosted.convert_small({'url': 'https://example.org/series', 'chapters': [{}] * 4})

    def test_completed_file_is_published_to_blob(self):
        uploaded = []

        class BlobClient:
            def put(self, name, body, **options):
                uploaded.append((name, body, options))
                return types.SimpleNamespace(url='https://blob.example/book.cbz')

        def fake_convert(job_id, payload):
            path = hosted.webapp.EXPORTS / 'Book' / job_id / 'files' / 'book.cbz'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'book')
            hosted.webapp.JOBS[job_id] = {'status': 'done', 'message': 'Built.',
                                            'files': [hosted.webapp.download_url(path)]}

        fake_vercel = types.ModuleType('vercel')
        fake_blob = types.ModuleType('vercel.blob')
        fake_blob.BlobClient = BlobClient
        fake_vercel.blob = fake_blob
        payload = {'url': 'https://example.org/series', 'chapters': [{'url': 'https://example.org/chapter/1'}],
                   'format': 'cbz'}
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {'BLOB_READ_WRITE_TOKEN': 'test'}), \
             patch.dict('sys.modules', {'vercel': fake_vercel, 'vercel.blob': fake_blob}), \
             patch.object(hosted.webapp, 'EXPORTS', Path(directory)), \
             patch.object(hosted.webapp, 'convert_job', fake_convert):
            result = hosted.convert_small(payload)
        self.assertEqual(result['files'], ['https://blob.example/book.cbz'])
        self.assertEqual(uploaded[0][1], b'book')
        self.assertEqual(uploaded[0][2]['access'], 'public')


if __name__ == '__main__':
    unittest.main()
