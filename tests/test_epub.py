"""EPUB output should remain valid XML for user supplied titles."""

import base64
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import webapp


class EpubTests(unittest.TestCase):
    def test_special_characters_in_title_are_escaped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "0001.gif").write_bytes(base64.b64decode(
                "R0lGODlhAQABAAD/ACwAAAAAAQABAAACAUwAOw=="
            ))
            output = root / "book.epub"
            webapp.make_epub(root, "A & B <C>", output, (0, 0))
            with zipfile.ZipFile(output) as archive:
                for name in ("OEBPS/content.opf", "OEBPS/nav.xhtml", "OEBPS/p1.xhtml"):
                    document = ET.fromstring(archive.read(name))
                    self.assertIn("A & B <C>", "".join(document.itertext()))

            webapp.normalize_epub_reading_order(output, "rtl")
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.infolist()[0].filename, "mimetype")
                self.assertEqual(archive.infolist()[0].compress_type, zipfile.ZIP_STORED)
                self.assertIn(b'page-progression-direction="rtl"', archive.read("OEBPS/content.opf"))
                page = next(name for name in archive.namelist() if name.startswith("OEBPS/page-0001."))
                self.assertTrue(archive.read(page))

    def test_navigation_rewrite_keeps_page_data_and_mimetype(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "book.epub"
            with zipfile.ZipFile(output, "w") as archive:
                archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
                archive.writestr("OEBPS/content.opf", '<package><manifest><item id="panel-contents" href="Text/panel-contents.xhtml"/></manifest><spine><itemref idref="panel-contents"/></spine></package>')
                archive.writestr("OEBPS/nav.xhtml", '<html><nav epub:type="toc"><ol><li><a href="Text/chapter/1.xhtml">Old label</a></li><li><a href="Text/panel-contents.xhtml">Contents</a></li></ol></nav><nav epub:type="page-list"><ol><li>Duplicate</li></ol></nav></html>')
                archive.writestr("OEBPS/Text/panel-contents.xhtml", "duplicate")
                archive.writestr("OEBPS/page.jpg", b"page data")
            webapp.update_epub_navigation(output)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.read("OEBPS/page.jpg"), b"page data")
                self.assertNotIn("OEBPS/Text/panel-contents.xhtml", archive.namelist())
                self.assertEqual(archive.infolist()[0].compress_type, zipfile.ZIP_STORED)
                self.assertNotIn(b"page-list", archive.read("OEBPS/nav.xhtml"))


if __name__ == "__main__":
    unittest.main()
