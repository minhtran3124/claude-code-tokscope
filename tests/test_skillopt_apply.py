import contextlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tokscope import cli, paths
from tokscope.core import ingest, skills
from tokscope.experiments.skillopt import apply, stats, store

RUN = "demo-20260101T000000Z"


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        env = {"TOKSCOPE_HOME": str(self.tmp / "tok"), "HOME": str(self.tmp / "h"), "GIT_CONFIG_GLOBAL": "/dev/null",
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        self.cwd = self.tmp / "proj"
        self.cwd.mkdir()
        self.root = self.tmp / "h" / ".claude" / "skills"
        self.folder = self.root / "demo"
        (self.folder / "refs").mkdir(parents=True)
        (self.folder / "evals").mkdir()
        (self.folder / "SKILL.md").write_text("---\nname: demo\n---\nold body\n")
        (self.folder / "refs" / "a.md").write_text("a\n")
        (self.folder / "evals" / "evals.json").write_text('{"keep": true}\n')
        self.old = skills.fingerprint(self.folder)
        self.run_dir = store.runs_dir() / RUN
        draft = self.run_dir / "versions" / "v1"
        (draft / "refs").mkdir(parents=True)
        (draft / "SKILL.md").write_text("---\nname: demo\n---\nnew body\n")
        (draft / "refs" / "b.md").write_text("b\n")
        self.new = skills.fingerprint(draft)
        (self.run_dir / "plan.json").write_text(json.dumps({"skill": "demo", "base_fingerprint": self.old}))
        self.set_verdict()

    def set_verdict(self, verdict=stats.APPLY, **kw):
        v = {"verdict": verdict, "reason": "r", "draft_version": "v1", "draft_fingerprint": self.new,
             "base_fingerprint": self.old, "run_id": RUN, "skill": "demo", **kw}
        (self.run_dir / "verdict.json").write_text(json.dumps(v))

    def approve(self, **kw):
        return apply.approve(RUN, cwd=str(self.cwd), **kw)

    def fp(self):
        return skills.fingerprint(self.folder)

    def rows(self, sql):
        conn = ingest.connect(paths.db())
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()

    def git_repo(self):
        sh(self.root, "git", "init", "-q", "-b", "main")
        sh(self.root, "git", "add", "-A")
        sh(self.root, "git", "commit", "-q", "-m", "init")


class TestApprove(Base):
    def test_install_matches_measured_fingerprint_and_keeps_evals(self):
        rec = self.approve()
        self.assertEqual(self.fp(), self.new)
        self.assertEqual(rec["decision"], "approve")
        self.assertEqual((self.folder / "evals" / "evals.json").read_text(), '{"keep": true}\n')
        self.assertFalse((self.folder / "refs" / "a.md").exists())
        self.assertEqual((self.folder / "refs" / "b.md").read_text(), "b\n")

    def test_uncovered_files_survive(self):
        (self.folder / ".hidden").write_text("h")
        (self.folder / "big.bin").write_bytes(b"x" * (skills.MAX_BYTES + 1))
        self.approve()
        self.assertTrue((self.folder / ".hidden").exists())
        self.assertTrue((self.folder / "big.bin").exists())
        self.assertEqual(self.fp(), self.new)

    def test_refusals_leave_the_skill_alone(self):
        def refused(msg):
            with self.assertRaisesRegex(apply.Refused, msg):
                self.approve()
            self.assertEqual(self.fp(), self.old)
            self.assertFalse((self.run_dir / apply.APPLY_JSON).exists())
        self.set_verdict(stats.REJECT)
        refused("Reject")
        self.set_verdict(stats.NOT_ENOUGH)
        refused("--reason")
        self.set_verdict(draft_version=None, draft_fingerprint=None)
        refused("no draft")
        self.set_verdict()
        (self.run_dir / "versions" / "v1" / "SKILL.md").write_text("tampered\n")
        refused("draft")
        (self.run_dir / "versions" / "v1" / "SKILL.md").write_text("---\nname: demo\n---\nnew body\n")
        (self.folder / "SKILL.md").write_text("edited by hand\n")
        self.old = self.fp()
        with self.assertRaisesRegex(apply.Refused, "edited after the run"):
            self.approve()
        self.assertEqual(self.fp(), self.old)

    def test_not_enough_evidence_with_reason(self):
        self.set_verdict(stats.NOT_ENOUGH)
        rec = self.approve(reason="owner reviewed the diff")
        self.assertEqual(rec["reason"], "owner reviewed the diff")
        self.assertEqual(self.fp(), self.new)

    def test_post_write_mismatch_restores(self):
        real = apply._replace

        def corrupt(folder, src):
            real(folder, src)
            if Path(src).name == "v1":
                (Path(folder) / "SKILL.md").write_bytes(b"corrupt")
        with mock.patch.object(apply, "_replace", corrupt):
            with self.assertRaisesRegex(apply.Refused, "do not match"):
                self.approve()
        self.assertEqual(self.fp(), self.old)
        self.assertFalse((self.run_dir / apply.APPLY_JSON).exists())

    def test_second_approve_says_already_approved(self):
        self.approve()
        with self.assertRaisesRegex(apply.Refused, "already approved"):
            self.approve()

    def test_run_lock_refuses(self):
        store.acquire(self.run_dir)
        self.addCleanup(store.release, self.run_dir)
        # same pid may re-take it; a foreign live pid is what refuses
        (self.run_dir / store.LOCK).write_text(str(os.getppid()))
        with self.assertRaises(ValueError):
            self.approve()
        self.assertEqual(self.fp(), self.old)


class TestGit(Base):
    def setUp(self):
        super().setUp()
        self.git_repo()

    def test_one_commit_with_only_skill_files(self):
        (self.root / "other.txt").write_text("x")
        sh(self.root, "git", "add", "other.txt")
        before = sh(self.root, "git", "rev-list", "--count", "HEAD")
        rec = self.approve()
        self.assertEqual(int(sh(self.root, "git", "rev-list", "--count", "HEAD")), int(before) + 1)
        files = sh(self.root, "git", "show", "--name-only", "--format=", "HEAD").splitlines()
        self.assertEqual(sorted(files), ["demo/SKILL.md", "demo/refs/a.md", "demo/refs/b.md"])
        self.assertIn("other.txt", sh(self.root, "git", "diff", "--cached", "--name-only"))
        self.assertEqual(rec["commit_sha"], sh(self.root, "git", "rev-parse", "HEAD"))
        self.assertIn(RUN, sh(self.root, "git", "log", "-1", "--format=%B"))

    def test_failing_hook_restores(self):
        hook = self.root / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho no >&2\nexit 1\n")
        hook.chmod(0o755)
        head = sh(self.root, "git", "rev-parse", "HEAD")
        with self.assertRaisesRegex(apply.Refused, "git commit failed"):
            self.approve()
        self.assertEqual(self.fp(), self.old)
        self.assertEqual(sh(self.root, "git", "rev-parse", "HEAD"), head)
        self.assertEqual(sh(self.root, "git", "status", "--porcelain", "--", "demo"), "")

    def test_detached_head_refuses(self):
        sh(self.root, "git", "checkout", "-q", "--detach")
        with self.assertRaisesRegex(apply.Refused, "detached"):
            self.approve()
        self.assertEqual(self.fp(), self.old)

    def test_non_git_has_no_commit(self):
        shutil.rmtree(self.root / ".git")
        self.assertIsNone(self.approve()["commit_sha"])


class TestRecords(Base):
    def test_rows_and_decision(self):
        rec = self.approve()
        self.assertEqual(len(self.rows("SELECT * FROM changes WHERE skill='demo'")), 1)
        op = self.rows("SELECT action, old_version, new_version FROM opt_applied")
        self.assertEqual(op, [("approve", self.old, self.new)])
        d = json.loads((self.run_dir / apply.DECISION_JSON).read_text())
        for k in ("decision", "run_id", "skill", "verdict", "old_fingerprint", "new_fingerprint", "commit_sha", "at", "history"):
            self.assertIn(k, d)
        self.assertFalse((self.run_dir / apply.APPLY_JSON).exists())
        self.assertTrue(skills.snapshot_dir("demo", self.old).is_dir())
        self.assertEqual(rec["new_fingerprint"], self.new)

    def test_change_error_does_not_undo(self):
        with mock.patch("tokscope.features.changes.add_change", side_effect=sqlite3.OperationalError("locked")):
            self.approve()
        d = json.loads((self.run_dir / apply.DECISION_JSON).read_text())
        self.assertIn("locked", d["change_error"])
        self.assertEqual(self.fp(), self.new)


class TestRecover(Base):
    def interrupt(self, name):
        return mock.patch.object(apply, name, side_effect=KeyboardInterrupt)

    def test_writing_phase_rolls_back(self):
        real = apply._replace

        def half(folder, src):
            if Path(src).name == "v1":
                (Path(folder) / "SKILL.md").write_text("half\n")
                raise KeyboardInterrupt
            real(folder, src)
        with mock.patch.object(apply, "_replace", half), self.assertRaises(KeyboardInterrupt):
            self.approve()
        self.assertNotEqual(self.fp(), self.old)
        self.assertTrue((self.run_dir / apply.APPLY_JSON).exists())
        apply.reject(RUN, cwd=str(self.cwd))
        self.assertEqual(self.fp(), self.old)
        self.assertFalse((self.run_dir / apply.APPLY_JSON).exists())

    def test_written_phase_without_commit_rolls_back(self):
        self.git_repo()
        with self.interrupt("_commit"), self.assertRaises(KeyboardInterrupt):
            self.approve()
        self.assertEqual(self.fp(), self.new)
        apply.reject(RUN, cwd=str(self.cwd))
        self.assertEqual(self.fp(), self.old)

    def test_committed_phase_completes(self):
        self.git_repo()
        with self.interrupt("_finish"), self.assertRaises(KeyboardInterrupt):
            self.approve()
        self.assertEqual(json.loads((self.run_dir / apply.APPLY_JSON).read_text())["phase"], "committed")
        self.assertEqual(apply.reject(RUN, cwd=str(self.cwd))["decision"], "reject")
        self.assertEqual(self.fp(), self.new)
        self.assertEqual(len(self.rows("SELECT * FROM changes WHERE skill='demo'")), 1)
        self.assertEqual(len(self.rows("SELECT * FROM opt_applied")), 1)
        d = json.loads((self.run_dir / apply.DECISION_JSON).read_text())
        self.assertEqual([d["decision"], d["history"][-1]["decision"]], ["reject", "approve"])

    def test_committed_phase_without_a_commit_completes(self):
        with self.interrupt("_finish"), self.assertRaises(KeyboardInterrupt):
            self.approve()  # skill is not in git: no commit, phase committed
        state = json.loads((self.run_dir / apply.APPLY_JSON).read_text())
        self.assertEqual((state["phase"], state.get("commit_sha")), ("committed", None))
        apply.recover(log=lambda m: None)
        self.assertEqual(self.fp(), self.new)
        self.assertEqual(len(self.rows("SELECT * FROM opt_applied")), 1)
        self.assertFalse((self.run_dir / apply.APPLY_JSON).exists())

    def test_commit_made_but_phase_still_written(self):
        self.git_repo()
        with self.interrupt("_finish"), self.assertRaises(KeyboardInterrupt):
            self.approve()
        f = self.run_dir / apply.APPLY_JSON
        state = json.loads(f.read_text())
        state.update(phase="written", commit_sha=None)
        f.write_text(json.dumps(state))
        apply.recover(log=lambda m: None)
        self.assertEqual(self.fp(), self.new)
        self.assertEqual(json.loads((self.run_dir / apply.DECISION_JSON).read_text())["decision"], "approve")

    def test_unrestorable_snapshot_refuses_every_command(self):
        with self.interrupt("_commit"), self.assertRaises(KeyboardInterrupt):
            self.approve()
        shutil.rmtree(skills.snapshot_dir("demo", self.old))
        for call in (lambda: apply.reject(RUN), lambda: self.approve(), lambda: apply.revert(RUN)):
            with self.assertRaisesRegex(apply.Refused, "snapshot"):
                call()
        self.assertTrue((self.run_dir / apply.APPLY_JSON).exists())

    def test_stuck_apply_of_another_skill_does_not_block(self):
        with self.interrupt("_commit"), self.assertRaises(KeyboardInterrupt):
            self.approve()
        shutil.rmtree(skills.snapshot_dir("demo", self.old))
        other = store.runs_dir() / "other-20260101T000000Z"
        other.mkdir(parents=True)
        (other / "plan.json").write_text(json.dumps({"skill": "other", "base_fingerprint": "x"}))
        d = apply.reject(other.name, cwd=str(self.cwd))
        self.assertEqual(d["decision"], "reject")
        self.assertTrue((self.run_dir / apply.APPLY_JSON).exists())
        with self.assertRaisesRegex(apply.Refused, "snapshot"):
            apply.reject(RUN)


class TestRejectRevert(Base):
    def test_reject(self):
        rec = apply.reject(RUN, reason="not now", cwd=str(self.cwd))
        self.assertEqual(rec["reason"], "not now")
        self.assertEqual(self.fp(), self.old)
        self.assertEqual(self.rows("SELECT * FROM opt_applied") if self._has_table() else [], [])
        d = json.loads((self.run_dir / apply.DECISION_JSON).read_text())
        self.assertEqual(d["decision"], "reject")
        apply.reject(RUN, cwd=str(self.cwd))
        self.assertIsNone(json.loads((self.run_dir / apply.DECISION_JSON).read_text())["reason"])

    def _has_table(self):
        return bool(self.rows("SELECT name FROM sqlite_master WHERE name='opt_applied'"))

    def test_revert_restores_old_fingerprint(self):
        self.approve()
        rec = apply.revert(RUN, cwd=str(self.cwd))
        self.assertEqual(self.fp(), self.old)
        self.assertEqual(rec["decision"], "revert")
        self.assertEqual([r[0] for r in self.rows("SELECT action FROM opt_applied ORDER BY rowid")], ["approve", "revert"])
        self.assertTrue((self.folder / "refs" / "a.md").exists())
        self.assertEqual((self.folder / "evals" / "evals.json").read_text(), '{"keep": true}\n')
        with self.assertRaisesRegex(apply.Refused, "nothing to revert"):
            apply.revert(RUN, cwd=str(self.cwd))

    def test_revert_after_reject_still_works(self):
        self.approve()
        rec = apply.reject(RUN, cwd=str(self.cwd))
        self.assertEqual(rec["decision"], "reject")
        self.assertEqual(self.fp(), self.new)
        apply.revert(RUN, cwd=str(self.cwd))
        self.assertEqual(self.fp(), self.old)
        apply.reject(RUN, cwd=str(self.cwd))

    def test_reject_after_approve_is_recorded_in_cli(self):
        self.approve()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch("sys.argv", ["tokscope", "optimize", "reject", RUN]), \
                mock.patch("os.getcwd", return_value=str(self.cwd)):
            cli.main()
        self.assertIn("rejected", out.getvalue())
        self.assertEqual(self.fp(), self.new)

    def test_revert_refusals(self):
        with self.assertRaisesRegex(apply.Refused, "nothing to revert"):
            apply.revert(RUN, cwd=str(self.cwd))
        self.approve()
        (self.folder / "SKILL.md").write_text("hand edit\n")
        edited = self.fp()
        with self.assertRaisesRegex(apply.Refused, "edited after the approve"):
            apply.revert(RUN, cwd=str(self.cwd))
        self.assertEqual(self.fp(), edited)

    def test_git_revert_commits(self):
        self.git_repo()
        self.approve()
        rec = apply.revert(RUN, cwd=str(self.cwd))
        self.assertTrue(rec["commit_sha"])
        self.assertIn("revert", sh(self.root, "git", "log", "-1", "--format=%s"))


class TestCli(Base):
    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch("sys.argv", ["tokscope", *argv]), \
                mock.patch("os.getcwd", return_value=str(self.cwd)):
            try:
                cli.main()
            except SystemExit as e:
                code = e.code or 0
        return code, out.getvalue(), err.getvalue()

    def test_approve_reject_revert(self):
        code, out, _ = self.call("optimize", "approve", RUN)
        self.assertEqual(code, 0)
        self.assertIn(f"approved demo: {self.old} → {self.new}", out)
        code, out, _ = self.call("optimize", "revert", RUN)
        self.assertEqual((code, self.fp()), (0, self.old))
        code, out, _ = self.call("optimize", "reject", RUN, "--reason", "nope")
        self.assertEqual(code, 0)

    def test_refusal_exits_2(self):
        self.set_verdict(stats.REJECT)
        code, _, err = self.call("optimize", "approve", RUN)
        self.assertEqual(code, 2)
        self.assertIn("tokscope:", err)
        code, _, err = self.call("optimize", "approve", "no-such-run")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
