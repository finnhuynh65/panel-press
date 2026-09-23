"""Exercise the dependency-free conversion path with real local files."""

import base64
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import webapp


class ConversionTests(unittest.TestCase):
    def test_web_download_detects_extensionless_image(self):
        image = b'GIF89a' + b'payload'
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(webapp, 'fetch', return_value=image):
            path = webapp.download_to_path('https://example.org/image?id=1',
                                           Path(directory) / '0001.img', 0)
            self.assertEqual(path.suffix, '.gif')
            self.assertEqual(path.read_bytes(), image)

    def test_repeated_title_preserves_both_exports(self):
        image = base64.b64decode("R0lGODlhAQABAAD/ACwAAAAAAQABAAACAUwAOw==")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            exports = output / "exports"
            results = []
            with patch.object(webapp, "OUTPUT", output), \
                 patch.object(webapp, "EXPORTS", exports), \
                 patch.object(webapp, "find_kcc", return_value=None), \
                 patch.dict(webapp.JOBS, {}, clear=True):
                for index in range(2):
                    upload_dir = root / f"upload-{index}"
                    upload_dir.mkdir()
                    source = upload_dir / "cover.gif"
                    source.write_bytes(image)
                    job_id = f"{index + 1:032x}"
                    webapp.convert_job(job_id, {
                        "files": [str(source)], "relative_paths": ["cover.gif"],
                        "title": "Same title", "profile": "original",
                    }, upload_dir)
                    result = webapp.JOBS[job_id]
                    self.assertEqual(result["status"], "done", result["message"])
                    url = result["files"][0]
                    path = webapp.downloadable_path(url)
                    self.assertIsNotNone(path)
                    with zipfile.ZipFile(path) as archive:
                        self.assertEqual(archive.read("images/0001.gif"), image)
                    results.append(path)
                self.assertNotEqual(results[0], results[1])
                self.assertTrue(all(path.exists() for path in results))

    def test_explicit_epub_fallback_is_honored_for_kindle_profile(self):
        image = base64.b64decode("R0lGODlhAQABAAD/ACwAAAAAAQABAAACAUwAOw==")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upload_dir = root / "upload"
            upload_dir.mkdir()
            source = upload_dir / "cover.gif"
            source.write_bytes(image)
            job_id = "c" * 32
            with patch.object(webapp, "EXPORTS", root / "exports"), \
                 patch.object(webapp, "find_kcc", return_value=None), \
                 patch.dict(webapp.JOBS, {}, clear=True):
                webapp.convert_job(job_id, {
                    "files": [str(source)], "relative_paths": ["cover.gif"],
                    "title": "Kindle book", "profile": "kindle-paperwhite", "format": "epub",
                }, upload_dir)
                result = webapp.JOBS[job_id]
                self.assertEqual(result["status"], "done", result["message"])
                self.assertTrue(result["files"][0].endswith(".epub"))

    def test_mobi_request_reports_missing_kcc(self):
        options = webapp.ConversionOptions.from_payload({"format": "mobi"})
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "pages"
            source.mkdir()
            (source / "0001.gif").write_bytes(b"image")
            with self.assertRaisesRegex(RuntimeError, "MOBI output requires KCC"):
                webapp.build_fallback(source, Path(directory) / "output", "Book", "ltr", options)

    def test_url_source_downloads_selected_chapter_pages(self):
        payload = {"url": "https://example.org/series/My-Book",
                   "chapters": [{"number": "1", "title": "Chapter 1", "url": "https://example.org/chapter/1"}]}
        options = webapp.ConversionOptions.from_payload(payload)

        def save_page(url, target, delay):
            target.write_bytes(url.encode())

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(webapp, "chapter_pages", return_value=["https://example.org/1.jpg", "https://example.org/2.jpg"]), \
             patch.object(webapp, "download_to_path", side_effect=save_page):
            prepared = webapp.prepare_source("job", payload, Path(directory), options)
            self.assertEqual(prepared.title, "My-Book")
            self.assertEqual(prepared.page_count, 2)
            self.assertFalse(prepared.uploaded)
            self.assertEqual(len(webapp.source_images(prepared.path)), 2)


if __name__ == "__main__":
    unittest.main()
