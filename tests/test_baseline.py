import json
import sqlite3
import unittest
from datetime import datetime, timezone

from tokscope.core import baseline
from tokscope.core.ingest import connect
from tests.test_ingest import SID, Fixture, assistant, human


def shape(tools):
    return {"type": "api-request-shape", "sessionId": SID, "shapeHash": "h", "timestamp": "2026-10-01T00:00:00Z",
            "shape": {"system": [{"type": "text", "text": "x"}], "tools": tools}}


def tool(name, text="d" * 100, **extra):
    return {"name": name, "description": text, "input_schema": {"type": "object"}, **extra}


class ShapeIngestTest(Fixture):
    # Claude Code writes compact JSON lines, and the parser tells a shape by its first characters
    def write_main(self, records):
        (self.project / f"{SID}.jsonl").write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records))

    def write_agent(self, agent_id, meta, records):
        d = self.project / SID / "subagents"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"agent-{agent_id}.jsonl").write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in records))
        (d / f"agent-{agent_id}.meta.json").write_text(json.dumps(meta))

    def test_mcp_definitions_are_summed_per_server_and_deferred_tools_count_nothing(self):
        a1, a2 = tool("mcp__docs__read"), tool("mcp__docs__write", "e" * 300)
        self.write_main([shape([tool("Bash"), a1, a2, tool("mcp__plugin_x_y__go", defer_loading=True),
                                tool("mcp__claude_ai_Linear__get")]), human("hi"), assistant("r1")])
        self.run_ingest()
        rows = self.rows("SELECT server, tools, chars FROM mcp_defs ORDER BY server")
        self.assertEqual(rows, [("claude_ai_Linear", 1, len(json.dumps(tool("mcp__claude_ai_Linear__get")))),
                                ("docs", 2, len(json.dumps(a1)) + len(json.dumps(a2)))])

    def test_only_the_first_main_thread_shape_counts_and_a_subagent_shape_is_ignored(self):
        self.write_main([shape([tool("mcp__a__x")]), human("hi"), assistant("r1"), shape([tool("mcp__b__x")])])
        self.write_agent("a1", {"agentType": "Explore", "toolUseId": "t", "spawnDepth": 1},
                         [shape([tool("mcp__c__x")]), assistant("r2")])
        self.run_ingest()
        self.assertEqual(self.rows("SELECT server FROM mcp_defs"), [("a",)])

    def test_a_session_without_a_shape_or_with_a_broken_one_has_no_rows(self):
        self.write_main([human("hi"), assistant("r1")])
        self.run_ingest()
        self.assertEqual(self.rows("SELECT * FROM mcp_defs"), [])
        self.write_main([{"type": "api-request-shape", "shape": {"tools": "nope"}}, human("hi"), assistant("r1")])
        self.run_ingest()
        self.assertEqual(self.rows("SELECT * FROM mcp_defs"), [])

    def test_an_existing_database_gets_the_table_and_a_changed_parser_reparses_unchanged_files(self):
        self.write_main([shape([tool("mcp__a__x")]), human("hi"), assistant("r1")])
        self.run_ingest()
        conn = sqlite3.connect(self.db)
        conn.execute("DROP TABLE mcp_defs")                       # a database from before this feature
        conn.execute("UPDATE ingest_state SET state = replace(state, '\"v\": 15', '\"v\": 14')")
        conn.execute("UPDATE sessions SET signature = 'v14:old'")
        conn.commit()
        conn.close()
        connect(self.db).close()
        self.run_ingest()
        self.assertEqual(self.rows("SELECT server FROM mcp_defs"), [("a",)])


