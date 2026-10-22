import unittest

from tokscope.web.theme import fonts
from tokscope.paths import PACKAGE


class FontsTest(unittest.TestCase):
    def test_every_face_has_both_subsets_on_disk(self):
        for family, weight in fonts.FACES:
            for subset in fonts.RANGES:
                self.assertIsNotNone(fonts.read(fonts._name(family, weight, subset)), (family, weight, subset))

    def test_only_shipped_font_names_can_be_read(self):
        for bad in ("../cli.py", "cli.py", "x.woff2", "BeVietnamPro-400-latin.woff2/../../cli.py"):
            self.assertIsNone(fonts.read(bad), bad)

    def test_the_report_embeds_them_and_the_dashboard_links_them(self):
        self.assertIn("data:font/woff2;base64,", fonts.face_css(True))
        self.assertNotIn("/fonts/", fonts.face_css(True))
        self.assertIn("url(/fonts/IBMPlexMono-500-vietnamese.woff2)", fonts.face_css(False))

    def test_the_wheel_ships_the_files(self):
        self.assertIn("assets/fonts/*.woff2", (PACKAGE.parent / "pyproject.toml").read_text())


if __name__ == "__main__":
    unittest.main()
