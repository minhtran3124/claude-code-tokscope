import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tokscope.web import charts
from tokscope.core.ingest import connect
from tokscope.core.ingest import CARRIED
from tokscope.web.report.sections.breakdowns import _breakdowns, _week_skills, _weekly_phases

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)  # a Tuesday
COND, PARAMS = "WHERE s.project NOT LIKE ?", ("%bench%",)


class WeekTest(unittest.TestCase):
    def setUp(self):
        self.conn = connect(Path(tempfile.mkdtemp()) / "t.db")
        self.conn.executemany("INSERT INTO sessions (session_id, project) VALUES (?, ?)",
                              [("real", "-home-u-app"), ("bench", "-home-u-bench-1")])
        self.n = 0

    def req(self, days_ago, tokens, skill, phase="review", session="real", agent=None):
        self.n += 1
        self.conn.execute(
            "INSERT INTO requests (session_id, request_key, ts, model, agent_id, agent_type, skill, phase, input, output, "
            "cache_read, cache_write_5m, cache_write_1h, cost_usd) VALUES (?,?,?,?,?,?,?,?,?,0,0,0,0,0)",
            (session, f"k{self.n}", (NOW - timedelta(days=days_ago)).isoformat(), "m", agent, agent and "reviewer",
             skill, phase, tokens))

    def test_the_report_nav_links_the_context_section(self):
        from pathlib import Path
        import tokscope.web.report.writer as w
        self.assertIn('<a href="#context">Context</a>', Path(w.__file__).read_text())

    def test_the_report_states_the_session_start_as_an_estimate_and_skips_benchmarks_and_empty_data(self):
        from tokscope.web.report.sections.summary import _session_start
        self.assertEqual(_session_start(self.conn, COND, PARAMS), "")
        self.req(1, 4000, "a")
        self.req(0, 90000, "a", agent="x1")                      # a subagent request is not a session start
        self.req(1, 99999, "a", session="bench")
        line = _session_start(self.conn, COND, PARAMS)
        self.assertIn("Every new session starts at ~4.0K tokens", line)
        self.assertIn("Estimate.", line)
        self.assertIn("median of 1 session", line)

    def test_skills_rank_by_the_last_7_days_and_carry_the_7_before(self):
        self.req(1, 100, "a")
        self.req(9, 400, "a")    # last week: a fell from 400 to 100
        self.req(2, 300, "b")    # new this week, so it ranks first
        self.req(20, 999, "c")   # older than 14 days: in neither window
        self.req(1, 5000, "a", session="bench")  # benchmarks never count
        self.assertEqual(_week_skills(self.conn, COND, PARAMS, NOW), [("b", "review", 300, 0), ("a", "review", 100, 400)])

    def test_a_skill_with_nothing_this_week_drops_out(self):
        self.req(9, 400, "gone")
        self.assertEqual(_week_skills(self.conn, COND, PARAMS, NOW), [])

    def test_weeks_start_on_monday_and_only_the_current_one_is_partial(self):
        self.req(1, 10, "a", "review")    # Mon Oct 19
        self.req(1, 5, "a", "implement")
        self.req(8, 20, "a", "review")    # Mon Oct 12
        self.req(2, 30, "a", "review")    # Sun Oct 18 belongs to the week of Oct 12
        weeks = _weekly_phases(self.conn, COND, PARAMS, today=NOW.date())
        self.assertEqual(weeks, [("Oct 12", {"review": 50}), ("Oct 19 so far", {"review": 10, "implement": 5})])


    def test_a_phase_splits_into_the_prompts_that_ran_its_skill_and_the_later_ones_that_carried_it(self):
        self.req(1, 100, "correctness-review")           # direct: the skill ran in this prompt
        self.req(1, 300, None)                           # carried: a later prompt with no skill
        self.req(1, 50, None, phase=None)                # before any skill: unscoped
        carried = self.conn.execute(f"SELECT sum(input) FROM requests r WHERE {CARRIED}").fetchone()[0]
        self.assertEqual(carried, 300)
        page = _breakdowns(self.conn, COND, PARAMS)
        self.assertIn("(66.7% of all tokens)", page)
        self.assertRegex(page, r"<td[^>]*>review</td><td[^>]*>1</td><td[^>]*>.*?400.*?</td><td[^>]*>100</td><td[^>]*>300 \(75%\)</td>")

    def test_a_skill_shows_its_main_thread_and_its_subagents_apart(self):
        self.req(1, 100, "correctness-review")
        self.req(1, 700, "correctness-review", agent="a1")
        page = _breakdowns(self.conn, COND, PARAMS)
        self.assertRegex(page, r"<td[^>]*>correctness-review</td>.*?800.*?</td><td[^>]*>100</td><td[^>]*>700</td>")


