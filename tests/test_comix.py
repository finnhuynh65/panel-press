import unittest

import comix_browser
import crawler


class ComixHelpersTests(unittest.TestCase):
    def test_shared_filename_rules(self):
        self.assertIs(comix_browser.safe_name, crawler.safe_name)
        self.assertEqual(comix_browser.safe_name("日本語/a"), "日本語_a")

    def test_module_import_does_not_require_playwright(self):
        self.assertEqual(comix_browser.chapter_number("https://comix.ws/title/example/chapter-1.5", 2), "1.5")


if __name__ == "__main__":
    unittest.main()
