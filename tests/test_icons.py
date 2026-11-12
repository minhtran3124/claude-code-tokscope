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

    def test_a_skill_gets_the_same_chip_tint_in_python_and_in_the_page_script(self):
        from tokscope.web.report.scripts import JS_SESSIONS
        from tokscope.web.report.widgets import hue, skill_chip
        # 32-bit FNV-1a over UTF-16 code units, mod 5; the script spells the same two constants
        self.assertEqual([hue(n) for n in ("factory", "code-review", "xia2", "Explore", "ünï😀")], [0, 2, 1, 3, 2])
        self.assertIn("0x811c9dc5", JS_SESSIONS)
        self.assertIn("0x01000193", JS_SESSIONS)
        self.assertEqual(hue("bad\ud800name"), 1)                          # a lone surrogate hashes as in the script (node: 1)
        self.assertEqual(skill_chip("a<b"), '<span class="skc t%d" title="a&lt;b">a&lt;b</span>' % hue("a<b"))


if __name__ == "__main__":
    unittest.main()
