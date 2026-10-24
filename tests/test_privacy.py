import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from tokscope.core import privacy
from tokscope.experiments.bench import BENCH_SCHEMA
from tokscope.features.changes import CHANGES_SCHEMA
from tokscope.core.ingest import connect
from tokscope.experiments.replay import REPLAY_SCHEMA
from tokscope.core.skills import SCHEMA as SKILLS_SCHEMA
from tokscope.web.report import write_report

NOW = datetime.now(timezone.utc)
# strings that must never reach a report below "full"; each sits in a different text column
CANARIES = {
    "prompt": "CANARY-PROMPT ask about acme invoices", "title": "CANARY-TITLE secret migration",
    "desc": "CANARY-DESC review the payroll diff", "answer": "CANARY-ANSWER the bug is in invoices.py",
    "note": "CANARY-NOTE switched reviewer model", "cwd": "/home/secretuser/clients/acme-corp",
    "project": "-home-secretuser-clients-acme-corp", "email": "jane.doe@acme.example",
    "about": "CANARY-ABOUT task text", "replay": "CANARY-REPLAY prompt", "sha": "deadbeefcafe1234",
}
NAMES = {"skill": "acme-deploy-skill", "agent": "acme-auditor", "tool": "mcp__claude_ai_AcmeCRM__find_customer"}


def ts(days=0):
    return (NOW - timedelta(days=days)).isoformat()


class PrivacyTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.env = mock.patch.dict(os.environ, {"TOKSCOPE_HOME": str(self.dir / "home")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.db = self.dir / "t.db"
        conn = connect(self.db)
        conn.executescript(BENCH_SCHEMA + REPLAY_SCHEMA + CHANGES_SCHEMA + SKILLS_SCHEMA)
        c = CANARIES
        conn.execute("INSERT INTO sessions (session_id, project, cwd, title, prompts) VALUES (?,?,?,?,1)",
                     ("s-real-0001", c["project"], c["cwd"], c["title"] + " " + c["email"]))
        conn.execute("INSERT INTO sessions (session_id, project, cwd, title, prompts) VALUES ('s-bench-01', "
                     "'-home-u-cc-tokscope-mod-bench-snapshots-s-1', '/x', 'bench run', 1)")
        for sid, key, agent, tokens in (("s-real-0001", "r1", None, 1000), ("s-real-0001", "r2", "a1", 500),
                                        ("s-bench-01", "b1", None, 99999)):
            conn.execute("INSERT INTO requests (session_id, request_key, ts, model, agent_id, agent_type, prompt_idx, skill, "
                         "phase, input, output, thinking, cache_read, cache_write_5m, cache_write_1h, cost_usd) "
                         "VALUES (?,?,?,?,?,?,1,?,?,?,7,0,0,0,0,0.5)",
                         (sid, key, ts(1), "claude-opus-5-5", agent, NAMES["agent"] if agent else None, NAMES["skill"],
                          "other:" + NAMES["skill"], tokens))
        conn.execute("INSERT INTO prompts VALUES ('s-real-0001', 1, ?, ?)", (ts(1), c["prompt"] + " " + c["email"]))
        conn.execute("INSERT INTO subagents (session_id, agent_id, agent_type, description, prompt_idx) VALUES "
                     "('s-real-0001', 'a1', ?, ?, 1)", (NAMES["agent"], c["desc"]))
        conn.execute("INSERT INTO tool_calls (session_id, tool_use_id, prompt_idx, agent_id, name, result_chars) VALUES ('s-real-0001', 't1', 1, NULL, ?, 400)", (NAMES["tool"],))
        conn.execute("INSERT INTO tool_calls (session_id, tool_use_id, prompt_idx, agent_id, name, result_chars) VALUES ('s-real-0001', 't2', 1, NULL, 'Read', 800)")
        conn.execute("INSERT INTO skill_calls (session_id, ts, skill, phase, source, agent_id, prompt_idx) "
                     "VALUES ('s-real-0001', ?, ?, ?, 'user', NULL, 1)",
                     (ts(1), NAMES["skill"], "other:" + NAMES["skill"]))
        conn.execute("INSERT INTO bench_runs (run_id, task, variant, run_idx, session_id, started_at, duration_s, exit_code, "
                     "is_error, reported_cost, passed, result, commit_sha) VALUES ('b', 'acme-task', 'v1', 0, 's-bench-01', ?, "
                     "1, 0, 0, 0, 1, ?, ?)", (ts(1), c["answer"], c["sha"]))
        conn.execute("INSERT INTO replay_turns (run_id, turn, prompt, result) VALUES ('rp', 0, ?, ?)", (c["replay"], c["answer"]))
        conn.execute("INSERT INTO changes (at, note, skill) VALUES (?, ?, ?)", (ts(2), c["note"], NAMES["skill"]))
        conn.commit()
        conn.close()  # checkpoints the WAL now; left open, whichever connection closed last would rewrite the file mid-test
        self.tasks = self.dir / "tasks"
        self.tasks.mkdir()
        (self.tasks / "acme-task.json").write_text(json.dumps({"about": c["about"], "grader": {"all": ["billing"]}}))

    def report(self, level, **kw):
        out = self.dir / f"{level}.html"
        write_report(self.db, out, tasks_dir=self.tasks, level=level, **kw)
        return out.read_text()

    def test_the_full_report_holds_the_canaries_so_the_scan_below_can_fail(self):
        page = self.report("full")
        for name in ("prompt", "title", "desc", "answer", "email", "about"):
            self.assertIn(CANARIES[name], page, name)

    def test_redacted_and_numbers_reports_hold_no_private_text(self):
        for level in ("redacted", "numbers"):
            page = self.report(level)
            for name, text in CANARIES.items():
                self.assertNotIn(text, page, f"{level}: {name}")
            for word in ("secretuser", "acme-corp", "acme.example"):
                self.assertNotIn(word, page, f"{level}: {word}")
            self.assertIn('"text":"[prompt \\u00b7 ', page)  # the session data is JSON, so · is escaped

    def test_names_survive_redacted_but_become_aliases_in_numbers(self):
        redacted, numbers = self.report("redacted"), self.report("numbers")
        self.assertIn(NAMES["skill"], redacted)
        self.assertIn(NAMES["agent"], redacted)
        for name in NAMES.values():
            self.assertNotIn(name, numbers)
        self.assertNotIn("AcmeCRM", numbers)
        self.assertNotIn("acme-task", numbers)
        self.assertIn("Read", numbers)  # built-in tool names say nothing about the user's work

    def test_numbers_are_the_same_at_every_level(self):
        for level in ("redacted", "numbers"):
            self.assertIn("1.5K", self.report(level))  # 1,000 + 500 real tokens; the bench session stays out

    def test_benchmark_sessions_stay_out_of_real_usage_after_aliasing(self):
        self.assertNotIn("101.5K", self.report("numbers"))

    def test_a_project_filter_matches_real_names_before_they_are_replaced(self):
        kept = self.report("redacted", where="WHERE s.project LIKE ?", params=("%acme-corp%",))
        gone = self.report("redacted", where="WHERE s.project LIKE ?", params=("%other-client%",))
        self.assertIn("1.5K", kept)
        self.assertNotIn("1.5K", gone)

    def test_an_alias_is_stable_on_one_machine_and_differs_on_another(self):
        a, b = privacy.Redactor("numbers", key=b"k1", phase_names=set()), privacy.Redactor("numbers", key=b"k1", phase_names=set())
        other = privacy.Redactor("numbers", key=b"k2", phase_names=set())
        self.assertEqual(a.name("skill", "x"), b.name("skill", "x"))
        self.assertNotEqual(a.name("skill", "x"), other.name("skill", "x"))
        self.assertEqual(a.name("agent", "Explore"), "Explore")
        self.assertEqual(a.name("phase", "other:x"), "other:" + a.name("skill", "x"))

    def test_the_key_file_is_private_to_the_user(self):
        self.report("numbers")
        self.assertEqual((self.dir / "home" / "privacy.key").stat().st_mode & 0o777, 0o600)

    def test_every_column_of_every_table_is_classified(self):
        conn = sqlite3.connect(self.db)
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            self.assertIn(table, privacy.COLUMNS, table)
            for col in (r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')):
                self.assertIn(col, privacy.COLUMNS[table], f"{table}.{col} is not classified in privacy.COLUMNS")

    def test_an_unknown_column_is_emptied_and_an_unknown_table_cleared(self):
        conn = sqlite3.connect(self.db)
        conn.execute("ALTER TABLE sessions ADD COLUMN new_text TEXT")
        conn.execute("UPDATE sessions SET new_text = 'CANARY-NEW'")
        conn.execute("CREATE TABLE notes (body TEXT)")
        conn.execute("INSERT INTO notes VALUES ('CANARY-TABLE')")
        conn.commit()
        copy = privacy.redacted_copy(self.db, "redacted")
        self.assertEqual(copy.execute("SELECT count(*) FROM sessions WHERE new_text IS NOT NULL").fetchone()[0], 0)
        self.assertEqual(copy.execute("SELECT count(*) FROM notes").fetchone()[0], 0)

    def test_a_copy_has_rows_still_in_the_wal(self):
        conn = connect(self.db)
        conn.execute("INSERT INTO sessions (session_id) VALUES ('latest-wal-row')")
        conn.commit()  # not checkpointed: the row is in the -wal file while conn is open
        copy = privacy.redacted_copy(self.db, "numbers")
        self.assertEqual(copy.execute("SELECT count(*) FROM sessions").fetchone()[0],
                         conn.execute("SELECT count(*) FROM sessions").fetchone()[0])
        conn.close()

    def test_the_database_on_disk_is_never_changed(self):
        before = self.db.read_bytes()
        self.report("numbers")
        self.assertEqual(self.db.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