class BaselineTest(Fixture):
    def test_a_baseline_is_the_first_main_thread_request_and_sidechain_requests_are_ignored(self):
        first = assistant("r1", cw5=2000, cw1=500)                # input 1 + cache_read 100 + 2000 + 500
        first["timestamp"] = "2026-10-01T00:00:10Z"
        later = assistant("r2", cw5=9000)
        later["timestamp"] = "2026-10-01T00:05:00Z"
        side = assistant("r3", cw5=77777)
        side["timestamp"] = "2026-10-01T00:00:01Z"                # earlier than the first main request
        self.write_main([human("hi"), first, later])
        self.write_agent("a1", {"agentType": "Explore", "toolUseId": "t", "spawnDepth": 1}, [side])
        self.run_ingest()
        rows = baseline.starts(connect(self.db))
        self.assertEqual([(r[0], r[4]) for r in rows], [(SID, 1 + 100 + 2000 + 500)])

    def test_stats_give_median_p90_cost_and_a_30_day_trend(self):
        now = datetime(2026, 10, 30, tzinfo=timezone.utc)
        rows = [(f"s{i}", "/p", f"2026-10-{d:02d}T10:00:00Z", "claude-opus-5-5", t)
                for i, (d, t) in enumerate([(1, 1000), (5, 2000), (20, 3000), (25, 4000), (28, 10000)])]
        s = baseline.stats(rows, now)
        self.assertEqual((s["n"], s["median"], s["p90"]), (5, 3000, 10000))
        self.assertAlmostEqual(s["cost"], 3000 * 4.0 * 1.25 / 1e6)  # the cache-write rate of the model
        self.assertEqual(s["trend"], [1000, 2000, 3000, 4000, 10000])
        self.assertEqual((s["first"], s["last"]), (1500, 4000))
        self.assertIsNone(baseline.stats([], now))

    def test_an_unpriced_model_has_tokens_but_no_cost(self):
        s = baseline.stats([("s", "/p", "2026-10-01T00:00:00Z", "mystery-model", 500)])
        self.assertEqual(s["median"], 500)
        self.assertIsNone(s["cost"])

    def test_haiku_session_starts_are_priced_at_their_own_size_not_at_a_million_tokens(self):
        model = "claude-haiku-5-5"                                # 5x above 100k tokens in one request
        self.assertAlmostEqual(baseline.start_usd(model, 150_000), 15 * baseline.start_usd(model, 50_000))
        s = baseline.stats([("s", "/p", "2026-10-01T00:00:00Z", model, 50_000)])
        self.assertAlmostEqual(s["cost"], baseline.start_usd(model, 50_000))

    def _insert(self, conn, sid, first_ts, request_ts):
        conn.execute("INSERT INTO sessions (session_id, project, cwd, first_ts) VALUES (?, 'p', '/p', ?)", (sid, first_ts))
        for i, ts in enumerate(request_ts):
            conn.execute("INSERT INTO requests (session_id, request_key, ts, model, input, cache_read, cache_write_5m, "
                         "cache_write_1h) VALUES (?, ?, ?, 'claude-opus-5-5', 1, 5000, 0, 0)", (sid, f"{sid}{i}", ts))

    def test_a_session_whose_first_request_is_not_in_the_database_is_skipped(self):
        conn = connect(self.db)
        self._insert(conn, "own", "2026-10-01T10:00:00Z", ["2026-10-01T10:00:05Z"])
        # a fork: its early requests were copied from an earlier session and kept only there (ingest._share_requests)
        self._insert(conn, "fork", "2026-10-01T10:00:00Z", ["2026-10-01T10:30:00Z"])
        self.assertEqual([r[0] for r in baseline.starts(conn)], ["own"])

    def test_a_range_gives_the_same_sessions_in_a_filtered_copy_as_in_the_full_database(self):
        conn = connect(self.db)
        self._insert(conn, "old", "2026-10-01T00:00:00Z", ["2026-10-01T00:00:10Z", "2026-10-02T09:00:00Z"])
        self._insert(conn, "new", "2026-10-02T08:00:00Z", ["2026-10-02T08:00:05Z"])
        cond, params = "WHERE r.ts >= ?", ("2026-10-02",)
        full = [r[0] for r in baseline.starts(conn, cond, params)]
        conn.execute("DELETE FROM requests WHERE ts < '2026-10-02'")  # what privacy.redacted_copy does with the range
        self.assertEqual([r[0] for r in baseline.starts(conn)], full)
        self.assertEqual(full, ["new"])


if __name__ == "__main__":
    unittest.main()
