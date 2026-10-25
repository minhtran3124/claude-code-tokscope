import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tokscope.features.changes import add_change, impact, impact_text, list_changes
from tokscope.core.ingest import connect

AT = datetime(2026, 10, 10, tzinfo=timezone.utc)


def ts(days):
    return (AT + timedelta(days=days)).isoformat()


class ChangeTest(unittest.TestCase):
    def setUp(self):
        self.conn = connect(Path(tempfile.mkdtemp()) / "t.db")
        self.conn.executemany("INSERT INTO sessions (session_id, project) VALUES (?, ?)",
                              [("real", "-home-u-edgeful-app"), ("bench", "-home-u-tokscope-bench-snapshots-s-1"),
                               ("bench2", "-home-u-cc-tokscope-mod-bench-replay-wt-1")])

    def run_agent(self, session, agent_id, day, tokens, model="claude-fable-5-1", agent_type="reviewer"):
        # two requests per run: impact must sum them into one unit
        for i, share in enumerate((tokens // 2, tokens - tokens // 2)):
            self.conn.execute(
                "INSERT INTO requests (session_id, request_key, ts, model, agent_id, agent_type, input, output, "
                "cache_read, cache_write_5m, cache_write_1h, cost_usd) VALUES (?,?,?,?,?,?,?,0,0,0,0,0.1)",
                (session, f"{agent_id}-{i}", ts(day), model, agent_id, agent_type, share))

    def test_a_change_must_name_what_it_affects(self):
        with self.assertRaises(ValueError):
            add_change(self.conn, "tweak something")

    def test_runs_split_at_the_change_and_are_summed_per_run(self):
        self.run_agent("real", "a1", -3, 1000)
        self.run_agent("real", "a2", -1, 3000)
        self.run_agent("real", "a3", 1, 400, model="claude-opus-5-5")
        cid = add_change(self.conn, "reviewer: fable -> opus", agent_type="reviewer", at=AT.isoformat())
        change = next(c for c in list_changes(self.conn) if c[0] == cid)

        r = impact(self.conn, change, days=14)

        self.assertEqual((r["before"]["n"], r["before"]["tokens_median"]), (2, 2000))
        self.assertEqual((r["after"]["n"], r["after"]["tokens_median"]), (1, 400))
        self.assertEqual(r["after"]["models"], ["claude-opus-5-5"])
        self.assertIn("-80%", impact_text(self.conn, change))

    def calls(self, session, agent_id, agent_type, day, failed, total, skill=None, interrupts=0):
        self.conn.execute("INSERT OR IGNORE INTO subagents (session_id, agent_id, agent_type) VALUES (?,?,?)",
                          (session, agent_id, agent_type))
        for i in range(total):
            self.conn.execute("INSERT INTO tool_calls (session_id, tool_use_id, agent_id, name, is_error, repeat, skill, ts) "
                              "VALUES (?,?,?,'Bash',?,0,?,?)",
                              (session, f"{agent_id}-{day}-{i}", agent_id, int(i < failed), skill, ts(day)))
        for _ in range(interrupts):
            self.conn.execute("INSERT INTO turn_events (session_id, ts, agent_id, skill, kind) VALUES (?,?,?,?,'interrupt')",
                              (session, ts(day), agent_id, skill))

    def test_the_error_rate_is_counted_on_both_sides_next_to_tokens(self):
        self.run_agent("real", "a1", -2, 1000)
        self.run_agent("real", "a2", 2, 1000)
        self.calls("real", "a1", "reviewer", -2, 1, 10)
        self.calls("real", "a2", "reviewer", 2, 4, 10, interrupts=1)
        self.calls("real", "x", "coding", 2, 10, 10)  # another agent type
        self.calls("bench", "b", "reviewer", 2, 10, 10)  # an experiment
        add_change(self.conn, "reviewer: new prompt", agent_type="reviewer", at=AT.isoformat())
        change = list_changes(self.conn)[0]

        r = impact(self.conn, change, days=14)

        self.assertEqual((r["before"]["errors"]["errors"], r["before"]["errors"]["calls"]), (1, 10))
        self.assertEqual((r["after"]["errors"]["errors"], r["after"]["errors"]["calls"], r["after"]["errors"]["interrupts"]),
                         (4, 10, 1))
        self.assertIn("errors 4/10 calls (40.0%)", impact_text(self.conn, change))
        self.assertIn("error rate 10.0% -> 40.0%", impact_text(self.conn, change))

    def test_a_skill_change_counts_the_calls_made_while_that_skill_ran(self):
        self.calls("real", "m", None, 1, 2, 5, skill="review")
        self.calls("real", "m2", None, 1, 5, 5, skill="other")
        add_change(self.conn, "review rewrite", skill="review", at=AT.isoformat())
        r = impact(self.conn, list_changes(self.conn)[0], days=14)
        self.assertEqual((r["after"]["errors"]["errors"], r["after"]["errors"]["calls"]), (2, 5))

    def test_benchmark_sessions_and_other_agents_are_left_out(self):
        self.run_agent("real", "a1", 1, 500)
        self.run_agent("bench", "b1", 1, 99999)  # experiment, not real work
        self.run_agent("bench2", "b2", 1, 88888)  # same, from the repo at …/cc-tokscope-mod
        self.run_agent("real", "c1", 1, 77777, agent_type="coding")
        add_change(self.conn, "reviewer change", agent_type="reviewer", at=AT.isoformat())

        r = impact(self.conn, list_changes(self.conn)[0], days=14)

        self.assertEqual((r["after"]["n"], r["after"]["tokens_median"]), (1, 500))

    def test_runs_outside_the_window_do_not_count(self):
        self.run_agent("real", "old", -20, 5000)
        self.run_agent("real", "a1", -2, 1000)
        add_change(self.conn, "reviewer change", agent_type="reviewer", at=AT.isoformat())

        r = impact(self.conn, list_changes(self.conn)[0], days=14)

        self.assertEqual(r["before"]["n"], 1)


if __name__ == "__main__":
    unittest.main()
