import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tokscope import charts
from tokscope.ingest import connect
from tokscope.ingest import CARRIED
from tokscope.report import _breakdowns, _week_skills, _weekly_phases

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


if __name__ == "__main__":
    unittest.main()
