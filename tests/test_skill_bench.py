import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tokscope.core import skills
from tokscope.experiments import bench
from tokscope.core.ingest import connect


def write(folder, text):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(text)
    return folder


class SkillBenchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        env = mock.patch.dict(os.environ, {"HOME": str(self.tmp / "home"), "TOKSCOPE_HOME": str(self.tmp / "data-home")})
        env.start()
        self.addCleanup(env.stop)
        self.conn = connect(self.tmp / "t.db")
        src = write(self.tmp / "repo" / ".claude" / "skills" / "review", "# v1\nRead every file.\n")
        self.v1 = skills.record(self.conn, "review", src, "2026-10-01T00:00:00+00:00", "scan")
        (src / "SKILL.md").write_text("# v2\nRead only the diff.\n")
        self.v2 = skills.record(self.conn, "review", src, "2026-10-10T00:00:00+00:00", "scan")

    def test_a_version_is_found_by_a_hash_prefix_and_a_wrong_one_names_the_kept(self):
        self.assertEqual(skills.resolve_version("review", self.v1[:5]), self.v1)
        with self.assertRaisesRegex(ValueError, f"no kept version matches 'zzz'.*{self.v1}"):
            skills.resolve_version("review", "zzz")

    def test_a_personal_copy_or_a_plugin_skill_cannot_be_pinned(self):
        with self.assertRaisesRegex(ValueError, "cannot be pinned yet"):
            skills.check_pinnable("ce:review")
        write(self.tmp / "home" / ".claude" / "skills" / "review", "# personal")
        with self.assertRaisesRegex(ValueError, "wins over a pinned project copy"):
            skills.check_pinnable("review")

    def test_each_variant_gets_its_own_pinned_copy_and_the_shared_snapshot_is_untouched(self):
        snapshot = self.tmp / "bench" / "snapshots" / "s-abc"
        write(snapshot / ".claude" / "skills" / "review", "# repo copy at the task's commit\n")
        (snapshot / "app.py").write_text("code")
        d1, d2 = bench.version_dir(snapshot, "review", self.v1), bench.version_dir(snapshot, "review", self.v2)
        self.assertEqual((d1 / ".claude/skills/review/SKILL.md").read_text(), "# v1\nRead every file.\n")
        self.assertEqual((d2 / ".claude/skills/review/SKILL.md").read_text(), "# v2\nRead only the diff.\n")
        self.assertEqual((snapshot / ".claude/skills/review/SKILL.md").read_text(), "# repo copy at the task's commit\n")
        self.assertEqual((d1 / "app.py").stat().st_ino, (snapshot / "app.py").stat().st_ino)  # linked, not copied

    def load(self, session, text_hash):
        self.conn.execute("INSERT INTO skill_calls (session_id, ts, skill, source, prompt_idx, tool_use_id, text_hash) "
                          "VALUES (?, '2026-10-20', 'review', 'command', 1, NULL, ?)", (session, text_hash))

    def test_a_run_is_checked_against_the_text_the_model_read(self):
        b1, b2 = skills.body_hash(skills.snapshot_dir("review", self.v1)), skills.body_hash(skills.snapshot_dir("review", self.v2))
        self.load("ran-v1", f"aaa {b1}")
        self.load("ran-v2-instead", b2)
        self.load("no-text", None)
        got = [skills.check_load(self.conn, s, "review", self.v1) for s in ("ran-v1", "ran-v2-instead", "no-text", "never")]
        self.assertEqual(got, ["ok", "other text", "unconfirmed", "not loaded"])

    def test_a_failed_load_is_not_a_load_for_the_check(self):
        self.conn.execute("INSERT INTO skill_calls (session_id, ts, skill, source, prompt_idx, tool_use_id, failed) "
                          "VALUES ('only-failed', '2026-10-20', 'review', 'tool', 1, 't1', 1)")
        self.assertEqual(skills.check_load(self.conn, "only-failed", "review", self.v1), "not loaded")

    def test_a_skill_benchmark_runs_each_version_interleaved_in_its_own_folder_and_records_the_check(self):
        task = {"name": "t", "repo": "r", "commit": "c", "paths": [], "prompt": "/review {version}", "grader": {}}
        snapshot = self.tmp / "bench" / "snapshots" / "s-abc"
        snapshot.mkdir(parents=True)
        seen = []

        def fake_run(task, variant, run_idx, cwd, sha):
            seen.append((variant, Path(cwd).name, (Path(cwd) / ".claude/skills/review/SKILL.md").read_text().splitlines()[0],
                         task["prompt"].format(version=variant)))
            sid = f"{variant}-{run_idx}"
            self.load(sid, skills.body_hash(Path(cwd) / ".claude/skills/review"))
            self.conn.commit()
            return {"run_id": sid, "task": "t", "variant": variant, "run_idx": run_idx, "session_id": sid, "passed": 1,
                    "is_error": 0, "reported_cost": 0.1, "duration_s": 1, "result": "", "commit_sha": sha}

        with mock.patch.object(bench, "prepare", return_value=(snapshot, "sha")), \
                mock.patch.object(bench, "run_one", fake_run), mock.patch.object(bench, "ingest_session"):
            bench.run(self.tmp, self.tmp / "t.db", None, task, 2, skill="review", versions=[self.v1[:6], self.v2[:6]], log=lambda *_: None)
        r1, r2 = (self.v1, f"s-abc-{self.v1[:8]}", "# v1"), (self.v2, f"s-abc-{self.v2[:8]}", "# v2")
        self.assertEqual([s[:3] for s in seen], [r1, r2, r2, r1])
        rows = connect(self.tmp / "t.db").execute("SELECT variant, skill_check FROM bench_runs ORDER BY run_id").fetchall()
        self.assertEqual(sorted(rows), sorted([(self.v1, "ok"), (self.v1, "ok"), (self.v2, "ok"), (self.v2, "ok")]))
        self.assertIn("skill: ok 2", bench.diff(self.tmp / "t.db", "t"))


    def test_an_inline_argument_is_put_back_but_an_appended_one_is_cut(self):
        head = "Base directory for this skill: /x\n\n"
        self.assertEqual(skills._kept_body(head + "Research `ENG-1 creds` now.", "ENG-1 creds"), "Research `$ARGUMENTS` now.")
        # appended: the word 'update' in the body stays a word
        self.assertEqual(skills._kept_body(head + "Run update.\n\n\nARGUMENTS: update", "update"), "Run update.")

    def test_an_older_text_a_transcript_kept_becomes_a_version_and_its_loads_take_it(self):
        projects = self.tmp / "projects"
        old_text = "Base directory for this skill: /x\n\n# v0\nResearch `ENG-9 pool` first."
        lines = [{"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t0", "name": "Skill",
                                                                "input": {"skill": "review", "args": "ENG-9 pool"}}]}},
                 {"type": "api-request-blob", "message": {"content": [
                     {"type": "tool_result", "tool_use_id": "t0", "content": "Launching skill: review"},
                     {"type": "text", "text": old_text}]}}]
        (projects / "p").mkdir(parents=True)
        (projects / "p" / "s0.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
        self.conn.execute("INSERT INTO sessions (session_id, project) VALUES ('s0', 'p')")
        self.conn.execute("INSERT INTO skill_calls (session_id, ts, skill, source, prompt_idx, tool_use_id, text_hash) "
                          "VALUES ('s0', '2026-09-28T10:00:00Z', 'review', 'tool', 1, 't0', ?)",
                          (skills.loaded_text_hash(old_text, "ENG-9 pool"),))
        self.load("later-without-text", None)
        self.conn.commit()
        (sk, version, first, n), = skills.import_from_transcripts(self.conn, projects)
        self.assertEqual((sk, first, n), ("review", "2026-09-28T10:00:00Z", 1))
        kept = (skills.snapshot_dir("review", version) / "SKILL.md").read_text()
        self.assertIn("Research `$ARGUMENTS` first.", kept)
        got = {sid: v for sid, _, _, _, v, _ in skills.load_versions(self.conn)}
        self.assertEqual(got["s0"], version)
        self.assertNotEqual(got["later-without-text"], version)   # known only where its text was kept
        self.assertEqual(skills.import_from_transcripts(self.conn, projects), [])   # nothing new the second time


    def test_an_older_text_of_a_typed_command_is_imported_too(self):
        projects = self.tmp / "projects"
        cmd = "<command-name>/review</command-name>\n<command-args>PR 7</command-args>"
        text = "Base directory for this skill: /x\n\n# v0 typed\nReview PR 7 now."
        lines = [{"type": "user", "timestamp": "2026-09-29T08:00:00Z", "message": {"role": "user", "content": cmd}},
                 {"type": "user", "isMeta": True, "message": {"role": "user", "content": [{"type": "text", "text": text}]}}]
        (projects / "p").mkdir(parents=True)
        (projects / "p" / "s7.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
        self.conn.execute("INSERT INTO sessions (session_id, project) VALUES ('s7', 'p')")
        self.conn.execute("INSERT INTO skill_calls (session_id, ts, skill, source, prompt_idx, text_hash) "
                          "VALUES ('s7', '2026-09-29T08:00:00Z', 'review', 'command', 1, ?)", (skills.loaded_text_hash(text, "PR 7"),))
        self.conn.commit()
        (_, version, first, n), = skills.import_from_transcripts(self.conn, projects)
        self.assertIn("Review $ARGUMENTS now.", (skills.snapshot_dir("review", version) / "SKILL.md").read_text())


if __name__ == "__main__":
    unittest.main()
