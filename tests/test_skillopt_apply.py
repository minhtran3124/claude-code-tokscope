import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tokscope import paths
from tokscope.core import ingest, skills
from tokscope.experiments.skillopt import apply, stats, store


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


def put(folder, files):
    for rel, text in files.items():
        p = Path(folder) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


class ApplyBase(unittest.TestCase):
    OLD = {"SKILL.md": "---\nname: demo\ndescription: d\n---\nold body\n", "ref/notes.md": "notes\n"}
    NEW = {"SKILL.md": "---\nname: demo\ndescription: d\n---\nnew body\n", "ref/extra.md": "extra\n"}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        p = mock.patch.dict(os.environ, {"TOKSCOPE_HOME": str(self.tmp / "data"), "HOME": str(self.tmp / "home"),
                                         "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                                         "GIT_COMMITTER_EMAIL": "t@t"})
        p.start()
        self.addCleanup(p.stop)
        self.skill = self.tmp / "work" / "demo"
        put(self.skill, self.OLD)
        put(self.skill, {"evals/evals.json": '{"evals": []}\n'})

    def seed(self, verdict="Apply", draft=NEW, reason="every gate passed"):
        run = store.new_run("demo")
        base = skills.fingerprint(self.skill)
        put(run / "versions" / "v0", self.OLD)
        put(run / "versions" / "v1", draft)
        store.write_plan(run, {"schema": 1, "skill": "demo", "run_id": run.name, "base_fingerprint": base,
                               "source": str(self.skill), "suite_hash": "x", "budget_usd": 1.0, "per_run_cap_usd": 1.0})
        (run / "verdict.json").write_text(json.dumps({
            "verdict": verdict, "reason": reason, "draft_version": "v1",
            "draft_fingerprint": skills.fingerprint(run / "versions" / "v1"), "base_fingerprint": base,
            "run_id": run.name, "skill": "demo"}))
        self.base = base
        return run

    def git_init(self):
        repo = self.tmp / "work"
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "init")
        return repo

    def changes(self):
        conn = ingest.connect(paths.db())
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS changes (id INTEGER PRIMARY KEY, at TEXT, note TEXT, agent_type TEXT, skill TEXT)")
            return conn.execute("SELECT note, skill FROM changes").fetchall()
        finally:
            conn.close()


class ApproveOutsideGit(ApplyBase):
    def test_replaces_files_keeps_evals_and_snapshot_then_reverts(self):
        run = self.seed()
        want = json.loads((run / "verdict.json").read_text())["draft_fingerprint"]
        res = apply.approve(run.name)
        self.assertEqual(skills.fingerprint(self.skill), want)  # AC1
        self.assertEqual((self.skill / "evals" / "evals.json").read_text(), '{"evals": []}\n')
        self.assertFalse((self.skill / "ref" / "notes.md").exists())
        self.assertEqual((self.skill / "ref" / "extra.md").read_text(), "extra\n")
        self.assertIsNone(res["commit"])  # AC3: no commit outside git
        self.assertTrue((paths.home() / "data" / "skills" / "demo" / self.base).is_dir())
        d = json.loads((run / "decision.json").read_text())
        self.assertEqual((d["decision"], d["old_fingerprint"], d["new_fingerprint"]), ("approved", self.base, want))
        self.assertEqual(json.loads((run / "apply.json").read_text())["state"], "done")
        self.assertEqual(self.changes(), [("Optimize applied", "demo")])  # AC7
        conn = ingest.connect(paths.db())
        self.assertEqual([r[0] for r in conn.execute("SELECT kind FROM opt_applied")], ["approve"])
        conn.close()
        apply.revert(run.name)
        self.assertEqual(skills.fingerprint(self.skill), self.base)
        self.assertTrue((self.skill / "ref" / "notes.md").exists())
        self.assertFalse((self.skill / "ref" / "extra.md").exists())
        self.assertIn("reverted", json.loads((run / "decision.json").read_text()))
        with self.assertRaises(apply.Refused):
            apply.revert(run.name)

    def test_refusals_leave_the_skill_alone(self):  # AC4
        run = self.seed()
        put(self.skill, {"SKILL.md": "---\nname: demo\ndescription: d\n---\nedited after the run\n"})
        before = skills.fingerprint(self.skill)
        with self.assertRaisesRegex(apply.Refused, "changed after this run"):
            apply.approve(run.name)
        self.assertEqual(skills.fingerprint(self.skill), before)

    def test_draft_changed_after_confirm(self):
        run = self.seed()
        put(run / "versions" / "v1", {"SKILL.md": "tampered\n"})
        with self.assertRaisesRegex(apply.Refused, "draft v1 changed"):
            apply.approve(run.name)
        self.assertEqual(skills.fingerprint(self.skill), self.base)

    def test_reject_verdict_and_not_enough_evidence(self):
        run = self.seed(verdict=stats.REJECT)
        with self.assertRaisesRegex(apply.Refused, "Reject"):
            apply.approve(run.name)
        run = self.seed(verdict=stats.NOT_ENOUGH)
        with self.assertRaisesRegex(apply.Refused, "--reason"):
            apply.approve(run.name)
        self.assertEqual(skills.fingerprint(self.skill), self.base)
        apply.approve(run.name, "I read the diff")
        d = json.loads((run / "decision.json").read_text())
        self.assertEqual(d["reason"], "I read the diff")

    def test_reject_is_always_recorded(self):
        run = self.seed(verdict=stats.REJECT)
        res = apply.reject(run.name)
        self.assertEqual(res["decision"], "rejected")
        self.assertEqual(json.loads((run / "decision.json").read_text())["decision"], "rejected")
        self.assertEqual(skills.fingerprint(self.skill), self.base)

    def test_changes_row_failure_does_not_fail_the_approve(self):  # AC7
        run = self.seed()
        with mock.patch("tokscope.features.changes.add_change", side_effect=sqlite3.OperationalError("locked")):
            res = apply.approve(run.name)
        self.assertIn("locked", res["change_error"])
        self.assertEqual(json.loads((run / "decision.json").read_text())["decision"], "approved")

    def test_fingerprint_mismatch_after_write_restores(self):  # AC5
        run = self.seed()
        real = apply._replace

        def bad(folder, src):
            out = real(folder, src)
            if Path(src) == run / "versions" / "v1":
                (Path(folder) / "ref" / "extra.md").write_text("drift\n")
            return out

        with mock.patch.object(apply, "_replace", bad):
            with self.assertRaisesRegex(apply.Refused, "restored"):
                apply.approve(run.name)
        self.assertEqual(skills.fingerprint(self.skill), self.base)

    def test_interrupted_apply_is_rolled_back_or_finished(self):  # AC6
        run = self.seed()
        real = apply._complete
        with mock.patch.object(apply, "_complete", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                apply.approve(run.name)
        self.assertEqual(json.loads((run / "apply.json").read_text())["state"], "writing")
        new = skills.fingerprint(self.skill)
        self.assertNotEqual(new, self.base)
        with mock.patch.object(apply, "_complete", real):
            msg = apply.recover(run)  # files were whole: finish
        self.assertIn("finished", msg)
        self.assertEqual((json.loads((run / "decision.json").read_text()))["decision"], "approved")
        # a stop in the middle of the copy: the skill is neither version
        apply.revert(run.name)  # back to the old version
        run2 = self.seed()

        def half(folder, src):
            (Path(folder) / "SKILL.md").write_text("half written\n")
            raise KeyboardInterrupt

        with mock.patch.object(apply, "_replace", half):
            with self.assertRaises(KeyboardInterrupt):
                apply.approve(run2.name)
        self.assertNotEqual(skills.fingerprint(self.skill), self.base)
        self.assertIn("rolled back", apply.recover(run2))
        self.assertEqual(skills.fingerprint(self.skill), self.base)


class ApproveInGit(ApplyBase):
    def test_one_commit_with_only_the_skill_files(self):  # AC2
        repo = self.git_init()
        put(repo, {"other.txt": "x\n"})
        git(repo, "add", "other.txt")  # staged before: stays staged
        run = self.seed()
        res = apply.approve(run.name)
        self.assertEqual(git(repo, "rev-list", "--count", "HEAD"), "2")
        self.assertEqual(git(repo, "rev-parse", "HEAD"), res["commit"])
        files = set(git(repo, "show", "--name-only", "--format=", "HEAD").splitlines())
        self.assertEqual(files, {"demo/SKILL.md", "demo/ref/notes.md", "demo/ref/extra.md"})
        self.assertEqual(git(repo, "diff", "--cached", "--name-only"), "other.txt")
        self.assertEqual(git(repo, "branch", "--show-current"), "main")
        self.assertRegex(git(repo, "log", "-1", "--format=%s"), r"^optimize\(demo\): [0-9a-f]{12} → [0-9a-f]{12}$")
        self.assertIn(run.name, git(repo, "log", "-1", "--format=%b"))
        apply.revert(run.name)
        self.assertEqual(git(repo, "rev-list", "--count", "HEAD"), "3")
        self.assertEqual(skills.fingerprint(self.skill), self.base)

    def test_detached_head_is_refused(self):  # AC4
        repo = self.git_init()
        git(repo, "checkout", "-q", "--detach")
        run = self.seed()
        with self.assertRaisesRegex(apply.Refused, "detached"):
            apply.approve(run.name)
        self.assertEqual(skills.fingerprint(self.skill), self.base)
        self.assertEqual(git(repo, "rev-list", "--count", "HEAD"), "1")

    def test_failing_pre_commit_hook_restores_the_skill(self):  # AC5
        repo = self.git_init()
        hook = repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        run = self.seed()
        with self.assertRaisesRegex(apply.Refused, "git commit failed"):
            apply.approve(run.name)
        self.assertEqual(skills.fingerprint(self.skill), self.base)
        self.assertEqual(git(repo, "rev-list", "--count", "HEAD"), "1")
        self.assertEqual(git(repo, "status", "--porcelain", "--", "demo"), "")


if __name__ == "__main__":
    unittest.main()
