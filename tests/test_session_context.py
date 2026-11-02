"""session_json carries `context`: the size of the last main-thread request, which the mod's 300K nudge reads."""
import tempfile
import unittest
from pathlib import Path

from tokscope import cli
from tokscope.core.ingest import connect


def add(conn, key, ts, agent=None, inp=0, out=0, cr=0, cw5=0, cw1=0, session="s1"):
    conn.execute("INSERT OR IGNORE INTO sessions (session_id, project, cwd, title, prompts) VALUES (?, 'p', '/p', 't', 1)", (session,))
    conn.execute("INSERT INTO requests (session_id, request_key, ts, model, prompt_idx, agent_id, input, output, cache_read, "
                 "cache_write_5m, cache_write_1h, cost_usd) VALUES (?, ?, ?, 'claude-opus-5-5', 1, ?, ?, ?, ?, ?, ?, 0.1)",
                 (session, key, ts, agent, inp, out, cr, cw5, cw1))
    conn.commit()


class SessionContextTest(unittest.TestCase):
    def setUp(self):
        self.conn = connect(Path(tempfile.mkdtemp()) / "t.db")
        self.addCleanup(self.conn.close)

    def test_context_is_the_last_main_thread_request_without_output(self):
        add(self.conn, "a", "2026-10-01T00:00:01Z", inp=10, cr=100)
        add(self.conn, "b", "2026-10-01T00:00:02Z", inp=1, cr=200_000, cw5=50_000, cw1=49_000, out=7_777)
        add(self.conn, "c", "2026-10-01T00:00:03Z", agent="ag1", inp=999_999)  # a later subagent request is not the context
        out = cli.session_json(self.conn, "s1")
        self.assertFalse(out["empty"])
        self.assertEqual(out["context"], 1 + 200_000 + 50_000 + 49_000)

    def test_a_session_with_only_subagent_requests_has_context_zero(self):
        add(self.conn, "a", "2026-10-01T00:00:01Z", agent="ag1", inp=500)
        self.assertEqual(cli.session_json(self.conn, "s1")["context"], 0)

    def test_an_unknown_session_is_empty_with_context_zero(self):
        out = cli.session_json(self.conn, "nope")
        self.assertTrue(out["empty"])
        self.assertEqual(out["context"], 0)


    def test_compacted_is_true_once_the_context_fell_below_300k_after_reaching_it(self):
        add(self.conn, "a", "2026-10-01T00:00:01Z", cr=350_000)
        self.assertFalse(cli.session_json(self.conn, "s1")["compacted"])
        add(self.conn, "b", "2026-10-01T00:00:02Z", cr=10_000)
        add(self.conn, "c", "2026-10-01T00:00:03Z", cr=400_000)
        self.assertTrue(cli.session_json(self.conn, "s1")["compacted"])

    def test_a_low_start_and_a_subagent_dip_is_not_a_compact(self):
        add(self.conn, "a", "2026-10-01T00:00:01Z", cr=10_000)
        add(self.conn, "b", "2026-10-01T00:00:02Z", cr=350_000)
        add(self.conn, "c", "2026-10-01T00:00:03Z", agent="ag1", cr=5_000)
        self.assertFalse(cli.session_json(self.conn, "s1")["compacted"])


if __name__ == "__main__":
    unittest.main()