class FindingTest(WeekTest):
    """Each folded Breakdowns section says its finding in the summary line; the how-it-is-counted text is inside."""

    def summary(self, page, anchor):
        import re
        m = re.search(rf'<details class="more finding-sec" id="{anchor}"><summary>(.*?)</summary>(.*?)</details>', page, re.S)
        return re.sub(r"<[^>]+>", "", m.group(1)), m.group(2)

    def test_owner_finding_is_the_subagent_share_and_the_how_text_is_inside(self):
        self.req(1, 300, "a")
        self.req(1, 100, "a", agent="a1")
        head, inner = self.summary(_breakdowns(self.conn, COND, PARAMS), "by-owner")
        self.assertIn("Subagents use 25% of all tokens", head)
        self.assertNotIn("rows sum to the total", head)
        self.assertIn("rows sum to the total", inner)

    def test_owner_finding_when_no_subagent_ran(self):
        self.req(1, 300, "a")
        head, _ = self.summary(_breakdowns(self.conn, COND, PARAMS), "by-owner")
        self.assertIn("No subagent ran: the main thread has every token", head)

    def test_phase_skill_and_subagent_type_findings(self):
        self.req(1, 300, "a", phase="review")
        self.req(1, 100, "b", phase="plan", agent="a1")
        page = _breakdowns(self.conn, COND, PARAMS)
        self.assertIn("review is the largest phase at 75.0%; 0.0% is carried", self.summary(page, "by-phase")[0])
        self.assertIn("a uses 75% of all tokens; 2 skills loaded", self.summary(page, "by-skill")[0])
        self.assertIn("1 run across 1 type; reviewer uses 100% of subagent tokens", self.summary(page, "agent-types")[0])

    def test_week_finding_compares_with_the_week_before(self):
        self.req(1, 300, "a")
        self.req(9, 100, "a")
        head, _ = self.summary(_breakdowns(self.conn, COND, PARAMS, now=NOW), "by-week")  # NOW, not the clock: the rows are dated from NOW
        self.assertIn("this week, ", head)
        self.assertIn("on last week; a leads", head)

    def test_mcp_and_tool_findings_come_from_result_size(self):
        for name, chars in (("mcp__gh__issue", 3000), ("mcp__gh__pr", 1000), ("mcp__db__q", 6000), ("Read", 8000)):
            self.conn.execute("INSERT INTO tool_calls (session_id, tool_use_id, name, result_chars) VALUES (?,?,?,?)",
                              ("real", name, name, chars))
        self.req(1, 10, None)
        page = _breakdowns(self.conn, COND, PARAMS)
        self.assertIn("db holds 60% of MCP result tokens across 2 servers", self.summary(page, "by-mcp")[0])
        self.assertIn("Read returns 100% of tool result tokens across 1 tool", self.summary(page, "by-tool")[0])

    def test_errors_section_ranks_skills_agents_and_phases_by_failed_calls(self):
        rows = [("t1", "a", "review", "a1", 1, "edit_mismatch", 0), ("t2", "a", "review", "a1", 1, "not_found", 1),
                ("t3", "b", "plan", None, 0, None, 0), ("t4", "b", "plan", None, 0, None, 0)]
        self.conn.executemany("INSERT INTO tool_calls (session_id, tool_use_id, skill, phase, agent_id, is_error, err_class, repeat, ts) "
                              "VALUES ('real', ?, ?, ?, ?, ?, ?, ?, '2026-10-19T00:00:00+00:00')",
                              [(t, s, p, a, e, c, r) for t, s, p, a, e, c, r in rows])
        self.conn.execute("INSERT INTO subagents (session_id, agent_id, agent_type) VALUES ('real', 'a1', 'reviewer')")
        self.conn.execute("INSERT INTO turn_events (session_id, skill, kind) VALUES ('real', 'a', 'interrupt')")
        head, inner = self.summary(_breakdowns(self.conn, COND, PARAMS), "errors")
        self.assertIn("2 of 4 tool calls failed (50.0%)", head)
        self.assertIn("1 repeated, 1 interrupt", head)
        self.assertIn("<h3>Subagent type</h3>", inner)
        self.assertIn("reviewer", inner)
        self.assertIn("100.0%", inner)  # skill a: both calls failed

    def test_an_empty_range_says_what_would_appear_and_how_to_get_it(self):
        page = _breakdowns(self.conn, COND, PARAMS)
        for anchor, head, hint in (("by-week", "No skill loaded in the last 7 days", "tokscope ingest"),
                                   ("by-mcp", "No MCP server called", "claude mcp add"),
                                   ("by-tool", "No tool called", "tokscope ingest"),
                                   ("by-phase", "No tokens in this range", "tokscope ingest"),
                                   ("by-owner", "No tokens in this range", "tokscope ingest"),
                                   ("by-skill", "No skill loaded", "tokscope ingest"),
                                   ("agent-types", "No subagent ran", "tokscope ingest")):
            h, inner = self.summary(page, anchor)
            self.assertIn(head, h, anchor)
            self.assertIn('<div class="empty">', inner, anchor)
            self.assertIn(hint, inner, anchor)
            self.assertNotIn("<table", inner, anchor)

    def test_a_skill_request_with_zero_tokens_does_not_divide_by_zero(self):
        self.req(1, 0, "a")
        page = _breakdowns(self.conn, COND, PARAMS)
        self.assertIn("a uses 0% of all tokens; 1 skill loaded", self.summary(page, "by-skill")[0])
        from tokscope.web.report import write_report
        self.conn.commit()
        db = Path(self.conn.execute("PRAGMA database_list").fetchone()[2])
        write_report(db, db.parent / "r.html", tasks_dir=db.parent)
        self.assertIn("by-skill", (db.parent / "r.html").read_text())

    def test_the_skill_count_is_not_capped_at_30_and_a_near_total_share_is_not_100(self):
        for i in range(35):
            self.req(1, 1, f"s{i}")
        self.req(1, 10000, "big")
        head, _ = self.summary(_breakdowns(self.conn, COND, PARAMS), "by-skill")
        self.assertIn("36 skills loaded", head)
        self.assertIn("big uses 99% of all tokens", head)
        from tokscope.web.report.widgets import _pc
        self.assertEqual((_pc(0.001), _pc(0.001, True), _pc(1)), ("&lt;1%", "under 1%", "100%"))

    def test_no_changes_says_how_to_record_one(self):
        from tokscope.web.report.sections.skills import _change_cards
        self.assertIn('tokscope change "note" --skill NAME', _change_cards(self.conn, []).replace("&quot;", '"'))


