import json
import tempfile
import unittest
from pathlib import Path

from tokscope.core import otel
from tokscope.core.ingest import connect, ingest_otel
from tokscope.core.pricing import cost_usd
from tokscope.web.report.sections.cost_check import cost_check

COND = "WHERE s.project NOT LIKE '%bench%'"


def attr(k, v):
    if isinstance(v, bool):
        return {"key": k, "value": {"boolValue": v}}
    if isinstance(v, int):
        return {"key": k, "value": {"intValue": str(v)}}  # OTLP JSON sends 64-bit ints as strings
    if isinstance(v, float):
        return {"key": k, "value": {"doubleValue": v}}
    return {"key": k, "value": {"stringValue": v}}


def event(session, ts, model, inp, out, read, write, cost, name="api_request", prompt="p1"):
    a = {"event.name": name, "event.timestamp": ts, "session.id": session, "prompt.id": prompt, "model": model,
         "input_tokens": inp, "output_tokens": out, "cache_read_tokens": read, "cache_creation_tokens": write,
         "cost_usd": cost, "duration_ms": 1840.0, "speed": "normal"}
    return {"resourceLogs": [{"resource": {"attributes": []}, "scopeLogs": [{"logRecords": [
        {"body": {"stringValue": "claude_code." + name}, "attributes": [attr(k, v) for k, v in a.items()]}]}]}]}


def line(body, signal="logs"):
    return json.dumps({"received_at": "2026-10-20T12:00:00+00:00", "signal": signal, "body": body}) + "\n"


class OtelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.dir = self.tmp / "otel"
        self.dir.mkdir()
        self.db = self.tmp / "t.db"
        self.conn = connect(self.db)
        self.conn.execute("INSERT INTO sessions (session_id, project) VALUES ('s1', '-home-u-app')")

    def write(self, text, name="logs-2026-10-20.jsonl", mode="a"):
        with open(self.dir / name, mode) as f:
            f.write(text)

    def req(self, key, ts, model, inp, out, read, write, session="s1"):
        cost = cost_usd(model, inp, out, read, write, 0)
        self.conn.execute("INSERT INTO requests (session_id, request_key, ts, model, input, output, thinking, cache_read, "
                          "cache_write_5m, cache_write_1h, cost_usd) VALUES (?,?,?,?,?,?,0,?,?,0,?)",
                          (session, key, ts, model, inp, out, read, write, cost))

    def ingest(self):
        return otel.ingest(self.conn, self.dir)

    def test_ingest_once_and_a_rerun_adds_nothing(self):
        self.write(line(event("s1", "2026-10-20T10:00:00.000Z", "claude-sonnet-4-6", 100, 50, 1000, 0, 0.01))
                   + line(event("s1", "2026-10-20T10:00:05.000Z", "claude-sonnet-4-6", 10, 5, 0, 0, 0.001, name="tool_result"))
                   + line({"resourceMetrics": []}, "metrics"))
        self.assertEqual(self.ingest(), 1)  # only the api_request event
        self.assertEqual(self.ingest(), 0)
        row = self.conn.execute("SELECT session_id, prompt_id, ts, model, input, output, cache_read, cache_write, cost_usd, "
                                "duration_ms FROM otel_requests").fetchall()
        self.assertEqual(row, [("s1", "p1", "2026-10-20T10:00:00.000Z", "claude-sonnet-4-6", 100, 50, 1000, 0, 0.01, 1840.0)])

    def test_a_later_line_is_added_and_a_half_written_line_waits(self):
        self.write(line(event("s1", "2026-10-20T10:00:00.000Z", "claude-sonnet-4-6", 1, 1, 0, 0, 0.1)))
        self.assertEqual(self.ingest(), 1)
        nxt = line(event("s1", "2026-10-20T10:01:00.000Z", "claude-sonnet-4-6", 2, 2, 0, 0, 0.2))
        self.write(nxt[:30])
        self.assertEqual(self.ingest(), 0)
        self.write(nxt[30:])
        self.assertEqual(self.ingest(), 1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM otel_requests").fetchone()[0], 2)

    def test_a_shrunk_or_replaced_file_is_read_again_without_duplicates(self):
        self.write(line(event("s1", "2026-10-20T10:00:00.000Z", "m", 1, 1, 0, 0, 0.1))
                   + line(event("s1", "2026-10-20T10:01:00.000Z", "m", 2, 2, 0, 0, 0.2)))
        self.assertEqual(self.ingest(), 2)
        self.write(line(event("s1", "2026-10-21T09:00:00.000Z", "m", 3, 3, 0, 0, 0.3)), mode="w")  # rotated: shorter
        self.assertEqual(self.ingest(), 1)
        self.assertEqual([r[0] for r in self.conn.execute("SELECT input FROM otel_requests")], [3])
        # replaced by a longer file with other content
        self.write(line(event("s1", "2026-10-22T09:00:00.000Z", "m", 7, 7, 0, 0, 0.7)) * 2, mode="w")
        self.assertEqual(self.ingest(), 2)
        self.assertEqual({r[0] for r in self.conn.execute("SELECT input FROM otel_requests")}, {7})
        self.assertEqual(self.conn.execute("SELECT count(*) FROM otel_requests").fetchone()[0], 2)

    def test_a_hostile_line_is_skipped_and_the_offset_moves_past_it(self):
        good = event("s1", "2026-10-20T12:00:00.000Z", "claude-opus-4-8", 10, 5, 0, 0, 0.01)
        bad = [{"resourceLogs": [1]}, {"resourceLogs": [{"scopeLogs": [{"logRecords": [{"attributes": [attr("event.name", 7)]}]}]}]}]
        for tok in ("nan", "1e999", "1e30"):
            bad.append(event("s2", "2026-10-20T12:00:00.000Z", "m", tok, 1, 0, 0, 0.0))
        text = "".join(line(b) for b in bad) + "[" * 100000 + "\n" + line(good)
        (self.dir / "logs-1.jsonl").write_text(text)
        conn = self.conn
        self.assertEqual(otel.ingest(conn, self.dir), 4)  # the good event, and "nan"/"1e999" read as 0 tokens, "1e30" clamped
        self.assertEqual(otel.ingest(conn, self.dir), 0)
        self.assertEqual(conn.execute("SELECT count(*) FROM otel_requests WHERE session_id = 's1'").fetchone()[0], 1)

    def test_a_huge_time_unix_nano_does_not_stop_ingest(self):
        def rec(nano):
            e = event("s2", "", "m", 1, 1, 0, 0, 0.0)
            e["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["timeUnixNano"] = nano
            return e
        good = event("s1", "2026-10-20T12:00:00.000Z", "claude-opus-4-8", 10, 5, 0, 0, 0.01)
        text = "".join(line(rec(n)) for n in ("1e22", "1e26", "1e30", "-1e26")) + line(good)
        (self.dir / "logs-1.jsonl").write_text(text)
        otel.ingest(self.conn, self.dir)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM otel_requests WHERE session_id = 's1'").fetchone()[0], 1)
        self.assertEqual(otel.ingest(self.conn, self.dir), 0)  # the offset moved past every line

    def test_a_transient_db_error_propagates_and_the_offset_stays_put(self):
        import sqlite3
        from unittest import mock
        (self.dir / "logs-1.jsonl").write_text(line(event("s1", "2026-10-20T12:00:00.000Z", "m", 10, 5, 0, 0, 0.01)))
        with mock.patch.object(otel, "events", side_effect=sqlite3.OperationalError("database is locked")):
            with self.assertRaises(sqlite3.OperationalError):
                otel.ingest(self.conn, self.dir)
        self.assertIsNone(self.conn.execute("SELECT off FROM otel_files").fetchone())
        self.assertEqual(otel.ingest(self.conn, self.dir), 1)  # the next run still reads the line

    def test_clamped_token_counts_from_two_sessions_do_not_break_cost_check_or_the_report(self):
        from tokscope.web.report import write_report
        self.write(line(event("a", "2026-10-20T10:00:00.000Z", "m", 1e30, 0, 0, 0, 0.1))
                   + line(event("b", "2026-10-20T10:00:00.000Z", "m", 1e30, 0, 0, 0, 0.1)))
        self.assertEqual(self.ingest(), 2)
        self.conn.commit()
        self.assertEqual(otel.cost_check(self.conn)["only"][1], 2)  # sum() of two INT64 maxima used to raise "integer overflow"
        write_report(self.db, self.tmp / "r.html", tasks_dir=self.tmp)

    def test_a_missing_folder_is_a_no_op(self):
        gone = self.tmp / "nothing"
        self.assertEqual(otel.ingest(self.conn, gone), 0)
        self.assertEqual(ingest_otel(self.db, gone, log=lambda *_: None), 0)
        self.assertIsNone(otel.cost_check(self.conn))
        self.assertEqual(cost_check(self.conn, "", ()), "")
        self.assertFalse(gone.exists())

    def test_an_old_database_gains_the_tables(self):
        self.conn.executescript("DROP TABLE otel_requests; DROP TABLE otel_files")
        self.conn.commit()
        self.conn = connect(self.db)
        self.write(line(event("s1", "2026-10-20T10:00:00.000Z", "m", 1, 1, 0, 0, 0.1)))
        self.assertEqual(self.ingest(), 1)

    def test_events_match_requests_by_session_tokens_and_time(self):
        m = "claude-sonnet-4-6"
        self.req("a", "2026-10-20T10:00:01.000Z", m, 100, 50, 1000, 0)
        self.req("b", "2026-10-20T10:00:02.000Z", m, 100, 50, 1000, 0)  # same tokens: one event each
        self.req("c", "2026-10-20T11:00:00.000Z", m, 5, 5, 0, 0)
        self.write(line(event("s1", "2026-10-20T10:00:00.000Z", m, 100, 50, 1000, 0, 0.01))
                   + line(event("s1", "2026-10-20T10:00:02.500Z", m, 100, 50, 1000, 0, 0.01))
                   + line(event("s1", "2026-10-20T11:00:00.000Z", m, 6, 5, 0, 0, 0.01))  # tokens differ
                   + line(event("s1", "2026-10-20T10:00:01.000Z", m, 5, 5, 0, 0, 0.01)))  # an hour off
        self.ingest()
        got = dict(self.conn.execute("SELECT ts, request_key FROM otel_requests"))
        self.assertEqual(got["2026-10-20T10:00:00.000Z"], "a")
        self.assertEqual(got["2026-10-20T10:00:02.500Z"], "b")
        self.assertIsNone(got["2026-10-20T11:00:00.000Z"])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM otel_requests WHERE request_key IS NULL").fetchone()[0], 2)

    def test_a_transcript_that_arrives_later_matches_the_old_events(self):
        self.write(line(event("s1", "2026-10-20T10:00:00.000Z", "claude-sonnet-4-6", 1, 1, 0, 0, 0.01)))
        self.ingest()
        self.req("a", "2026-10-20T10:00:00.500Z", "claude-sonnet-4-6", 1, 1, 0, 0)
        self.ingest()
        self.assertEqual(self.conn.execute("SELECT request_key FROM otel_requests").fetchone()[0], "a")

    def test_drift_per_model_a_model_with_no_rate_drifts_100_percent_and_telemetry_only_sessions_show(self):
        cost = cost_usd("claude-sonnet-4-6", 1000, 500, 0, 0, 0)
        self.req("a", "2026-10-20T10:00:00.000Z", "claude-sonnet-4-6", 1000, 500, 0, 0)
        self.req("b", "2026-10-20T10:01:00.000Z", "claude-mystery-9", 10, 10, 0, 0)  # no rate: cost_usd is NULL
        self.write(line(event("s1", "2026-10-20T10:00:00.000Z", "claude-sonnet-4-6", 1000, 500, 0, 0, cost * 1.5))
                   + line(event("s1", "2026-10-20T10:01:00.000Z", "claude-mystery-9", 10, 10, 0, 0, 0.5))
                   + line(event("s1", "2026-10-20T10:02:00.000Z", "claude-sonnet-4-6", 9, 9, 0, 0, 0.25))  # no request
                   + line(event("gone", "2026-10-20T09:00:00.000Z", "claude-sonnet-4-6", 40, 20, 100, 0, 2.0))
                   + line(event("gone", "2026-10-20T09:01:00.000Z", "claude-sonnet-4-6", 40, 20, 100, 0, 1.0)))
        self.ingest()
        c = otel.cost_check(self.conn, COND, ())
        by = {m["model"]: m for m in c["models"]}
        self.assertAlmostEqual(by["claude-sonnet-4-6"]["drift"], 1 / 3, places=6)  # |cost - 1.5 cost| / (1.5 cost)
        self.assertEqual(by["claude-mystery-9"]["drift"], 1.0)
        self.assertTrue(by["claude-mystery-9"]["unpriced"])
        self.assertEqual(c["n"], 2)
        self.assertEqual(tuple(c["unmatched"]), (1, 0.25))
        self.assertEqual(tuple(c["only"]), (1, 2, 320, 3.0))  # session "gone" has no transcript
        card = cost_check(self.conn, COND, ())
        self.assertIn("100% (no rate)", card)
        self.assertIn("33%", card)
        self.assertIn("telemetry only", card)
        self.assertIn("1 unmatched event", card)
        self.assertIn(f"${cost * 1.5 + 0.5 + 0.25 + 3.0:,.2f}", card)  # the Claude Code total, telemetry-only included
        self.assertNotIn("telemetry only", cost_check(self.conn, COND, (), scoped=True))

    def test_telemetry_only_and_unmatched_leave_out_bench_sessions(self):
        from tokscope.features.changes import BENCH_PROJECT
        self.assertEqual(otel.BENCH_LIKE, BENCH_PROJECT)
        self.conn.execute("INSERT INTO sessions (session_id, project) VALUES ('b1', '-x-tokscope-bench-t1')")
        self.conn.execute("INSERT INTO sessions (session_id, project) VALUES ('b2', '-x-tokscope-bench-t2')")  # no requests
        self.req("a", "2026-10-20T10:00:00.000Z", "claude-sonnet-4-6", 1000, 500, 0, 0)
        self.req("k", "2026-10-20T10:00:00.000Z", "claude-sonnet-4-6", 7, 7, 0, 0, session="b1")
        self.write(line(event("s1", "2026-10-20T10:00:00.000Z", "claude-sonnet-4-6", 1000, 500, 0, 0, 0.5))
                   + line(event("b1", "2026-10-20T10:05:00.000Z", "claude-sonnet-4-6", 9, 9, 0, 0, 4.0))  # unmatched, bench
                   + line(event("b2", "2026-10-20T10:06:00.000Z", "claude-sonnet-4-6", 5, 5, 0, 0, 3.0))  # telemetry only, bench
                   + line(event("gone", "2026-10-20T09:00:00.000Z", "claude-sonnet-4-6", 40, 20, 100, 0, 2.0)))
        self.ingest()
        c = otel.cost_check(self.conn, COND, ())
        self.assertEqual(tuple(c["unmatched"]), (0, None))
        self.assertEqual(tuple(c["only"]), (1, 1, 160, 2.0))
        c = otel.cost_check(self.conn, COND, (), since="2026-10-20T00:00:00Z")
        self.assertEqual(tuple(c["unmatched"]), (0, None))

    def test_report_cost_check_follows_the_report_filter(self):
        from tokscope.web.report import write_report
        self.req("a", "2026-10-20T10:00:00.000Z", "claude-sonnet-4-6", 1000, 500, 0, 0)
        self.write(line(event("s1", "2026-10-20T10:00:00.000Z", "claude-sonnet-4-6", 1000, 500, 0, 0, 0.5))
                   + line(event("gone", "2026-10-20T09:00:00.000Z", "claude-sonnet-4-6", 40, 20, 100, 0, 2.0)))
        self.ingest()
        self.conn.commit()
        out = self.tmp / "r.html"
        write_report(self.db, out, tasks_dir=self.tmp)
        self.assertIn('<span class="tag">telemetry only</span>', out.read_text())  # the page script also says it, hence the markup
        write_report(self.db, out, "WHERE s.project = ?", ("-home-u-app",), tasks_dir=self.tmp)
        self.assertNotIn('<span class="tag">telemetry only</span>', out.read_text())

    def test_the_dashboard_cost_check_sits_in_a_data_region_so_live_refresh_swaps_it(self):
        from tokscope.web.dashboard.common import Filters
        from tokscope.web.dashboard.pages import overview
        empty = overview.page_overview(self.conn, Filters({}))
        self.assertIn('<div data-region="cost-check"></div>', empty)  # present before the first ingest, so it can fill in
        self.write(line(event("s9", "2026-10-20T10:00:00.000Z", "claude-opus-5-5", 10, 5, 0, 0, 0.5)))
        self.ingest()
        self.assertRegex(overview.page_overview(self.conn, Filters({})), r'<div data-region="cost-check"><section[^>]*>.*?Cost check')

    def telemetry_db(self):
        """s1 has a transcript and OTel events; "gone" has OTel events only."""
        self.req("a", "2026-10-20T10:00:00.000Z", "claude-sonnet-4-6", 1000, 500, 0, 0)
        self.write(line(event("s1", "2026-10-20T10:00:00.000Z", "claude-sonnet-4-6", 1000, 500, 0, 0, 0.5))
                   + line(event("gone", "2026-10-20T09:00:00.000Z", "claude-sonnet-4-6", 40, 20, 100, 0, 2.0))
                   + line(event("gone", "2026-10-20T09:01:00.000Z", "claude-sonnet-4-6", 40, 20, 100, 0, 1.0)))
        self.ingest()
        self.conn.commit()

    def report(self, level="full", where="", params=()):
        from tokscope.web.report import write_report
        out = self.tmp / "r.html"
        write_report(self.db, out, where, params, tasks_dir=self.tmp, level=level)
        return out.read_text()

    def test_a_telemetry_only_session_is_a_row_and_in_the_totals_once(self):
        from tokscope.web.report.sections.sessions import _sessions_json
        self.telemetry_db()
        got = otel.only_sessions(self.conn)
        self.assertEqual([(s["id"], s["requests"], s["usd"]) for s in got], [("gone", 2, 3.0)])
        self.assertEqual(otel.only_totals(self.conn)["tokens"], 320)
        rows = {s["id"]: s for s in _sessions_json(self.conn, COND, (), got)}
        self.assertEqual(sorted(rows), ["gone", "s1"])
        self.assertTrue(rows["gone"]["only"])
        self.assertIn("No transcript", rows["gone"]["tip"])  # the row's tooltip
        self.assertEqual((rows["gone"]["tokens"], rows["gone"]["usd"], rows["gone"]["turns"]), (320, 3.0, []))
        self.assertNotIn("only", rows["s1"])
        page = self.report()
        self.assertIn('data-count="2" data-kind="int">2<', page)  # Sessions: s1 and gone, each once
        self.assertEqual(page.count('"id":"gone"'), 1)
        cost = cost_usd("claude-sonnet-4-6", 1000, 500, 0, 0, 0)
        self.assertIn(f'data-count="{round(cost + 3.0, 2)}" data-kind="usd"', page)  # API-eq: transcript-priced plus Claude Code's 3.0
        self.assertIn("Includes telemetry-only sessions", page)

    def test_a_session_with_a_transcript_and_events_is_not_added_again(self):
        self.telemetry_db()
        self.assertNotIn("s1", [s["id"] for s in otel.only_sessions(self.conn)])
        cost = cost_usd("claude-sonnet-4-6", 1000, 500, 0, 0, 0)
        self.assertIn(f'data-count="{round(cost + 3.0, 2)}"', self.report())  # not cost + 0.5 + 3.0
        # events that come before the transcript is ingested make it telemetry only; once it has requests they stop counting
        self.conn.execute("DELETE FROM requests")
        self.assertEqual({s["id"] for s in otel.only_sessions(self.conn)}, {"s1", "gone"})

    def test_an_event_without_cost_is_priced_from_its_tokens_and_a_model_with_no_rate_counts_zero(self):
        self.write(line(event("t1", "2026-10-20T09:00:00.000Z", "claude-sonnet-4-6", 1000, 500, 0, 0, None))
                   + line(event("t1", "2026-10-20T09:01:00.000Z", "claude-mystery-9", 10, 10, 0, 0, None)))
        self.ingest()
        (s,) = otel.only_sessions(self.conn)
        self.assertAlmostEqual(s["usd"], cost_usd("claude-sonnet-4-6", 1000, 500, 0, 0, 0))
        self.assertEqual(s["unpriced"], 1)

    def test_a_range_counts_only_the_events_in_it(self):
        self.telemetry_db()
        self.assertEqual(otel.only_totals(self.conn, since="2026-10-20T09:00:30Z")["requests"], 1)
        self.assertEqual(otel.only_totals(self.conn, until="2026-10-20T09:00:30Z")["requests"], 1)
        self.assertEqual(otel.only_totals(self.conn, since="2026-10-21T00:00:00Z")["sessions"], 0)

    def test_a_filtered_report_and_the_dashboard_filters_leave_telemetry_only_sessions_out(self):
        from tokscope.web.dashboard.common import Filters
        from tokscope.web.dashboard.pages import overview, sessions
        self.telemetry_db()
        self.assertNotIn('"id":"gone"', self.report(where="WHERE s.project = ?", params=("-home-u-app",)))
        for qs, shown in (({"range": ["all"]}, True), ({"range": ["all"], "project": ["-home-u-app"]}, False),
                          ({"range": ["all"], "model": ["claude-sonnet-4-6"]}, False)):
            f = Filters(qs)
            self.assertEqual('"id":"gone"' in sessions.page_sessions(self.conn, f, {}), shown, qs)
            self.assertEqual("telemetry only" in overview._kpis(self.conn, f), shown, qs)

    def test_a_redacted_report_lists_the_session_without_any_name(self):
        self.telemetry_db()
        page = self.report("redacted")
        self.assertIn('"id":"gone"', page)
        self.assertIn('"only":true', page)
        self.assertNotIn("-home-u-app", page)

    def test_the_dashboard_counts_the_telemetry_only_session_in_the_tiles_and_the_nav(self):
        from tokscope.web.dashboard import shell
        from tokscope.web.dashboard.common import Filters
        from tokscope.web.dashboard.pages import overview
        self.telemetry_db()
        tiles = overview._kpis(self.conn, Filters({"range": ["all"]}))
        self.assertIn('data-count="2" data-kind="int" data-key="sessions"', tiles)
        self.assertIn("telemetry only", tiles)
        self.assertEqual(shell._nav_counts(self.conn)["sessions"], 2)  # s1 plus gone


if __name__ == "__main__":
    unittest.main()
