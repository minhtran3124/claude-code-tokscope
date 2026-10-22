"""A skin is tokens plus a short look block (layout.py, classic.py). These checks keep it that way."""
import re
import unittest

from tokscope.web import dashboard, report
from tokscope.web.theme import layout
from tokscope.web.theme.classic import CLASSIC_CSS, CLASSIC_DASH_CSS


def rules(css):
    """(media prefix, selector, normalised body) of every flat rule; nested at-rules are read through."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out, i = [], 0

    def walk(text, prefix):
        j = 0
        while j < len(text):
            k = text.find("{", j)
            if k < 0:
                return
            sel, d, m = text[j:k].strip(), 1, k + 1
            while m < len(text) and d:
                d += (text[m] == "{") - (text[m] == "}")
                m += 1
            body = text[k + 1:m - 1]
            if sel.startswith(("@media", "@supports")):
                walk(body, prefix + sel + " ")
            else:
                out.append((prefix, " ".join(sel.split()), "".join(body.split())))
            j = m
    walk(css, "")
    return out


LAYOUT = layout.LAYOUT_CSS + layout.LAYOUT_DASH_CSS + layout.LAYOUT_TOKEN_CSS + layout.LAYOUT_TOKEN_DASH_CSS
SKINS = {"Ink": report.CSS + dashboard.DASH_CSS, "Classic": CLASSIC_CSS + CLASSIC_DASH_CSS}


def root_tokens(css):
    """Custom properties set in the light :root rule."""
    m = re.search(r"(?m)^:root\{(.*?)\}$", css, re.S)
    return set(re.findall(r"(--[\w-]+):", m.group(1)))


class SkinTokensTest(unittest.TestCase):
    def test_a_skin_sheet_does_not_repeat_a_layout_rule(self):
        held = set(rules(LAYOUT))
        for name, css in SKINS.items():
            again = [r[:2] for r in rules(css) if r in held]
            self.assertEqual(again, [], f"{name} repeats rules layout.py already holds word for word")

    def test_a_skin_sheet_stays_a_short_look_block(self):
        for name, css in SKINS.items():
            self.assertLess(len(rules(css)), 140, f"{name} grew back: move a rule that differs only in value into layout.py and read a token")

    def test_every_look_token_is_defined_in_both_skins(self):
        ink, classic = root_tokens(report.CSS), root_tokens(CLASSIC_CSS)
        used = set(re.findall(r"var\((--[\w-]+)\)", layout.LAYOUT_TOKEN_CSS + layout.LAYOUT_TOKEN_DASH_CSS))
        # tokens the layout sheet defines itself (motion, per-element values set inline or by a rule)
        own = {"--t-fast", "--t-state", "--t-layout", "--ease-exit", "--i", "--d", "--depth", "--n", "--mx", "--my", "--scols", "--tok-accent"}
        for tok in sorted(used - own):
            self.assertIn(tok, ink, f"{tok} is missing from the Ink :root")
            self.assertIn(tok, classic, f"{tok} is missing from the Classic :root")
        self.assertEqual({t for t in ink if t.startswith(("--r-", "--lab-", "--pad-"))}, {t for t in classic if t.startswith(("--r-", "--lab-", "--pad-"))})

    def test_the_dark_theme_leaves_the_shape_tokens_alone(self):
        # the look tokens sit in the light :root and hold in dark too: the dark rules must not need to repeat them
        for css in (report.CSS, CLASSIC_CSS):
            dark = re.search(r":root\[data-theme=dark\]\{(.*?)\}", css, re.S).group(1)
            for tok in re.findall(r"(--[\w-]+):", dark):
                self.assertNotRegex(tok, r"^--(r-|lab-|pad-|ctl-|num-|cell-)", f"{tok} belongs in the light :root only")


if __name__ == "__main__":
    unittest.main()
