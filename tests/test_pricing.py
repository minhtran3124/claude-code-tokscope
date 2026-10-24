import contextlib
import io
import re
import unittest
from unittest import mock

from tests.test_ingest import Fixture, assistant, human
from tokscope import cli
from tokscope.core.ingest import connect
from tokscope.core.pricing import RATES, cost_usd, normalize, unpriced, unpriced_text

# model -> (input, output, cache read) from https://docs.claude.com/en/docs/about-claude/pricing
LIST = {
    "claude-sonnet-4-5-20250929": (3, 15, .30), "claude-sonnet-4-20250514": (3, 15, .30),
    "claude-opus-4-5-20251101": (5, 25, .50), "claude-opus-4-1-20250805": (15, 75, 1.5),
    "claude-opus-4-20250514": (15, 75, 1.5), "claude-haiku-3-5": (.8, 4, .08), "claude-3-5-haiku-20241022": (.8, 4, .08),
    "claude-mythos-5": (10, 50, 1.0), "claude-mythos-5-1": (10, 50, .25),
}
NOTE = "unpriced: 2 requests (claude-foo-9)"


class PricingTest(unittest.TestCase):
    def test_documented_models_are_priced(self):
        for model, (i, o, c) in LIST.items():
            with self.subTest(model):
                self.assertAlmostEqual(cost_usd(model, 1_000_000, 1_000_000, 1_000_000, 0, 0), i + o + c)

    def test_unknown_minor_version_is_not_a_snapshot(self):
        self.assertEqual(normalize("claude-opus-4-9"), "claude-opus-4-9")
        self.assertIsNone(cost_usd("claude-opus-4-9", 1, 1, 1, 0, 0))
        self.assertIsNone(cost_usd("claude-foo-9", 1, 1, 1, 0, 0))

    def test_every_rate_is_a_model_id(self):
        self.assertTrue(all(re.fullmatch(r"claude-[a-z0-9-]+", m) for m in RATES))


class UnpricedTest(Fixture):
    def setUp(self):
        super().setUp()
        self.write_main([human("hi"), assistant("r1"), assistant("r2", model="claude-foo-9"), assistant("r3", model="claude-foo-9")])
        self.run_ingest()
        self.conn = connect(self.db)

    def test_helper_counts_requests_per_model(self):
        rows = unpriced(self.conn)
        self.assertEqual(rows, [("claude-foo-9", 2)])
        self.assertIn("2 requests (claude-foo-9)", unpriced_text(rows))

    def test_no_notice_when_all_priced(self):
        self.assertEqual(unpriced(self.conn, "WHERE r.model = ?", ("claude-opus-5-5",)), [])
        self.assertEqual(unpriced_text([]), "")

    def test_cli_names_them(self):
        args = cli.argparse.Namespace(by="model", since=None, project=None, limit=10)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(cli, "DB", self.db):
            cli.summary(args)
        self.assertIn(NOTE, out.getvalue())
        self.assertIn(NOTE, cli.session_text(self.conn, "s1"))

    def test_report_and_dashboard_name_them(self):
        from tokscope.web.dashboard.common import Filters
        from tokscope.web.dashboard.pages.overview import _kpis
        from tokscope.web.report import write_report
        out = self.tmp / "r.html"
        write_report(self.db, out, tasks_dir=self.tmp)
        self.assertIn(NOTE, out.read_text())
        self.assertIn(NOTE, _kpis(self.conn, Filters({"range": ["all"]})))


if __name__ == "__main__":
    unittest.main()
