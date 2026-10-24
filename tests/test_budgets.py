"""budgets.json: loading, the states, `tokscope check --once` exit codes, statusline, the SessionEnd line and the Overview bars."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tokscope import cli
from tokscope.core import budgets, summary
from tokscope.core.ingest import connect
from tokscope.web.dashboard.common import Filters
from tokscope.web.dashboard.pages import overview


def seed(conn, cost, session="s1", agent=None, skill=None, key="a", tokens=1000):
    conn.execute("INSERT OR IGNORE INTO sessions (session_id, project, cwd, title, prompts) VALUES (?, '-home-u-app', '/home/u/app', 't', 1)",
                 (session,))
    conn.execute("INSERT INTO requests (session_id, request_key, ts, model, prompt_idx, skill, agent_id, agent_type, input, output, "
                 "cache_read, cache_write_5m, cache_write_1h, cost_usd) VALUES (?, ?, ?, 'claude-opus-5-5', 1, ?, ?, ?, ?, 0, 0, 0, 0, ?)",
                 (session, key, budgets.tz.now().astimezone(budgets.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"), skill,
                  "ag1" if agent else None, agent, tokens, cost))
    conn.commit()


class BudgetsTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        env = mock.patch.dict(os.environ, {"TOKSCOPE_HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)
        self.db = self.home / "t.db"
        self.conn = connect(self.db)
        self.addCleanup(self.conn.close)

    def write(self, data):
        (self.home / "budgets.json").write_text(data if isinstance(data, str) else json.dumps(data))

    def test_a_missing_file_means_no_budgets_and_an_invalid_one_gives_a_clear_error(self):
        self.assertIsNone(budgets.load())
        for bad, why in (("{half", "not valid JSON"), ("[]", "must be a JSON object"), ('{"daily_usd": "5"}', "'daily_usd' must be a number"),
                         ('{"daily_usd": 0}', "above 0"), ('{"block_pct": 150}', "at most 100"), ('{"nope": 1}', "unknown key 'nope'"),
                         ('{"skills": {"x": {"daily_pct": 1}}}', "unknown key 'daily_pct'"), ('{"agents": {"x": {"per_load_tokens": 5}}}', "unknown key"),
                         ('{"skills": []}', "must be an object"), ('{"daily_usd": true}', "must be a number")):
            self.write(bad)
            with self.assertRaises(budgets.BudgetError, msg=bad) as cm:
                budgets.load()
            self.assertIn(why, str(cm.exception))
            self.assertIn("budgets.json", str(cm.exception))

    def test_every_documented_key_loads(self):
        data = {"daily_usd": 50, "block_pct": 80, "weekly_pct": 90, "daily_tokens": 5e6,
                "skills": {"xia2": {"per_load_tokens": 200000}}, "agents": {"reviewer": {"daily_usd": 10}}}
        self.write(data)
        self.assertEqual(budgets.load(), data)

    def check(self, data):
        return budgets.check(self.conn, data)

    def test_states_follow_the_eighty_and_hundred_percent_lines(self):
        seed(self.conn, 7.9)
        self.assertEqual(self.check({"daily_usd": 10})["state"], "ok")
        seed(self.conn, 0.1, key="b")  # 8.0 of 10: exactly 80%
        self.assertEqual((self.check({"daily_usd": 10})["state"], self.check({"daily_usd": 10})["exit"]), ("near", 10))
        seed(self.conn, 2.0, key="c")  # 10.0 of 10
        self.assertEqual((self.check({"daily_usd": 10})["state"], self.check({"daily_usd": 10})["exit"]), ("over", 11))

    def test_no_budgets_no_measurable_item_or_an_empty_db_is_no_data(self):
        self.assertEqual(self.check(None)["exit"], 30)
        self.assertEqual(self.check({"daily_usd": 10})["exit"], 30)  # no requests at all
        seed(self.conn, 1.0)
        self.assertEqual(self.check({"block_pct": 80, "weekly_pct": 90})["exit"], 30)  # quota % has no snapshots
        mixed = self.check({"daily_usd": 10, "block_pct": 80})
        self.assertEqual((mixed["state"], [i["state"] for i in mixed["items"]]), ("ok", ["ok", "nodata"]))

    def test_tokens_budget(self):
        seed(self.conn, 0.0, tokens=900)
        r = self.check({"daily_tokens": 1000})
        self.assertEqual((r["state"], r["items"][0]["pct"]), ("near", 90.0))

    def test_skill_and_agent_budgets_use_the_attribution_of_summary_by(self):
        seed(self.conn, 6.0, skill="xia2", key="a")
        seed(self.conn, 5.0, agent="reviewer", key="b")
        seed(self.conn, 1.0, key="c")
        by_skill = {r["key"]: r["cost_usd"] for r in summary.rows(self.conn, "skill")}
        by_agent = {r["key"]: r["cost_usd"] for r in summary.rows(self.conn, "agent")}
        r = self.check({"skills": {"xia2": {"daily_usd": 10}}, "agents": {"reviewer": {"daily_usd": 5}, "ghost": {"daily_usd": 1}}})
        used = {i["key"]: (i["used"], i["state"]) for i in r["items"]}
        self.assertEqual(used["skills.xia2.daily_usd"], (by_skill["xia2"], "ok"))
        self.assertEqual(used["agents.reviewer.daily_usd"], (by_agent["reviewer"], "over"))
        self.assertEqual(used["agents.ghost.daily_usd"], (0, "ok"))
        self.assertEqual(r["exit"], 11)

    def test_per_load_tokens_uses_the_median_per_load_and_is_no_data_without_loads(self):
        self.assertEqual(self.check({"skills": {"xia2": {"per_load_tokens": 1000}}})["exit"], 30)
        seed(self.conn, 1.0, skill="xia2", tokens=900)
        self.conn.execute("INSERT INTO skill_calls (session_id, ts, skill, prompt_idx, tool_use_id) VALUES ('s1', '2026-01-01T00:00:00Z', 'xia2', 1, 'u1')")
        self.conn.commit()
        item = self.check({"skills": {"xia2": {"per_load_tokens": 1000}}})["items"][0]
        self.assertEqual((item["key"], item["used"], item["state"]), ("skills.xia2.per_load_tokens", 900, "near"))
        self.assertEqual(self.check({"skills": {"xia2": {"per_load_tokens": 800}}})["state"], "over")

    def test_crossed_names_what_this_session_pushed_over(self):
        seed(self.conn, 5.0, session="old", key="a")
        seed(self.conn, 4.0, session="new", key="b")
        hit = budgets.crossed(self.conn, {"daily_usd": 10, "daily_tokens": 1e9}, "new")
        self.assertEqual([i["key"] for i in hit], ["daily_usd"])
        seed(self.conn, 0.1, session="tiny", key="c")
        self.assertEqual(budgets.crossed(self.conn, {"daily_usd": 10}, "tiny"), [])  # 9.0 without it: still near, nothing crossed

    def run_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.object(cli, "DB", self.db), \
                mock.patch("sys.argv", ["tokscope", *argv]), mock.patch("sys.stdin", io.StringIO("{}")):
            try:
                cli.main()
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_check_once_exits_0_10_11_30_and_prints_json(self):
        code, out, _ = self.run_cli(["check", "--once"])
        self.assertEqual(code, 30)
        self.assertIn("no budgets file", out)
        self.write({"daily_usd": 10})
        seed(self.conn, 1.0)
        self.assertEqual(self.run_cli(["check", "--once"])[0], 0)
        seed(self.conn, 7.5, key="b")
        code, out, _ = self.run_cli(["check", "--once", "--json"])
        self.assertEqual((code, json.loads(out)["state"]), (10, "near"))
        seed(self.conn, 5.0, key="c")
        self.assertEqual(self.run_cli(["check", "--once"])[0], 11)

    def test_check_once_needs_once_and_an_invalid_file_exits_with_its_message(self):
        self.write("{half")
        code, _, _ = self.run_cli(["check"])
        self.assertEqual(code, 2)  # argparse: --once is required
        code, _, err = self.run_cli(["check", "--once"])
        self.assertEqual(code, 2)
        self.assertIn("budgets.json", err)
        self.assertIn("not valid JSON", err)

    def test_statusline_warns_near_and_over_and_names_a_bad_file(self):
        self.assertNotIn("budgets", self.run_cli(["statusline"])[1])  # no file: plain
        self.write({"daily_usd": 10})
        seed(self.conn, 1.0)
        self.assertIn("budgets ok", self.run_cli(["statusline"])[1])
        seed(self.conn, 7.5, key="b")
        self.assertIn("near: today 85%", self.run_cli(["statusline"])[1])
        self.assertIn("\033[33m", self.run_cli(["statusline"])[1])
        seed(self.conn, 5.0, key="c")
        out = self.run_cli(["statusline"])[1]
        self.assertIn("OVER: today", out)
        self.assertIn("\033[31m", out)
        self.write("{half")
        out = self.run_cli(["statusline"])
        self.assertEqual(out[0], 0)
        self.assertIn("budgets.json is invalid", out[1])

    def test_session_json_carries_the_warnings_for_the_pane(self):
        seed(self.conn, 1.0)
        self.assertIsNone(cli.session_json(self.conn, "s1")["budget"])
        self.write({"daily_usd": 1.1})
        warn = cli.session_json(self.conn, "s1")["budget"]["warn"]
        self.assertEqual((warn[0]["state"], round(warn[0]["pct"])), ("near", 91))
        self.write("{half")
        self.assertIn("not valid JSON", cli.session_json(self.conn, "s1")["budget"]["error"])

    def test_the_session_end_ingest_prints_one_line_only_when_a_budget_was_crossed(self):
        seed(self.conn, 5.0, session="old", key="a")
        seed(self.conn, 4.0, session="new", key="b")
        seed(self.conn, 0.1, session="tiny", key="c")
        self.write({"daily_usd": 10})
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(cli, "DB", self.db):
            cli._budget_line("new")
        self.assertRegex(out.getvalue(), r"^tokscope budget: NEAR today 91% \(\$9\.10 of \$10\.00\)\n$")
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(cli, "DB", self.db):
            cli._budget_line("tiny")  # 9.0 of 10 without it: it crossed nothing
            self.write("{half")
            cli._budget_line("new")  # a bad file never breaks the hook
        self.assertEqual(out.getvalue(), "")

    def test_the_overview_shows_budget_bars_only_with_a_file_and_names_a_bad_one(self):
        f = Filters({})
        self.assertEqual(overview._budgets(self.conn), "")
        seed(self.conn, 9.0)
        self.write({"daily_usd": 10, "agents": {"reviewer": {"daily_usd": 1}}, "block_pct": 80})
        page = overview._budgets(self.conn)
        self.assertIn('class="bgt near"', page)
        self.assertIn('class="bgt nodata"', page)
        self.assertIn("width:90.0%", page)
        self.assertIn("bgt ok", page)
        self.assertIn('data-region="budgets"', overview.page_overview(self.conn, f))
        self.write("{half")
        self.assertIn('role="alert"', overview._budgets(self.conn))


if __name__ == "__main__":
    unittest.main()
