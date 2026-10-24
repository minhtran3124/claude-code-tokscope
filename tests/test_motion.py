import re
import unittest

from tokscope.web import dashboard
from tokscope.web.report.scripts import JS_CORE
from tokscope.web.theme.classic import CLASSIC_CSS, CLASSIC_DASH_CSS
from tokscope.web.theme.layout import LAYOUT_CSS, LAYOUT_DASH_CSS
from tokscope.web.report.styles import CSS

SHEETS = {"layout": LAYOUT_CSS, "layout-dash": LAYOUT_DASH_CSS, "ink": CSS, "ink-dash": dashboard.DASH_CSS,
          "classic": CLASSIC_CSS, "classic-dash": CLASSIC_DASH_CSS}
DURATION = re.compile(r"(?<![\w.#-])(\d*\.\d+|\d+)m?s(?![\w-])")


def strip(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"--t-(fast|state|layout):\d+ms", "", css)       # the token definitions
    return re.sub(r"animation-delay:[^;}]*", "", css)             # a stagger step per item is a delay, not a duration


class MotionTokensTest(unittest.TestCase):
    def test_the_three_tokens_and_the_exit_curve_are_in_the_layout_sheet(self):
        for t in ("--t-fast:120ms", "--t-state:200ms", "--t-layout:320ms", "--ease-exit:cubic-bezier(.55,.06,.68,.19)"):
            self.assertIn(t, LAYOUT_CSS)

    def test_every_duration_uses_a_token_except_the_commented_ones(self):
        allowed = ("animation:spin", "animation:slide", "animation:drift", "animation:ring 600ms", "animation:pulse 1600ms")
        for name, css in SHEETS.items():
            for line in strip(css).split("\n"):
                if DURATION.search(line) and not any(a in line for a in allowed):
                    self.fail(f"{name}: a literal duration outside the tokens: {line[:120]}")

    def test_only_the_spinners_the_hero_glow_and_the_working_dot_loop(self):
        for name, css in SHEETS.items():
            for line in strip(css).split("\n"):
                if "infinite" in line:
                    self.assertTrue(any(k in line for k in ("spin", "slide", "drift", "pulse")), f"{name}: {line[:100]}")

    def test_reduced_motion_has_a_fallback_per_rule_not_a_global_off_switch(self):
        for name, css in SHEETS.items():
            self.assertNotIn("animation:none!important", css, name)
            self.assertNotIn("transition:none!important", css, name)
        reduced = LAYOUT_CSS.split("@media (prefers-reduced-motion:reduce){", 1)[1]
        for name in ("reveal", "pop", "pop-in", "rise-in", "rise", "grow", "draw"):
            m = re.search(r"@keyframes %s\{([^\n]*)\}\n" % name, reduced)
            self.assertTrue(m, name)
            self.assertNotIn("transform", m.group(1), name)    # opacity stays, travel and scale go
        for name in ("ring", "chip-in", "chip-out", "toast-in"):
            m = re.search(r"@keyframes %s\{([^\n]*)\}\n" % name, LAYOUT_DASH_CSS.split("prefers-reduced-motion", 1)[1])
            self.assertTrue(m, name)
            self.assertNotIn("transform", m.group(1), name)

    def test_the_blur_in_the_flash_and_the_always_on_pulse_are_gone(self):
        for name, css in SHEETS.items():
            self.assertNotIn("keyframes focus", css, name)
            self.assertNotIn("animation:focus", css, name)
            self.assertNotIn("pulse 2s", css, name)
            self.assertNotIn(".flash", css, name)

    def test_session_rows_do_not_lift_on_hover(self):
        for name in ("ink", "classic"):
            self.assertIsNone(re.search(r"\.srow:hover\{[^}]*transform", SHEETS[name]), name)

    def test_a_swapped_region_never_replays_an_entrance(self):
        self.assertIn("html.settled [data-region] :is(.hero,.kpi,.empty,.bar i u){animation:none}", LAYOUT_CSS)
        self.assertIn("classList.add('settled')", dashboard.DASH_JS)       # before refresh() swaps a region
        self.assertIn("setTimeout(()=>document.documentElement.classList.add('settled')", JS_CORE)

    def test_live_values_change_at_once_with_a_chip_and_the_dot_rings_once(self):
        js = dashboard.DASH_JS
        self.assertNotIn("countFrom", js)
        self.assertIn("deltaChip(el,old[el.dataset.key])", js)
        self.assertIn("[data-count]:not([data-key])", JS_CORE)   # no count-up on live values
        self.assertIn(".dot.ring{animation:ring 600ms var(--ease) 1}", LAYOUT_DASH_CSS)
        self.assertIn(".fresh.stale .dot,body.offline h2>.dot{background:transparent", LAYOUT_DASH_CSS)   # offline: hollow
        for name in ("ink-dash", "classic-dash"):
            self.assertNotIn("stale .dot", SHEETS[name], name)             # a skin rule would win over the layout one

    def test_every_keyframes_set_that_moves_something_has_a_reduced_motion_answer(self):
        # an opacity-only twin in the layout sheet, or (spin, slide, drift) a rule that switches it off, tested below
        twins = set()
        for css in (LAYOUT_CSS, LAYOUT_DASH_CSS):
            twins |= set(re.findall(r"@keyframes ([\w-]+)\{[^\n]*\}\n", css.split("prefers-reduced-motion:reduce){", 1)[1]))
        moving = set()
        for css in SHEETS.values():
            for kf, body in re.findall(r"@keyframes ([\w-]+)\{(.*?)\}\n", css):
                if "transform" in body or "translate" in body:
                    moving.add(kf)
        self.assertEqual(moving - twins, {"spin", "slide", "drift"})
        for kf in twins:
            self.assertNotIn("transform", "".join(re.findall(r"@keyframes %s\{([^\n]*)\}\n" % kf, LAYOUT_CSS.split("prefers-reduced-motion:reduce){", 1)[1] + LAYOUT_DASH_CSS.split("prefers-reduced-motion:reduce){", 1)[1])))

    def test_the_hero_glow_and_the_spinners_stop_under_reduced_motion(self):
        self.assertRegex(CLASSIC_CSS, r"@media \(prefers-reduced-motion:reduce\)\{\s*\.hero::before\{animation:none\}")
        from tokscope.web.theme.layout import LAYOUT_TOKEN_DASH_CSS
        self.assertRegex(LAYOUT_TOKEN_DASH_CSS, r"@media \(prefers-reduced-motion:reduce\)\{\s*\.runbar i,\.spin,\.busy::before\{animation:none\}")


if __name__ == "__main__":
    unittest.main()
