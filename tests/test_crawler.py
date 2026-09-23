"""Resume behavior for partially downloaded chapters."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import crawler


class ResumeTests(unittest.TestCase):
    def test_fetch_does_not_retry_permanent_http_error(self):
        error = HTTPError('https://example.org/missing', 404, 'Not found', {}, None)
        with patch.object(crawler, 'urlopen', side_effect=error) as request, \
             patch.object(crawler.time, 'sleep') as sleep:
            with self.assertRaises(RuntimeError):
                crawler.fetch('https://example.org/missing', retries=3)
            self.assertEqual(request.call_count, 1)
            sleep.assert_not_called()

    def test_fetch_retries_transient_error_without_final_sleep(self):
        error = HTTPError('https://example.org/busy', 503, 'Unavailable', {}, None)
        with patch.object(crawler, 'urlopen', side_effect=error) as request, \
             patch.object(crawler.time, 'sleep') as sleep:
            with self.assertRaises(RuntimeError):
                crawler.fetch('https://example.org/busy', retries=3)
            self.assertEqual(request.call_count, 3)
            self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])

    def test_extensionless_image_url_uses_detected_format(self):
        image = b'GIF89a' + b'payload'
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(crawler, 'fetch', return_value=image):
            target = Path(directory) / '0001.img'
            crawler.download_page('https://example.org/image?id=1', target, 0, 1)
            self.assertEqual(target.with_suffix('.gif').read_bytes(), image)
            self.assertFalse(target.exists())

    def test_zero_byte_page_requires_a_fresh_download(self):
        chapter = crawler.Chapter("1", "Chapter 1", "https://example.org/chapters/1", "1")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            folder = output / "Series" / "chapters" / "001-chapter-1"
            crawler.write_json(folder / "chapter.json", {
                "url": chapter.url, "page_count": 2, "order": 1,
            })
            (folder / "0001.jpg").write_bytes(b"complete")
            (folder / "0002.jpg").touch()
            pages = ["https://example.org/pages/1.jpg", "https://example.org/pages/2.jpg"]

            def save_page(url, target, delay, retries):
                if not target.exists() or target.stat().st_size == 0:
                    target.write_bytes(url.encode())

            with patch.object(crawler, "discover_chapters", return_value=("Series", [chapter])), \
                 patch.object(crawler, "discover_pages", return_value=pages) as discover, \
                 patch.object(crawler, "download_page", side_effect=save_page):
                crawler.crawl(chapter.url, output, 0, 1, 1, False, 1)

            discover.assert_called_once()
            self.assertEqual((folder / "0001.jpg").read_bytes(), b"complete")
            self.assertEqual((folder / "0002.jpg").read_bytes(), pages[1].encode())


if __name__ == "__main__":
    unittest.main()
