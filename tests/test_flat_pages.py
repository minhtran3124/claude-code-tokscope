import sqlite3
import unittest
from unittest import mock

from tokscope.web.dashboard.pages import benchmarks


class BenchmarksPageTest(unittest.TestCase):
    def conn(self):
        c = sqlite3.connect(":memory:")
        c.executescript("""CREATE TABLE bench_runs (run_id, task, variant, run_idx, session_id, started_at, duration_s, exit_code,
            is_error, reported_cost, passed, result, commit_sha, cc_version, skill_check);
            CREATE TABLE requests (session_id, request_key, agent_id, model, input, output, thinking, cache_read, cache_write_5m,
            cache_write_1h, cost_usd);""")
        for variant, tok, passed in (("a", 100000, 1), ("b", 120000, 0)):
            sid = "s" + variant
            c.execute("INSERT INTO bench_runs VALUES (?,?,?,0,?,'',1,0,0,0,?,'x','abc','',NULL)", (sid, "t", variant, sid, passed))
            c.execute("INSERT INTO requests VALUES (?,'k',NULL,'m',?,0,0,0,0,0,0.5)", (sid, tok))
        return c

    def test_row_shows_change_verdict_and_rail(self):
        with mock.patch.object(benchmarks.paths, "tasks", return_value="/nonexistent"):
            out = benchmarks.page_benchmarks(self.conn(), None)
        self.assertIn("+20.0%", out)
        self.assertIn("answer differs", out)
        self.assertIn("Needs a look (1)", out)
        self.assertIn("Cost of a run", out)

    def test_empty_keeps_the_hint(self):
        c = sqlite3.connect(":memory:")
        with mock.patch.object(benchmarks.paths, "tasks", return_value="/nonexistent"):
            self.assertIn("No benchmark runs yet", benchmarks.page_benchmarks(c, None))


if __name__ == "__main__":
    unittest.main()
