import unittest

from tokscope.web.dashboard.common import PAGES
from tokscope.web.theme import icons


class IconsTest(unittest.TestCase):
    def test_every_page_in_the_menu_has_an_icon(self):
        for page in PAGES:
            self.assertIn(icons.PAGE_ICON[page], icons.PATHS, page)

    def test_an_icon_is_inline_svg_in_the_text_colour(self):
        svg = icons.icon("home")
        self.assertIn('stroke="currentColor"', svg)
        self.assertIn('aria-hidden="true"', svg)
        self.assertNotIn("http", svg)


if __name__ == "__main__":
    unittest.main()
