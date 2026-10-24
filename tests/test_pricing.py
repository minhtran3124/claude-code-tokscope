import contextlib
import io
import re
import unittest
from unittest import mock

from tests.test_ingest import Fixture, assistant, human
from tokscope import cli
from tokscope.core.ingest import connect
from tokscope.core.pricing import RATES, fingerprint, cost_usd, normalize, unpriced, unpriced_text

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


M = 1_000_000


class ModifierTest(unittest.TestCase):
    def test_fast_mode_opus_5_5(self):  # $8 in, $40 out, cache read 2x of $0.20
        self.assertAlmostEqual(cost_usd("claude-opus-5-5", M, M, M, 0, 0, speed="fast", ov={}), 8 + 40 + 0.4)

    def test_fast_mode_opus_5_and_4_8(self):  # $10 / $50
        for m in ("claude-opus-5", "claude-opus-4-8"):
            self.assertAlmostEqual(cost_usd(m, M, M, 0, 0, 0, speed="fast", ov={}), 60)

    def test_fast_mode_scales_cache_writes(self):
        self.assertAlmostEqual(cost_usd("claude-opus-5", 0, 0, 0, M, M, speed="fast", ov={}), 10 * 1.25 + 10 * 2)

    def test_standard_speed_and_global_geo_are_list_price(self):
        self.assertAlmostEqual(cost_usd("claude-opus-5-5", M, 0, 0, 0, 0, speed="standard", geo="global", ov={}), 4)

    def test_us_geo_is_1_1x_on_4_6_and_later(self):
        self.assertAlmostEqual(cost_usd("claude-opus-4-6", M, M, M, 0, 0, geo="us", ov={}), 30.5 * 1.1)
        self.assertAlmostEqual(cost_usd("claude-sonnet-5", M, 0, 0, 0, 0, geo="us", ov={}), 2.2)

    def test_us_geo_not_charged_on_older_models(self):
        self.assertAlmostEqual(cost_usd("claude-opus-4-5", M, 0, 0, 0, 0, geo="us", ov={}), 5)

    def test_fast_and_us_stack(self):
        self.assertAlmostEqual(cost_usd("claude-opus-5-5", M, 0, 0, 0, 0, speed="fast", geo="us", ov={}), 4 * 2 * 1.1)

    def test_web_search_is_ten_dollars_per_thousand(self):
        self.assertAlmostEqual(cost_usd("claude-opus-5-5", 0, 0, 0, 0, 0, searches=7, ov={}), 0.07)

    def test_override_replaces_rates_and_adds_models(self):
        ov = {"claude-opus-5-5": {"input": 1, "fast": 3}, "claude-new-1": {"input": 1, "output": 2, "cache_read": 0.1},
              "web_search_per_1000": 20}
        self.assertAlmostEqual(cost_usd("claude-opus-5-5", M, 0, 0, 0, 0, speed="fast", ov=ov), 3)
        self.assertAlmostEqual(cost_usd("claude-new-1", M, M, 0, 0, 0, ov=ov), 3)
        self.assertAlmostEqual(cost_usd("claude-opus-5-5", 0, 0, 0, 0, 0, searches=5, ov=ov), 0.1)
        self.assertIsNone(cost_usd("claude-new-2", 1, 1, 1, 0, 0, ov={"claude-new-2": {"input": 1}}))


def usage_request(req, **extra):
    r = assistant(req)
    r["message"]["usage"].update(extra)
    return r


class StoredCostTest(Fixture):
    def setUp(self):
        super().setUp()
        home = mock.patch.dict("os.environ", {"TOKSCOPE_HOME": str(self.tmp / "th")})
        home.start()
        self.addCleanup(home.stop)
        (self.tmp / "th").mkdir()
        self.write_main([human("hi"),
                         usage_request("fast", speed="fast"),
                         usage_request("us", inference_geo="us"),
                         usage_request("web", server_tool_use={"web_search_requests": 3, "web_fetch_requests": 2}),
                         assistant("plain")])
        self.run_ingest()

    def costs(self):
        conn = connect(self.db)
        return {k: c for k, c in conn.execute("SELECT request_key, cost_usd FROM requests")}

    def test_modifiers_are_stored_and_priced(self):
        conn = connect(self.db)
        rows = dict((r[0], r[1:]) for r in conn.execute(
            "SELECT request_key, speed, inference_geo, web_search_requests, web_fetch_requests FROM requests"))
        self.assertEqual(rows["fast"], ("fast", None, 0, 0))
        self.assertEqual(rows["us"], (None, "us", 0, 0))
        self.assertEqual(rows["web"], (None, None, 3, 2))
        c = self.costs()
        self.assertAlmostEqual(c["fast"], c["plain"] * 2)
        self.assertAlmostEqual(c["us"], c["plain"] * 1.1)
        self.assertAlmostEqual(c["web"], c["plain"] + 0.03)

    def test_editing_pricing_json_changes_totals_without_reingest(self):
        before = fingerprint()
        (self.tmp / "th" / "pricing.json").write_text('{"claude-opus-5-5": {"input": 40, "output": 200, "cache_read": 2}}')
        self.assertNotEqual(before, fingerprint())
        c = self.costs()
        self.assertAlmostEqual(c["plain"], (40 + 10 * 200 + 100 * 2) / M)
        self.assertAlmostEqual(c["fast"], c["plain"] * 2)
        (self.tmp / "th" / "pricing.json").unlink()
        self.assertAlmostEqual(self.costs()["plain"], (4 + 10 * 20 + 100 * .2) / M)


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
        args = cli.argparse.Namespace(by="model", since=None, until=None, project=None, limit=10)
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
