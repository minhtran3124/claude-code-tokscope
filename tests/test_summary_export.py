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
from tokscope.core import summary
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
