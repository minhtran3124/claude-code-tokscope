import tempfile
import unittest
from pathlib import Path

from tests.test_ingest import Fixture, assistant, human, result
from tokscope.core import context
from tokscope.core.ingest import connect
from tokscope.web.report.sections.breakdowns import _breakdowns

SONNET = "claude-sonnet-4-6"   # 4.0 chars per token, cache read $0.30 per million
NEW = "claude-opus-5-5"        # 4.7 and later: 3.08 chars per token, cache read $0.20 per million
COND, PARAMS = "WHERE s.project NOT LIKE 'zz%'", ()


def at(n):
    return f"2026-10-01T00:00:{n:02d}.000Z"


class CarryTest(unittest.TestCase):
    """A thread of six requests; a 40,000-character Read (10,000 tokens) is made by request 2 and a compaction
    follows request 4. Hand calculation: the requests after the call and before the compaction are 3 and 4, so
    carry = 10,000 tokens x 2 requests x $0.30 / 1,000,000 = $0.006."""

    def setUp(self):
        self.conn = connect(Path(tempfile.mkdtemp()) / "t.db")
        self.conn.execute("INSERT INTO sessions (session_id, project, title, prompts) VALUES ('s1', 'app', 'T', 1)")
        for n in range(1, 7):
            self.conn.execute(
                "INSERT INTO requests (session_id, request_key, ts, model, input, output, cache_read, cache_write_5m, "
                "cache_write_1h) VALUES ('s1', ?, ?, ?, 10, 1, ?, 0, 0)", (f"r{n}", at(n), SONNET, n * 30_000))
        self.conn.execute("INSERT INTO turn_events (session_id, ts, kind) VALUES ('s1', ?, 'compact')", ("2026-10-01T00:00:04.500Z",))
        for tid, name, chars, ts, skill in (("t1", "Read", 40_000, at(2), "plan"), ("t2", "Read", 4_000, at(5), None),
                                            ("t3", "mcp__foo__search", 20_000, at(1), "plan"),
                                            ("t4", "mcp__foo__search", 80_000, at(5), "plan")):
            self.conn.execute("INSERT INTO tool_calls (session_id, tool_use_id, name, result_chars, ts, model, skill) "
                              "VALUES ('s1', ?, ?, ?, ?, ?, ?)", (tid, name, chars, ts, SONNET, skill))
        self.conn.commit()

    def test_the_carry_of_a_result_is_its_tokens_times_the_later_requests_until_the_compaction(self):
        calls = {c["tokens"]: c for c in context.load(self.conn)}
        read = calls[10_000]
        self.assertEqual(read["later"], 2)
        self.assertAlmostEqual(read["carry"], 0.006, places=9)
        self.assertEqual(calls[1_000]["later"], 1)      # made by request 5, only request 6 follows
        self.assertAlmostEqual(calls[1_000]["carry"], 1_000 * 0.30 / 1e6, places=9)
        # t3 came before the compaction: requests 2, 3 and 4 re-read it
        self.assertEqual((calls[5_000]["later"], round(calls[5_000]["carry"], 9)), (3, round(5_000 * 3 * 0.30 / 1e6, 9)))

    def test_ranking_has_median_p95_total_share_and_splits(self):
        calls = context.load(self.conn)
        read = next(r for r in context.rank(calls, "tool") if r["key"] == "Read")
        self.assertEqual((read["calls"], read["median"], read["p95"], read["total"]), (2, 5_500, 10_000, 11_000))
        self.assertAlmostEqual(read["share"], 11_000 / 36_000)
        server = context.rank(calls, "server")
        self.assertEqual([(r["key"], r["total"]) for r in server], [("foo", 25_000)])
        self.assertEqual(context.rank(calls, "mcp_tool")[0]["key"], "foo · search")
        by_skill = {(r["key"], r["split"]): r["total"] for r in context.rank(calls, "tool", "skill")}
        self.assertEqual(by_skill, {("Read", "plan"): 10_000, ("Read", "(none)"): 1_000})
        self.assertEqual(context.rank(calls, "tool", "project")[0]["split"], "app")

    def test_a_new_model_family_counts_more_tokens_for_the_same_characters(self):
        self.assertEqual(context.chars_per_token(SONNET), 4)
        self.assertAlmostEqual(context.chars_per_token(NEW), 4 / 1.3)
        self.assertEqual(context.chars_per_token("claude-opus-4-7-20260101"), context.NEW_CHARS_PER_TOKEN)
        self.assertEqual(context.chars_per_token("claude-opus-4-6"), 4)
        self.assertEqual(context.chars_per_token(None), 4)
        for legacy in ("claude-3-5-sonnet-20241022", "claude-3-7-sonnet-20250219", "claude-3-5-haiku-20241022"):
            self.assertIsNone(context.version(legacy))
            self.assertEqual(context.chars_per_token(legacy), 4)

    def test_pressure_is_the_peak_request_against_the_window_with_its_compactions(self):
        rows, compacts, _ = context.pressure(self.conn, COND, PARAMS)
        self.assertEqual((rows[0]["peak"], rows[0]["window"], rows[0]["compacts"], compacts), (180_010, 200_000, 1, 1))
        self.assertAlmostEqual(rows[0]["share"], 180_010 / 200_000)

    def test_findings_name_the_fat_tool_with_a_hint(self):
        for i in range(3):
            self.conn.execute("INSERT INTO tool_calls (session_id, tool_use_id, name, result_chars, ts, model) "
                              "VALUES ('s1', ?, 'mcp__foo__big', 200000, ?, ?)", (f"b{i}", at(1), SONNET))
        found = context.findings(context.load(self.conn), *context.pressure(self.conn, COND, PARAMS)[:0:-1])
        self.assertTrue(any("foo · big p95 ~50K tokens" in f and "limit or pagination" in f for f in found), found)
        self.assertTrue(any("reached 80% or more of the context window; 1 compaction" in f for f in found), found)

    def test_the_breakdowns_context_section_marks_estimates_and_follows_the_filter(self):
        page = _breakdowns(self.conn, COND, PARAMS)
        sec = page[page.index('id="context"'):page.index('id="errors"')]
        self.assertIn("<h3>MCP server</h3>", sec)
        self.assertIn("<h3>Context pressure</h3>", sec)
        self.assertIn(">~10.0K</span>", sec)
        self.assertIn("title=\"~ estimate:", sec)
        self.assertIn("Split by skill", sec)
        none = _breakdowns(self.conn, "WHERE s.project = 'other'", ())
        self.assertIn("No tool result recorded", none)


class IngestTest(Fixture):
    def test_a_compact_boundary_is_an_event_and_a_tool_call_keeps_its_model(self):
        boundary = {"type": "system", "subtype": "compact_boundary", "timestamp": "2026-10-01T00:00:03Z"}
        self.write_main([human("go"), assistant("r1", tools=[("t1", "Read", {})]), result("t1", "x" * 50), boundary,
                         assistant("r2")])
        self.run_ingest()
        self.assertEqual(self.rows("SELECT kind FROM turn_events"), [("compact",)])
        self.assertEqual(self.rows("SELECT model, result_chars FROM tool_calls"), [("claude-opus-5-5", 50)])


if __name__ == "__main__":
    unittest.main()