class ChartTest(unittest.TestCase):
    def test_change_reads_as_a_multiple_past_double(self):
        self.assertEqual(charts.change_text(0, 50), "new")
        self.assertEqual(charts.change_text(100, 150), "▲ 50%")
        self.assertEqual(charts.change_text(100, 25), "▼ 75%")
        self.assertEqual(charts.change_text(10, 306), "▲ 30.6×")

    def test_the_tail_folds_into_other_and_slots_follow_size(self):
        parts = charts.fold([("s", 1), ("a", 9), ("b", 8), ("c", 7), ("d", 6), ("e", 5), ("f", 2)])
        self.assertEqual([(n, s) for n, _, s in parts], [("a", 1), ("b", 2), ("c", 3), ("d", 4), ("e", 5), ("Other (2)", 0)])
        self.assertEqual(parts[-1][1], 3)

    def test_axis_ends_on_a_round_number(self):
        self.assertEqual([charts._nice(v) for v in (330e6, 2.7e9, 7, 100)], [400e6, 3e9, 8, 100])

    def test_names_from_a_chart_are_escaped(self):
        svg = charts.dumbbell([("<script>", 1, 2)], "tokens")
        self.assertNotIn("<script>", svg)


class TimeZoneSettingTest(unittest.TestCase):
    def test_the_scripts_show_times_in_the_browser_zone_with_a_utc_switch(self):
        from tokscope.web.report.scripts import JS
        self.assertIn("tokscope-tz", JS)
        self.assertIn("data-set-tz", JS)
        self.assertNotIn("s.start.slice(0,10)", JS)  # days come from dayOf, which follows the setting


if __name__ == "__main__":
    unittest.main()
