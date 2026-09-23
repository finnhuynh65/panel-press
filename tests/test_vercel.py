"""Tests for the hosted page-manifest API."""

import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
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
        result = response.status, json.loads(response.read() or b'{}')
        connection.close()
        return result

    def test_manifest_preserves_page_order_and_allows_part_sized_chapter_batches(self):
        chapter = {'url': 'https://example.org/chapter/1', 'title': 'Chapter 1', 'number': '1'}
        with patch.object(hosted.webapp, 'chapter_pages', return_value=['https://cdn.example/1.jpg', 'https://cdn.example/2.jpg']):
            result = hosted.conversion_pages({'url': 'https://example.org/series/Test', 'chapters': [chapter], 'delay': 0})
        self.assertEqual([page['page_index'] for page in result['pages']], [1, 2])
        self.assertEqual(result['pages'][0]['referer'], chapter['url'])
        with self.assertRaisesRegex(ValueError, 'one chapter per page manifest'):
            hosted.conversion_pages({'url': 'https://example.org/series', 'chapters': [chapter] * 4})
        with patch.object(hosted.webapp, 'chapter_pages', return_value=[f'https://cdn.example/{i}.jpg' for i in range(301)]):
            manifest = hosted.conversion_pages({'url': 'https://example.org/series', 'chapters': [chapter], 'delay': 0})
        self.assertEqual(len(manifest['pages']), 301)
        self.assertEqual(manifest['max_part_pages'], 300)

    def test_pages_endpoint_returns_manifest(self):
        preview = {'title': 'Book', 'chapters': [], 'preview': [], 'ready': False, 'suggestions': []}
        chapter = {'url': 'https://example.org/chapter/1', 'title': 'Chapter 1', 'number': '1'}
        with patch.object(hosted.webapp, 'chapter_pages', return_value=['https://cdn.example/1.jpg']):
            status, result = self.request('POST', '/api/v1/pages', json.dumps({
                'url': 'https://example.org/series/Book', 'chapters': [chapter], 'delay': 0,
            }), {'Content-Type': 'application/json'})
        self.assertEqual(status, 200)
        self.assertEqual(result['pages'][0]['url'], 'https://cdn.example/1.jpg')


if __name__ == '__main__':
    unittest.main()
