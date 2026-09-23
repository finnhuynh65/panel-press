import unittest
from unittest.mock import patch

import webapp
from crawler import Chapter


class SourceRoutingTests(unittest.TestCase):
    def test_weebcentral_adapter_only_matches_its_domain(self):
        self.assertTrue(webapp.is_weebcentral_url("https://weebcentral.com/series/1"))
        self.assertTrue(webapp.is_weebcentral_url("https://www.weebcentral.com/series/1"))
        self.assertFalse(webapp.is_weebcentral_url("https://evilweebcentral.com/series/1"))
        self.assertFalse(webapp.is_weebcentral_url("https://weebcentral.com.evil.test/series/1"))

    def test_preview_checks_only_three_spread_out_chapters(self):
        chapters = [Chapter(str(i), f"Chapter {i}", f"https://example.org/chapter/{i}", str(i)) for i in range(1, 8)]
        with patch.object(webapp, "scan", return_value=("Series", chapters)), \
             patch.object(webapp, "chapter_pages", return_value=["https://example.org/page.jpg"]) as pages:
            result = webapp.scan_preview("https://example.org/series", 0)
        self.assertTrue(result["ready"])
        self.assertEqual([row["index"] for row in result["preview"]], [0, 3, 6])
        self.assertEqual(pages.call_count, 3)

    def test_preview_blocks_build_when_a_sample_has_no_pages(self):
        chapters = [Chapter("1", "Chapter 1", "https://example.org/chapter/1", "1")]
        with patch.object(webapp, "scan", return_value=("Series", chapters)), \
             patch.object(webapp, "chapter_pages", return_value=[]):
            result = webapp.scan_preview("https://example.org/series", 0)
        self.assertFalse(result["ready"])
        self.assertEqual(result["preview"][0]["error"], "No page images found.")
        self.assertTrue(result["suggestions"])

    def test_direct_chapter_link_becomes_one_chapter(self):
        with patch.object(webapp, "scan", return_value=("A chapter", [])), \
             patch.object(webapp, "chapter_pages", return_value=["https://example.org/one.jpg"]):
            result = webapp.scan_preview("https://example.org/chapter/1", 0)
        self.assertTrue(result["ready"])
        self.assertEqual(len(result["chapters"]), 1)

    def test_invalid_locator_is_reported_before_fetch(self):
        with self.assertRaisesRegex(ValueError, "capture group"):
            webapp.scan_preview("https://example.org/series", 0, {"chapter_number_pattern": "Chapter [0-9]+"})


if __name__ == "__main__":
    unittest.main()
