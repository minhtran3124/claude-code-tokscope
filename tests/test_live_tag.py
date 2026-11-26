import re
import unittest

from tokscope.web.theme.layout import LAYOUT_DASH_CSS, LAYOUT_TOKEN_CSS


class LiveTagAlignmentTests(unittest.TestCase):
    def test_the_live_tag_centres_itself_in_the_title_cell(self):
        # the title cell aligns its items on the text baseline, which sits above the row's centre line
        # (where the skill chip and the numbers are), so the tag has to centre itself (#270)
        rule = re.search(r"\.srow \.live\{([^}]*)\}", LAYOUT_DASH_CSS).group(1)
        self.assertIn("align-self:center", rule)

    def test_a_project_line_drops_the_tag_to_the_row_centre_on_wide_screens_only(self):
        m = re.search(r"@media \(min-width:640px\)\{([^}]*\.live\{[^}]*\})\}", LAYOUT_TOKEN_CSS)
        self.assertIn(".t:has(>.pj)>.live{transform:translateY(8.4px)}", m.group(1))


if __name__ == "__main__":
    unittest.main()
