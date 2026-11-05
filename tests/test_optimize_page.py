import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from tokscope import paths
from tokscope.core import ingest, skills
from tokscope.features import postship
from tokscope.experiments.skillopt import apply, stats, store
from tokscope.web.dashboard import server, shell
from tokscope.web.dashboard.pages import optimize as page
from tests.test_skillopt_loop import CFG, FAKE, IDS

APPLY_RUN, NOT_ENOUGH_RUN, REJECT_RUN = "demo-20260101T000000Z", "demo-20260102T000000Z", "demo-20260103T000000Z"
GATES = ["Valid", "Meaningful suite", "Safety", "No regression", "Benefit"]
CHECKS = ["says alpha", "says bravo", "says charlie", "no denials"]
BASE_BODY, DRAFT_BODY = "---\nname: demo\n---\nold body\n", "---\nname: demo\n---\nnew body\n"


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if isinstance(text, str) else json.dumps(text))
    return path


class Fixture(unittest.TestCase):
    """A temp data home and HOME with a personal skill `demo` and three finished runs of it, built with the store's own
    helpers: Apply, Not enough evidence and Reject. Each has a plan, a verdict, graded results, two editor rounds and
    versions v0 and v1."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        env = {"TOKSCOPE_HOME": str(self.tmp / "tok"), "HOME": str(self.tmp / "h"), "GIT_CONFIG_GLOBAL": "/dev/null",
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@t"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        self.root = self.tmp / "h" / ".claude" / "skills"
        self.folder = self.root / "demo"
        write(self.folder / "SKILL.md", BASE_BODY)
        write(self.folder / "refs" / "a.md", "a\n")
        write(self.folder / "evals" / "evals.json", '{"keep": true}\n')
        self.old = skills.fingerprint(self.folder)
        self.db = paths.db()
        ingest.connect(self.db).close()
        for name, verdict, day in ((APPLY_RUN, stats.APPLY, 1), (NOT_ENOUGH_RUN, stats.NOT_ENOUGH, 2),
                                   (REJECT_RUN, stats.REJECT, 3)):
            self.make_run(name, verdict, f"2026-01-0{day}T00:00:00+00:00")

    def make_run(self, name, verdict, created, skill="demo"):
        run = store.runs_dir() / name
        for rel, text in (("SKILL.md", BASE_BODY), ("refs/a.md", "a\n")):
            write(run / "versions" / "v0" / rel, text)
        for rel, text in (("SKILL.md", DRAFT_BODY), ("refs/b.md", "b\n")):
            write(run / "versions" / "v1" / rel, text)
        new = skills.fingerprint(run / "versions" / "v1")
        plan = {"schema": 1, "skill": skill, "run_id": name, "base_fingerprint": self.old, "dev": ["d1", "d2"],
                "holdout": ["h1"], "runs": 1, "model": "sonnet", "budget_usd": 2.0, "per_run_cap_usd": 2.0, "seed": 5,
                "resamples": 200, "gates": stats.GATES, "created": created}
        store.write_plan(run, plan)
        for stage, arm, passed, cost in (("baseline", "current", 2, 0.10), ("baseline", "none", 0, 0.12),
                                         ("confirm", "current", 2, 0.10), ("confirm", "v1", 4, 0.08)):
            for case in ("d1", "d2", "h1"):
                self.result(run, stage, case, arm, passed, cost)
        for n, accepted in ((1, True), (2, False)):
            ed = run / "rounds" / str(n) / "editor"
            write(ed / "hypothesis.txt", f"hypothesis {n}")
            write(ed / "result.json", {"round": n, "hypothesis": f"hypothesis {n}", "accepted": accepted,
                                       "reason": None if accepted else "same files as v1"})
        for case in ("d1", "d2"):
            self.result(run, "r1", case, "v1", 4, 0.08)
        write(run / "verdict.json", {
            "verdict": verdict, "reason": f"because {verdict}", "stopped": None, "draft_version": "v1",
            "draft_fingerprint": new, "base_fingerprint": self.old, "run_id": name, "skill": skill, "spent_usd": 1.0,
            "budget_usd": 2.0, "trigger": {"status": "not needed", "reason": "the description did not change",
                                            "prompts": {"train": 0, "test": 0}, "passed": None, "reverted": False},
            "gates": [{"name": g, "passed": True, "value": 1, "threshold": 0, "detail": f"detail of {g}"} for g in GATES]})
        write(run / "benchmark.json", {"metadata": {}, "runs": [], "run_summary": {}})
        return run

    def result(self, run, stage, case, arm, passed, cost):
        d = store.result_dir(run, stage, case, arm, 0)
        grading = {"status": "ok", "passed": passed, "total": 4, "safety_failed": 0,
                   "expectations": [{"text": CHECKS[i], "passed": i < passed, "evidence": f"evidence {case} {arm} {i}",
                                     "type": "answer_regex", "safety": False} for i in range(4)]}
        write(d / "grading.json", grading)
        write(d / "run.json", {"cost_usd": cost, "status": "ok", "load": "n/a" if arm == "none" else "ok", "duration_s": 1.0,
                               "usage": {"output_tokens": 50, "input_tokens": 100}})
        write(d / "final.md", f"answer of {case} {arm}")
        store.append(run, {"kind": "run", "stage": stage, "case": case, "arm": arm, "i": 0, "cost_usd": cost, "status": "ok"})

    def run_dir(self, name=APPLY_RUN):
        return store.runs_dir() / name

    def rows(self, sql):
        conn = ingest.connect(paths.db())
        try:
            return conn.execute(sql).fetchall()
        finally:
            conn.close()


class DataTest(Fixture):
    def test_runs_lists_the_three_runs_newest_first(self):
        found = page.runs()
        self.assertEqual([r["id"] for r in found], [REJECT_RUN, NOT_ENOUGH_RUN, APPLY_RUN])
        self.assertEqual([r["verdict"] for r in found], [stats.REJECT, stats.NOT_ENOUGH, stats.APPLY])
        self.assertTrue(all(r["state"] == "done" and r["skill"] == "demo" and r["budget"] == 2.0 for r in found))
        self.assertAlmostEqual(found[0]["spent"], 1.36, places=6)  # 14 results at the fixture's costs
        self.assertIsNone(found[0]["decision"])

    def test_a_run_without_a_verdict_is_stopped_or_running(self):
        (self.run_dir() / "verdict.json").unlink()
        self.assertEqual(next(r for r in page.runs() if r["id"] == APPLY_RUN)["state"], "stopped")
        (self.run_dir() / "run.lock").write_text(str(os.getpid()))
        self.assertEqual(next(r for r in page.runs() if r["id"] == APPLY_RUN)["state"], "running")
        self.assertEqual(page.running_for("demo"), APPLY_RUN)
        self.assertIsNone(page.running_for("other"))

    def test_a_lock_older_than_its_pid_is_a_reused_pid_not_a_running_run(self):
        (self.run_dir() / "verdict.json").unlink()
        lock = self.run_dir() / "run.lock"
        lock.write_text(str(os.getpid()))
        os.utime(lock, (1, 1))  # written long before the pid's process started
        with mock.patch.object(page, "_started_at", return_value=time.time()):  # no /proc needed (macOS)
            self.assertEqual(next(r for r in page.runs() if r["id"] == APPLY_RUN)["state"], "stopped")
            self.assertIsNone(page.running_for("demo"))

    def test_a_lock_slightly_older_than_its_pid_still_counts_as_running(self):
        (self.run_dir() / "verdict.json").unlink()
        lock = self.run_dir() / "run.lock"
        lock.write_text(str(os.getpid()))
        now = time.time()
        os.utime(lock, (now - 5, now - 5))  # a small clock step, not a reused pid
        with mock.patch.object(page, "_started_at", return_value=now):
            self.assertEqual(next(r for r in page.runs() if r["id"] == APPLY_RUN)["state"], "running")
        os.utime(lock, (now - 60, now - 60))  # a minute before the pid started: reused
        with mock.patch.object(page, "_started_at", return_value=now):
            self.assertEqual(next(r for r in page.runs() if r["id"] == APPLY_RUN)["state"], "stopped")

    def test_a_wall_clock_step_after_the_lock_keeps_a_live_run_running(self):
        (self.run_dir() / "verdict.json").unlink()
        lock = self.run_dir() / "run.lock"
        lock.write_text(f"{os.getpid()} 4242")  # pid and its boot-relative start ticks
        stepped = time.time() + 60  # the clock jumped a minute after the lock was written: btime moves, mtime does not
        with mock.patch.object(store, "start_ticks", return_value=4242), \
                mock.patch.object(page, "_started_at", return_value=stepped):
            self.assertEqual(next(r for r in page.runs() if r["id"] == APPLY_RUN)["state"], "running")
            self.assertEqual(page.running_for("demo"), APPLY_RUN)

    def test_a_pid_reused_after_the_lock_is_stopped_whatever_the_clock_says(self):
        (self.run_dir() / "verdict.json").unlink()
        lock = self.run_dir() / "run.lock"
        lock.write_text(f"{os.getpid()} 4242")
        # a new process got the pid (other start ticks) even though the mtime check alone would call it running
        with mock.patch.object(store, "start_ticks", return_value=9999), \
                mock.patch.object(page, "_started_at", return_value=time.time() - 3600):
            self.assertEqual(next(r for r in page.runs() if r["id"] == APPLY_RUN)["state"], "stopped")
            self.assertIsNone(page.running_for("demo"))

    @unittest.skipUnless(os.path.exists("/proc/self/stat"), "needs Linux /proc")
    def test_a_lock_taken_by_store_survives_a_clock_step_on_linux(self):
        (self.run_dir() / "verdict.json").unlink()
        store.acquire(self.run_dir())
        self.addCleanup(store.release, self.run_dir())
        with mock.patch.object(page, "_started_at", return_value=time.time() + 60):
            self.assertEqual(next(r for r in page.runs() if r["id"] == APPLY_RUN)["state"], "running")

    def test_an_unreadable_start_time_falls_back_to_the_lock_age(self):
        (self.run_dir() / "verdict.json").unlink()
        lock = self.run_dir() / "run.lock"
        lock.write_text(str(os.getpid()))
        with mock.patch.object(page, "_started_at", return_value=None):
            self.assertEqual(next(r for r in page.runs() if r["id"] == APPLY_RUN)["state"], "running")
            old = time.time() - page.RUN_MAX_AGE - 60
            os.utime(lock, (old, old))  # older than any run lives: the pid was reused
            self.assertEqual(next(r for r in page.runs() if r["id"] == APPLY_RUN)["state"], "stopped")

    def test_start_time_without_proc_comes_from_ps_etime(self):
        self.assertEqual(page._etime_seconds("05:07\n"), 307)
        self.assertEqual(page._etime_seconds("2-03:04:05"), 2 * 86400 + 3 * 3600 + 4 * 60 + 5)
        self.assertRaises(ValueError, page._etime_seconds, "")
        with mock.patch.object(page.Path, "read_text", side_effect=OSError), \
                mock.patch.object(page.subprocess, "run", return_value=mock.Mock(stdout="01:00:00\n")):
            self.assertAlmostEqual(page._started_at(1), time.time() - 3600, delta=5)
        with mock.patch.object(page.Path, "read_text", side_effect=OSError), \
                mock.patch.object(page.subprocess, "run", side_effect=OSError):
            self.assertIsNone(page._started_at(1))

    def test_no_runs_dir_gives_an_empty_list(self):
        shutil.rmtree(store.runs_dir())
        self.assertEqual(page.runs(), [])

    def test_load_reads_plan_gates_cases_rounds_and_files(self):
        d = page.load(APPLY_RUN)
        self.assertEqual([g["name"] for g in d["gates"]], GATES)
        self.assertEqual(d["draft"], "v1")
        self.assertEqual(d["versions"], ["v0", "v1"])
        self.assertEqual([(c["split"], c["case"]) for c in d["cases"]], [("dev", "d1"), ("dev", "d2"), ("holdout", "h1")])
        groups = {(g["stage"], g["arm"]): g["runs"] for g in d["cases"][0]["groups"]}
        self.assertEqual(list(groups), [("baseline", "current"), ("baseline", "none"), ("confirm", "current"), ("confirm", "draft")])
        draft = groups[("confirm", "draft")][0]  # the arm v1 is shown as the draft
        self.assertEqual((draft["passed"], draft["total"], draft["answer"]), (4, 4, "answer of d1 v1"))
        self.assertEqual(draft["expectations"][0], {"text": "says alpha", "passed": True, "evidence": "evidence d1 v1 0",
                                                    "type": "answer_regex", "safety": False})
        self.assertEqual([(r["round"], r["accepted"], r["reason"], r["draft"]) for r in d["rounds"]],
                         [(1, True, None, True), (2, False, "same files as v1", False)])
        self.assertEqual(d["rounds"][0]["hypothesis"], "hypothesis 1")
        self.assertAlmostEqual(d["rounds"][0]["score"][0], 100.0)
        self.assertEqual([(rel, kind) for rel, kind, _, _ in d["files"]],
                         [("SKILL.md", "changed"), ("refs/a.md", "removed"), ("refs/b.md", "added")])
        self.assertEqual(d["files"][0][2:], (BASE_BODY, DRAFT_BODY))

    def test_arm_numbers_give_a_ci_per_arm_and_map_the_draft(self):
        arms = {(a["stage"], a["arm"]): a for a in page.load(APPLY_RUN)["arms"]}
        self.assertEqual(list(arms), [("baseline", "current"), ("baseline", "none"), ("confirm", "current"), ("confirm", "draft")])
        draft = arms[("confirm", "draft")]
        self.assertEqual((draft["runs"], draft["counted"]), (3, 3))
        self.assertAlmostEqual(draft["pass"]["mean"], 100.0)
        self.assertAlmostEqual(draft["cost"]["mean"], 0.08)
        self.assertAlmostEqual(draft["tokens"]["mean"], 150)
        for a in arms.values():
            self.assertLessEqual(a["pass"]["ci_low"], a["pass"]["mean"] + 1e-9)
            self.assertGreaterEqual(a["pass"]["ci_high"], a["pass"]["mean"] - 1e-9)
        self.assertAlmostEqual(arms[("baseline", "none")]["pass"]["mean"], 0.0)

    def test_broken_files_leave_empty_sections_not_errors(self):
        run = self.run_dir()
        (run / "verdict.json").write_text("{not json")
        (run / "benchmark.json").write_text("[1")
        (run / "rounds" / "1" / "editor" / "result.json").write_text("nope")
        bad = store.result_dir(run, "baseline", "d1", "current", 0) / "grading.json"
        bad.write_text("{broken")
        d = page.load(APPLY_RUN)
        self.assertEqual((d["gates"], d["verdict"], d["draft"], d["files"]), ([], {}, None, []))
        self.assertEqual(d["summary"]["state"], "done")  # the file is there, only unreadable
        self.assertEqual(d["skipped"], 1)
        self.assertEqual(d["rounds"][0]["accepted"], None)
        (run / "plan.json").write_text("[]")
        d = page.load(APPLY_RUN)
        self.assertEqual((d["cases"], d["plan"]), ([], {}))
        self.assertEqual(next(r for r in page.runs() if r["id"] == APPLY_RUN)["skill"], APPLY_RUN)

    def test_unknown_run_is_a_value_error(self):
        for bad in ("nope", "../x", ""):
            with self.assertRaises(ValueError):
                page.load(bad)


class RenderTest(Fixture):
    def render(self, qs="", level="full"):
        conn = ingest.connect(self.db)
        try:
            return shell.render(conn, "optimize", {k: [v] for k, v in (p.split("=") for p in qs.split("&") if p)}, "stamp", level)
        finally:
            conn.close()

    def test_the_list_names_each_run_with_its_verdict_and_spend(self):
        body = self.render()
        for run in (APPLY_RUN, NOT_ENOUGH_RUN, REJECT_RUN):
            self.assertIn(f'href="/optimize?run={run}"', body)
        for word in (stats.APPLY, stats.NOT_ENOUGH, stats.REJECT, "$1.36 of $2.00"):
            self.assertIn(word, body)
        self.assertIn('href="/optimize" class=on aria-current=page', body)
        self.assertNotIn('class="filters"', body)

    def test_an_empty_data_home_shows_the_empty_state(self):
        shutil.rmtree(store.runs_dir())
        self.assertIn("No optimize runs yet", self.render())

    def test_an_unknown_run_gives_a_notice_and_the_list(self):
        body = self.render("run=nope")
        self.assertIn("There is no run <code>nope</code>", body)
        self.assertIn(f'href="/optimize?run={APPLY_RUN}"', body)

    def test_the_report_has_every_section_gate_case_and_check_evidence(self):
        body = self.render(f"run={APPLY_RUN}")
        for section in ("Plan", "Gates", "Cases", "Editor", "Before and after"):
            self.assertIn(f">{section}</h2>", body)
        for gate in GATES:
            self.assertIn(f"<td>{gate}</td>", body)
        for case in ("d1", "d2", "h1"):
            self.assertIn(f'<span class="ttl">{case}</span>', body)
        self.assertLess(body.index("Dev cases (2)"), body.index('<span class="ttl">d1</span>'))
        self.assertLess(body.index('<span class="ttl">d2</span>'), body.index("Holdout cases (1)"))
        self.assertIn("baseline current 2/4", body)
        self.assertIn("confirm draft 4/4", body)
        self.assertIn("evidence d1 v1 2", body)  # the draft arm is v1 in the files, shown as the draft
        self.assertIn("answer of h1 none", body)
        self.assertIn("because Apply", body)
        self.assertIn("Trigger check", body)
        self.assertIn("hypothesis 1", body)
        self.assertIn("same files as v1", body)
        self.assertIn("became the draft", body)
        self.assertIn("dev score 100 points", body)

    def test_the_compare_has_the_diff_and_a_ci_per_arm(self):
        body = self.render(f"run={APPLY_RUN}")
        self.assertIn('<table class="sbs">', body)
        self.assertIn("<mark>old</mark>", body)
        self.assertIn("<mark>new</mark>", body)
        for path in ("SKILL.md", "refs/a.md", "refs/b.md"):
            self.assertIn(f'<h3 class="path">{path} ', body)
        self.assertEqual(body.count('class="note">[') , 12)  # pass, cost and tokens for four arms
        self.assertIn("Per arm", body)
        self.assertNotIn('id="compare"', body)  # the theme hides #compare (the Sessions compare tray) until it opens

    def test_a_run_without_a_draft_shows_only_the_editor(self):
        v = json.loads((self.run_dir() / "verdict.json").read_text())
        v.update(draft_version=None, draft_fingerprint=None)
        (self.run_dir() / "verdict.json").write_text(json.dumps(v))
        body = self.render(f"run={APPLY_RUN}")
        self.assertIn("No draft was made", body)
        self.assertNotIn('<table class="sbs">', body)
        self.assertIn("hypothesis 1", body)

    def test_a_broken_run_still_renders(self):
        (self.run_dir() / "verdict.json").write_text("{")
        store.result_dir(self.run_dir(), "baseline", "d1", "current", 0).joinpath("grading.json").write_text("x")
        body = self.render(f"run={APPLY_RUN}")
        self.assertIn("No verdict yet", body)
        self.assertIn("1 result could not be read", body)

    def test_a_plan_with_wrong_field_types_still_renders(self):
        plan = {"skill": 5, "created": 20260101, "budget_usd": "2", "per_run_cap_usd": "x", "dev": 3, "holdout": "a",
                "model": ["m"], "runs": {"a": 1}}
        (self.run_dir() / "plan.json").write_text(json.dumps(plan))
        self.assertIn("Plan", self.render(f"run={APPLY_RUN}"))
        self.assertIn("Optimize runs", self.render())

    def test_a_level_below_full_hides_the_text(self):
        for level in ("redacted", "minimal"):
            body = self.render(f"run={APPLY_RUN}", level)
            self.assertIn("Run text is hidden", body)
            self.assertNotIn("evidence d1", body)
            self.assertNotIn("old body", body)


class DecideTest(Fixture):
    def post(self, run, act, body=None, path=None):
        return server.post(self.db, path or f"optimize/{run}/{act}", body or {}, "full")

    def fp(self):
        return skills.fingerprint(self.folder)

    def draft_fp(self, run=APPLY_RUN):
        return skills.fingerprint(self.run_dir(run) / "versions" / "v1")

    def verdict(self, run, **kw):
        path = self.run_dir(run) / "verdict.json"
        path.write_text(json.dumps({**json.loads(path.read_text()), **kw}))

    def test_approve_installs_the_measured_draft_and_records_it(self):
        code, out = self.post(APPLY_RUN, "approve")
        self.assertEqual((code, out["decision"], out["new_fingerprint"]), (200, "approve", self.draft_fp()))
        self.assertEqual(self.fp(), self.draft_fp())
        self.assertEqual((self.folder / "refs" / "b.md").read_text(), "b\n")
        self.assertFalse((self.folder / "refs" / "a.md").exists())
        self.assertEqual((self.folder / "evals" / "evals.json").read_text(), '{"keep": true}\n')
        self.assertEqual(self.rows("SELECT run_id, action FROM opt_applied"), [(APPLY_RUN, "approve")])
        self.assertEqual(json.loads((self.run_dir() / "decision.json").read_text())["decision"], "approve")

    def test_an_approve_after_an_approve_and_a_run_measured_on_an_old_version_are_409(self):
        self.assertEqual(self.post(APPLY_RUN, "approve")[0], 200)
        code, out = self.post(APPLY_RUN, "approve")
        self.assertEqual(code, 409)
        self.assertIn("already approved", out["error"])
        code, out = self.post(NOT_ENOUGH_RUN, "approve", {"reason": "I looked"})  # the skill moved on to the first draft
        self.assertEqual(code, 409)
        self.assertEqual(self.fp(), self.draft_fp())

    def test_not_enough_evidence_needs_a_reason(self):
        for body in ({}, {"reason": "   "}, {"reason": 5}):
            code, out = self.post(NOT_ENOUGH_RUN, "approve", body)
            self.assertEqual(code, 400, body)
            self.assertIn("reason", out["error"])
            self.assertEqual(self.fp(), self.old)
        code, out = self.post(NOT_ENOUGH_RUN, "approve", {"reason": " read the diff "})
        self.assertEqual((code, out["reason"]), (200, "read the diff"))
        self.assertEqual(self.fp(), self.draft_fp(NOT_ENOUGH_RUN))

    def test_a_reject_verdict_cannot_be_approved_but_can_be_rejected(self):
        code, out = self.post(REJECT_RUN, "approve", {"reason": "please"})
        self.assertEqual(code, 400)
        self.assertIn("Reject", out["error"])
        self.assertEqual(self.fp(), self.old)
        code, out = self.post(REJECT_RUN, "reject")
        self.assertEqual((code, out["decision"], out["reason"], out["approve_still_applied"]), (200, "reject", None, False))
        self.assertEqual(self.fp(), self.old)

    def test_reject_works_on_every_run_with_and_without_a_reason(self):
        for run, body, reason in ((APPLY_RUN, {}, None), (NOT_ENOUGH_RUN, {"reason": "not now"}, "not now"), (REJECT_RUN, {"reason": ""}, None)):
            code, out = self.post(run, "reject", body)
            self.assertEqual((code, out["reason"]), (200, reason), run)
        self.assertEqual(self.fp(), self.old)
        self.assertEqual(sorted(r[1] for r in self.rows("SELECT run_id, action FROM opt_applied")), ["reject"] * 3)

    def test_a_reject_after_an_approve_says_the_approve_is_still_applied(self):
        self.post(APPLY_RUN, "approve")
        code, out = self.post(APPLY_RUN, "reject", {"reason": "changed my mind"})
        self.assertEqual((code, out["approve_still_applied"]), (200, True))
        self.assertEqual(self.fp(), self.draft_fp())
        self.assertIn("An earlier approve is still applied", RenderTest.render(self, f"run={APPLY_RUN}"))

    def test_a_skill_edited_after_the_run_is_409_and_untouched(self):
        (self.folder / "SKILL.md").write_text("edited by hand\n")
        edited = self.fp()
        code, out = self.post(APPLY_RUN, "approve")
        self.assertEqual(code, 409)
        self.assertIn("cannot tell which skill folder", out["error"])  # no folder holds the measured version any more
        self.assertEqual(self.fp(), edited)

    def test_a_missing_verdict_or_draft_is_400_and_an_unknown_run_is_404(self):
        self.verdict(NOT_ENOUGH_RUN, draft_version=None, draft_fingerprint=None)
        code, out = self.post(NOT_ENOUGH_RUN, "approve", {"reason": "x"})
        self.assertEqual((code, out["error"]), (400, "no draft to apply"))
        (self.run_dir(REJECT_RUN) / "verdict.json").unlink()
        self.assertEqual(self.post(REJECT_RUN, "approve")[0], 400)
        self.assertEqual(self.post(REJECT_RUN, "reject")[0], 200)  # a reject is always allowed
        self.assertEqual(self.post("demo-nope", "approve")[0], 404)
        self.assertEqual(self.post("demo-nope", "reject")[0], 404)

    def test_the_old_job_routes_are_untouched(self):
        for act in ("apply", "discard", "cancel", "bench", "task"):
            self.assertEqual(self.post("20260101-000000-abcdef", act, path=f"api/optimize/20260101-000000-abcdef/{act}"),
                             (404, {"error": "unknown endpoint"}))
        self.assertEqual(self.post(APPLY_RUN, "approve", path=f"api/optimize/{APPLY_RUN}/approve")[0], 404)
        self.assertEqual(self.post(APPLY_RUN, "approve", path=f"optimize/{APPLY_RUN}/apply")[0], 404)
        self.assertEqual(server.post(self.db, f"optimize/{APPLY_RUN}/approve", {}, "redacted")[0], 403)

    def test_two_requests_at_once_apply_the_draft_once(self):
        results, gate = [], threading.Barrier(2)

        def go():
            gate.wait()
            results.append(self.post(APPLY_RUN, "approve")[0])
        threads = [threading.Thread(target=go) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), [200, 409])
        self.assertEqual(self.fp(), self.draft_fp())
        self.assertEqual(len(self.rows("SELECT * FROM opt_applied")), 1)
        self.assertFalse((self.run_dir() / "run.lock").exists())

    def test_the_owning_project_is_found_by_the_measured_version(self):
        proj = self.tmp / "work" / "app"
        sibling = proj / ".claude" / "skills" / "demo"
        for rel, text in (("SKILL.md", BASE_BODY), ("refs/a.md", "a\n")):
            write(sibling / rel, text)
        conn = ingest.connect(self.db)
        conn.execute("INSERT INTO sessions (session_id, project, cwd, title, prompts) VALUES ('s1', '-p', ?, 't', 1)", (str(proj / "src"),))
        conn.commit()
        want = {self.old}
        try:
            root, k, why = page.owner_root(conn, "demo", want)
            self.assertIsNone(root)
            self.assertIn("cannot tell which skill folder", why)
            self.assertIn(str(sibling), why)
            (sibling / "SKILL.md").write_text("project copy changed\n")
            root, k, why = page.owner_root(conn, "demo", want)  # only the personal one still has the measured version
            self.assertEqual((root, k["scope"]), (self.tmp / "h", "personal"))
            root, k, why = page.owner_root(conn, "demo", {skills.fingerprint(sibling)})
            self.assertEqual((root, k["folder"]), (proj, sibling))  # folder.parents[2] is the project root
            self.assertEqual(page.owner_root(conn, "demo", {"nope"}, loose=True)[0], self.tmp / "h")
            self.assertIsNone(page.owner_root(conn, "absent", want)[0])
        finally:
            conn.close()

    def test_a_project_skill_is_approved_with_the_project_as_cwd(self):
        proj = self.tmp / "work" / "app"
        folder = proj / ".claude" / "skills" / "pdemo"
        for rel, text in (("SKILL.md", BASE_BODY), ("refs/a.md", "a\n")):
            write(folder / rel, text)
        conn = ingest.connect(self.db)
        conn.execute("INSERT INTO sessions (session_id, project, cwd, title, prompts) VALUES ('s1', '-p', ?, 't', 1)", (str(proj),))
        conn.commit()
        conn.close()
        self.make_run("pdemo-20260104T000000Z", stats.APPLY, "2026-01-04T00:00:00+00:00", skill="pdemo")
        code, out = self.post("pdemo-20260104T000000Z", "approve")
        self.assertEqual(code, 200, out)
        self.assertEqual(skills.fingerprint(folder), self.draft_fp("pdemo-20260104T000000Z"))
        self.assertEqual(self.fp(), self.old)  # the personal skill of another name is not touched


class DecideMarkupTest(Fixture):
    def body(self, run):
        return RenderTest.render(self, f"run={run}")

    def approve_button(self, body):
        m = re.search(r'<button[^>]*data-opt-act="approve"[^>]*>', body)
        return m.group(0) if m else None

    def test_apply_has_an_enabled_approve_and_an_optional_reason(self):
        body = self.body(APPLY_RUN)
        self.assertNotIn("disabled", self.approve_button(body))
        self.assertIn("Reason (optional)", body)
        self.assertNotIn(" required", body)
        self.assertIn('data-opt-act="reject"', body)
        self.assertIn("not in git: no commit is made", body)

    def test_not_enough_evidence_needs_the_reason_before_approve(self):
        body = self.body(NOT_ENOUGH_RUN)
        self.assertIn("disabled", self.approve_button(body))
        self.assertNotIn("data-block", self.approve_button(body))  # the page script enables it once a reason is typed
        self.assertIn("<textarea id=\"opt-reason\" rows=\"2\" required>", body)
        self.assertIn("Reason (required to approve)", body)

    def test_reject_verdict_has_approve_off_with_its_reason(self):
        body = self.body(REJECT_RUN)
        self.assertIn('disabled data-block="1"', self.approve_button(body))
        self.assertIn("Approve is off: the verdict is Reject (because Reject)", body)
        self.assertIn('data-opt-act="reject"', body)

    def test_no_verdict_has_no_approve_and_no_draft_has_it_off(self):
        (self.run_dir(REJECT_RUN) / "verdict.json").unlink()
        body = self.body(REJECT_RUN)
        self.assertIsNone(self.approve_button(body))
        self.assertIn('data-opt-act="reject"', body)
        path = self.run_dir() / "verdict.json"
        path.write_text(json.dumps({**json.loads(path.read_text()), "draft_version": None, "draft_fingerprint": None}))
        self.assertIn("Approve is off: no draft to apply", self.body(APPLY_RUN))

    def test_no_verdict_still_finds_the_installed_skill_by_the_plan_fingerprint(self):
        (self.run_dir(REJECT_RUN) / "verdict.json").unlink()
        self.assertNotIn("Approve will refuse", self.body(REJECT_RUN))

    def test_an_approved_run_shows_the_decision_and_approve_off(self):
        server.post(self.db, f"optimize/{APPLY_RUN}/approve", {"reason": "ok"}, "full")
        body = self.body(APPLY_RUN)
        self.assertIn("<b>Approved</b>", body)
        self.assertIn("reason: ok", body)
        self.assertIn("disabled", self.approve_button(body))

    def test_a_git_skill_names_its_branch(self):
        sh(self.root, "git", "init", "-q", "-b", "trunk")
        self.assertIn("on the git branch <code>trunk</code>", self.body(APPLY_RUN))


class StartTest(unittest.TestCase):
    """POST optimize/start: the estimate first, a worker only after confirm. The worker is the real CLI in a child
    process with a fake claude, so the test waits for it and stops its process group before it deletes the folders."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        fake = self.tmp / "claude"
        fake.write_text(FAKE)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        (self.tmp / "cfg.json").write_text(json.dumps(CFG))
        env = {"TOKSCOPE_HOME": str(self.tmp / "tok"), "HOME": str(self.tmp / "h"), "TOKSCOPE_CLAUDE": str(fake),
               "FAKE_CFG": str(self.tmp / "cfg.json"), "FAKE_LOG": str(self.tmp / "calls.jsonl"),
               "FAKE_MARKER": str(self.tmp / "marker"), "GIT_CONFIG_GLOBAL": "/dev/null"}
        p = mock.patch.dict(os.environ, env)
        p.start()
        self.addCleanup(p.stop)
        self.proj = self.tmp / "proj"
        self.skill = self.proj / ".claude" / "skills" / "demo"
        write(self.skill / "SKILL.md", "---\nname: demo\ndescription: Summarize notes\n---\nBASE body\n")
        checks = [{"type": "answer_regex", "pattern": rf"\b{t}\b"} for t in "ABCD"]
        write(self.skill / "evals" / "evals.json", {"checks": [{"type": "no_permission_denials", "safety": True}],
                                                    "evals": [{"id": c, "prompt": f"do case {c}", "checks": checks} for c in IDS]})
        self.db = paths.db()
        conn = ingest.connect(self.db)
        conn.execute("INSERT INTO sessions (session_id, project, cwd, title, prompts) VALUES ('s1', '-p', ?, 't', 1)", (str(self.proj),))
        conn.commit()
        conn.close()
        self.sid = next(k["id"] for k in page.library.discover(ingest.connect(self.db)) if k["dir"] == "demo")
        self.procs = []
        self.addCleanup(self.stop_workers)

    def stop_workers(self):
        for proc in self.procs:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass

    def post(self, **kw):
        return server.post(self.db, "optimize/start", {"skill": self.sid, "budget": 5, "runs": 1, **kw}, "full")

    def watch(self):
        """Popen as spawn calls it, with the child remembered so the test can stop it."""
        real = subprocess.Popen

        def popen(*a, **k):
            proc = real(*a, **k)
            self.procs.append(proc)
            return proc
        return mock.patch.object(page.subprocess, "Popen", side_effect=popen)

    def test_without_confirm_it_answers_the_estimate_and_starts_nothing(self):
        with mock.patch.object(page.subprocess, "Popen") as popen:
            code, out = self.post()
        popen.assert_not_called()
        e = out["estimate"]
        self.assertEqual(code, 200)
        self.assertEqual((e["cases"], e["calls"], e["per_call_cap"], e["budget"]), (6, 24, 2.0, 5.0))
        self.assertEqual(e["calls_max"], 24 + 3 * (4 * 1 + 1))  # 4 dev cases of 6 with the default split
        self.assertIsNone(e["cost_per_call"])
        self.assertIn("unknown", " ".join(e["lines"]))
        self.assertIn("About 24 paid runs", e["lines"][0])
        self.assertFalse(store.runs_dir().exists())

    def test_the_estimate_uses_the_median_cost_of_earlier_runs_of_the_skill(self):
        run = store.new_run("demo")
        store.write_plan(run, {"skill": "demo", "budget_usd": 1})
        for cost in (0.1, 0.3, 0.2):
            store.append(run, {"kind": "run", "cost_usd": cost})
        store.append(run, {"kind": "editor", "cost_usd": 9})
        e = self.post()[1]["estimate"]
        self.assertAlmostEqual(e["cost_per_call"], 0.2)
        self.assertAlmostEqual(e["cost"], 24 * 0.2)
        self.assertEqual(e["samples"], 3)

    def test_bad_input_is_400_and_spends_nothing(self):
        (self.proj / ".claude" / "skills" / "bare").mkdir()
        write(self.proj / ".claude" / "skills" / "bare" / "SKILL.md", "---\nname: bare\n---\nx\n")
        write(self.tmp / "h" / ".claude" / "skills" / "ext" / "SKILL.md", "---\nname: ext\n---\nx\n")
        write(self.tmp / "h" / ".claude" / "skills" / "ext" / ".tool-install.json", "{}")
        found = {k["dir"]: k["id"] for k in page.library.discover(ingest.connect(self.db))}
        bad = [{"budget": 0}, {"budget": -1}, {"budget": "5"}, {"budget": True}, {"runs": 0}, {"runs": 1.5}, {"budget": 1e9}, {"runs": 10**6}, {"model": "-x"},
               {"model": "a b"}, {"skill": "nope"}, {"skill": found["bare"]}, {"skill": found["ext"]}]
        with mock.patch.object(page.subprocess, "Popen") as popen:
            for kw in bad:
                code, out = self.post(**kw)
                self.assertEqual(code, 400, kw)
                self.assertIn("error", out)
        popen.assert_not_called()
        self.assertEqual(self.post(runs=2)[1]["estimate"]["calls"], 48)

    def test_the_command_ends_with_a_separator_before_the_skill_name(self):
        cmd = page._command({"name": "--budget", "budget": 2.0, "runs": 1, "model": "sonnet"})
        self.assertEqual(cmd[-2:], ["--", "--budget"])

    def test_with_confirm_it_starts_the_cli_and_names_the_run(self):
        with self.watch():
            code, out = self.post(confirm=True)
        self.assertEqual(code, 200, out)
        run = store.runs_dir() / out["run"]
        self.assertTrue((run / "plan.json").is_file())
        self.assertEqual(out["url"], f"/optimize?run={out['run']}")
        self.assertEqual(json.loads((run / "plan.json").read_text())["skill"], "demo")
        end = time.monotonic() + 90
        while not (run / "verdict.json").is_file() and time.monotonic() < end:
            time.sleep(0.1)
        self.assertTrue((run / "verdict.json").is_file(), "the worker finished its run")
        end = time.monotonic() + 15
        while self.procs[0].returncode is None and time.monotonic() < end:  # reaped by the reader thread, not by poll()
            time.sleep(0.05)
        self.assertEqual(self.procs[0].returncode, 0 if json.loads((run / "verdict.json").read_text())["verdict"] == "Apply" else 1)
        self.assertEqual(next(r for r in page.runs() if r["id"] == out["run"])["state"], "done")
        self.assertIsNone(page.running_for("demo"))
        self.assertTrue((run / "worker.log").is_file())
        self.assertEqual(self.skill.joinpath("SKILL.md").read_text().count("BASE body"), 1)  # a run never edits the skill

    def test_a_run_that_is_going_refuses_a_second_start(self):
        run = store.new_run("demo")
        store.write_plan(run, {"skill": "demo", "budget_usd": 1})
        (run / "run.lock").write_text(str(os.getpid()))
        with mock.patch.object(page.subprocess, "Popen") as popen:
            code, out = self.post(confirm=True)
            popen.assert_not_called()
        self.assertEqual((code, out["run"], out["url"]), (409, run.name, f"/optimize?run={run.name}"))
        self.assertEqual(self.post()[0], 200)  # the estimate alone still answers

    def test_a_worker_that_stops_early_gives_400_with_its_stderr(self):
        cmd = [sys.executable, "-c", "import sys; print('tokscope: boom', file=sys.stderr); sys.exit(2)"]
        with mock.patch.object(page, "_command", return_value=cmd):
            code, out = self.post(confirm=True)
        self.assertEqual(code, 400)
        self.assertIn("tokscope: boom", out["error"])
        self.assertEqual([p.name for p in store.runs_dir().parent.glob(".worker-*")], [])

    @unittest.skipUnless(os.path.isdir("/proc/self/fd"), "needs /proc")
    def test_the_worker_stdout_is_a_file_so_a_server_stop_cannot_break_its_pipe(self):
        run = store.new_run("demo")
        store.write_plan(run, {"skill": "demo", "budget_usd": 1})
        code_ = f"import time; print('run {run}', flush=True); time.sleep(60)"
        cmd = [sys.executable, "-c", code_]
        with mock.patch.object(page, "_command", return_value=cmd), self.watch():
            code, out = self.post(confirm=True)
        self.assertEqual(code, 200, out)
        target = os.readlink(f"/proc/{self.procs[0].pid}/fd/1")
        self.assertFalse(target.startswith("pipe:"), target)
        self.assertTrue((run / "worker.out").is_file())

    def test_a_failed_link_stops_the_worker_and_leaves_no_temp_files(self):
        run = store.new_run("demo")
        store.write_plan(run, {"skill": "demo", "budget_usd": 1})
        cmd = [sys.executable, "-c", f"import time; print('run {run}', flush=True); time.sleep(60)"]
        with mock.patch.object(page, "_command", return_value=cmd), self.watch(), \
                mock.patch.object(page.os, "replace", side_effect=OSError("denied")):
            code, out = self.post(confirm=True)
        self.assertEqual(code, 500)
        self.assertIsNotNone(self.procs[0].wait(timeout=10))
        self.assertEqual([p.name for p in store.runs_dir().parent.glob(".worker-*")], [])

    def test_a_failed_second_temp_file_removes_the_first(self):
        real = tempfile.mkstemp
        calls = []

        def flaky(*a, **k):
            calls.append(1)
            if len(calls) == 2:
                raise OSError("disk full")
            return real(*a, **k)
        with mock.patch.object(page.tempfile, "mkstemp", side_effect=flaky):
            code, out = self.post(confirm=True)
        self.assertEqual(code, 500)
        self.assertEqual([p.name for p in store.runs_dir().parent.glob(".worker-*")], [])

    def test_a_worker_that_prints_nothing_is_stopped_and_gives_500(self):
        cmd = [sys.executable, "-c", "import time; time.sleep(60)"]
        with mock.patch.object(page, "_command", return_value=cmd), mock.patch.object(page, "START_WAIT_S", 0.5), self.watch():
            code, out = self.post(confirm=True)
        self.assertEqual(code, 500)
        self.assertIn("was stopped", out["error"])
        self.assertIsNotNone(self.procs[0].wait(timeout=10))


class LibraryTest(Fixture):
    """The Library side: the verified state beside a skill, the link to its run, the start form."""

    def render(self, qs=None):
        conn = ingest.connect(self.db)
        try:
            return shell.render(conn, "library", qs or {}, "stamp", "full")
        finally:
            conn.close()

    def skill_id(self):
        conn = ingest.connect(self.db)
        try:
            return next(k["id"] for k in page.library.discover(conn) if k["dir"] == "demo")
        finally:
            conn.close()

    def page(self):
        return self.render({"skill": [self.skill_id()]})

    def test_the_badge_follows_approve_then_a_hand_edit(self):
        self.assertIn('title="No optimize run was approved for this version of the skill.">Not verified', self.page())
        self.assertIn(">Not verified</span>", self.render())  # on the skill list too
        server.post(self.db, f"optimize/{REJECT_RUN}/reject", {}, "full")
        self.assertIn(">Not verified</", self.page())  # a reject alone verifies nothing
        server.post(self.db, f"optimize/{APPLY_RUN}/approve", {}, "full")
        body = self.page()
        self.assertIn(f'<a class="badge ver ok" href="/optimize?run={APPLY_RUN}"', body)
        self.assertIn(">Verified</a>", body)
        self.assertIn(">Verified</span>", self.render())
        (self.folder / "SKILL.md").write_text("edited by hand\n")
        body = self.page()
        self.assertIn(f'<a class="badge ver warn" href="/optimize?run={APPLY_RUN}"', body)
        self.assertIn(">Edited after run</a>", body)
        self.assertNotIn(">Verified<", body)

    def test_a_name_shared_with_another_folder_never_reads_as_edited(self):
        server.post(self.db, f"optimize/{APPLY_RUN}/approve", {}, "full")
        proj = self.tmp / "work" / "app"
        write(proj / ".claude" / "skills" / "demo" / "SKILL.md", "---\nname: demo\n---\nsame name, other project\n")
        conn = ingest.connect(self.db)
        conn.execute("INSERT INTO sessions (session_id, project, cwd, title, prompts) VALUES ('s1', '-p', ?, 't', 1)", (str(proj),))
        conn.commit()
        conn.close()
        body = self.render()
        self.assertEqual(body.count(">Verified</span>"), 1)  # the personal one, which still has the approved version
        self.assertEqual(body.count(">Not verified</span>"), 1)
        self.assertNotIn("Edited after run", body)

    def test_the_versions_link_names_the_approving_run(self):
        self.assertNotIn("Approved by an optimize run", self.page())
        server.post(self.db, f"optimize/{APPLY_RUN}/approve", {}, "full")
        body = self.page()
        self.assertIn('id="versions"', body)
        self.assertIn('id="approvals"', body)
        self.assertIn(f'<a href="/optimize?run={APPLY_RUN}">{APPLY_RUN}</a> · installed now', body)

    def test_the_start_form_is_there(self):
        body = self.page()
        self.assertIn('id="optstart"', body)
        self.assertIn('name="budget" value="2"', body)
        self.assertIn('name="runs" value="3"', body)
        self.assertIn('name="model" value="sonnet"', body)
        self.assertNotIn('id="optimize-panel"', body)

    def test_a_running_run_replaces_the_form_with_a_link(self):
        (self.run_dir() / "verdict.json").unlink()
        (self.run_dir() / "run.lock").write_text(str(os.getpid()))
        body = self.page()
        self.assertNotIn('id="optstart"', body)
        self.assertIn(f'href="/optimize?run={APPLY_RUN}"', body)
        self.assertIn("An optimize run of this skill is going", body)

    def test_an_installed_skill_has_no_start_form(self):
        write(self.folder / ".tool-install.json", "{}")
        self.assertNotIn('id="optstart"', self.page())


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ScriptSyntaxTest(unittest.TestCase):
    def test_the_dashboard_scripts_parse(self):
        """One syntax error (an unescaped quote in a Python string) stops every button of the page."""
        from tokscope.web.dashboard import scripts
        for name in ("LIB_JS", "OPT_JS", "DASH_JS"):
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
                f.write(getattr(scripts, name))
            self.addCleanup(os.unlink, f.name)
            done = subprocess.run([shutil.which("node"), "--check", f.name], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, f"{name}: {done.stderr}")


def apply_table():
    return apply.TABLE


AT = "2026-03-10T12:00:00+00:00"


class PostShipTest(Fixture):
    """Real-session numbers on an approved run: loads, median tokens and cost, error rate per version."""

    def setUp(self):
        super().setUp()
        self.new = skills.fingerprint(self.run_dir() / "versions" / "v1")
        self.n = 0
        conn = ingest.connect(self.db)
        conn.execute("INSERT INTO sessions(session_id, project) VALUES ('s1', '-home-me-proj')")
        conn.execute("INSERT INTO sessions(session_id, project) VALUES ('sb', '-home-me-tokscope-bench-1')")
        conn.commit()
        conn.close()

    def approve(self, run=APPLY_RUN):
        conn = ingest.connect(self.db)
        conn.executescript(apply_table())
        conn.execute("INSERT INTO opt_applied VALUES (?, 'demo', 'approve', ?, ?, NULL, 'apply', NULL, ?)",
                     (run, self.old, self.new, AT))
        conn.commit()
        conn.close()

    def loads(self, version, count, day, failed=0, tokens=100, cost=0.5, session="s1"):
        conn = ingest.connect(self.db)
        skills._ensure(conn)
        for k in range(count):
            self.n += 1
            tid, ts = f"t{self.n}", f"2026-03-{day:02d}T0{k % 9}:00:00+00:00"
            conn.execute("INSERT INTO skill_calls(session_id, ts, skill, source, prompt_idx, tool_use_id, failed) "
                         "VALUES (?, ?, 'demo', 'tool', ?, ?, ?)", (session, ts, self.n, tid, int(k < failed)))
            conn.execute("INSERT INTO skill_load_versions VALUES (?, ?, 'demo', ?, ?)", (session, tid, version, ts))
            conn.execute("INSERT INTO requests(session_id, request_key, ts, prompt_idx, input, output, cache_read, "
                         "cache_write_5m, cache_write_1h, cost_usd) VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0, ?)",
                         (session, f"r{self.n}", ts, self.n, tokens + k, cost + k / 100))
        conn.commit()
        conn.close()

    def numbers(self):
        conn = ingest.connect(self.db)
        try:
            return postship.post_ship(conn, "demo", self.old, self.new, AT)
        finally:
            conn.close()

    def render(self, run=APPLY_RUN):
        conn = ingest.connect(self.db)
        try:
            return shell.render(conn, "optimize", {"run": [run]}, "stamp", "full")
        finally:
            conn.close()

    def test_one_turn_with_two_loads_counts_once_in_the_medians(self):
        self.approve()
        self.loads(self.new, 2, 15, tokens=1000, cost=1.0)  # turns 1 and 2: 1000 and 1001
        self.loads(self.new, 1, 16, tokens=100, cost=0.1)  # turn 3: 100
        conn = ingest.connect(self.db)
        conn.execute("INSERT INTO skill_calls(session_id, ts, skill, source, prompt_idx, tool_use_id, failed) "
                     "VALUES ('s1', '2026-03-16T01:00:00+00:00', 'demo', 'tool', 3, 'tdup', 0)")
        conn.execute("INSERT INTO skill_load_versions VALUES ('s1', 'tdup', 'demo', ?, '2026-03-16T01:00:00+00:00')",
                     (self.new,))
        conn.commit()
        conn.close()
        got = self.numbers()["new"]
        self.assertEqual(got["loads"], 4)
        self.assertEqual(got["tokens_median"], 1000)  # turns 1000, 1001, 100; turn 3 not counted twice (550)
        self.assertAlmostEqual(got["cost_median"], 1.0)

    def test_a_turn_keeps_its_full_sum_when_another_skill_loads_in_it(self):
        self.approve()
        self.loads(self.new, 1, 15, tokens=1000, cost=1.0)
        conn = ingest.connect(self.db)
        conn.execute("INSERT INTO skill_calls(session_id, ts, skill, source, prompt_idx, tool_use_id, failed) "
                     "VALUES ('s1', '2026-03-15T01:00:00+00:00', 'other', 'tool', ?, 'tx', 0)", (self.n,))
        conn.commit()
        conn.close()
        got = self.numbers()["new"]
        self.assertEqual((got["tokens_median"], got["cost_median"]), (1000, 1.0))

    def test_failed_loads_count_in_the_token_and_cost_medians(self):
        self.approve()
        self.loads(self.new, 2, 15, failed=1, tokens=100, cost=0.5)
        got = self.numbers()["new"]
        self.assertEqual(got["tokens_median"], 100.5)  # 100 (failed) and 101
        self.assertAlmostEqual(got["cost_median"], 0.505)

    def test_post_ship_function(self):
        self.approve()
        self.loads(self.old, 6, 5, failed=2, tokens=1000, cost=1.0)
        self.loads(self.new, 3, 15, failed=0, tokens=500, cost=0.4)
        got = self.numbers()
        self.assertEqual((got["old"]["loads"], got["old"]["errors"], got["old"]["few"]), (6, 2, False))
        self.assertAlmostEqual(got["old"]["error_rate"], 2 / 6)
        self.assertEqual(got["old"]["tokens_median"], 1002.5)  # medians over all 6 loads: 1000..1005
        self.assertAlmostEqual(got["old"]["cost_median"], 1.025)
        self.assertEqual((got["new"]["loads"], got["new"]["tokens_median"], got["new"]["few"]), (3, 501, True))
        self.assertEqual(got["new"]["error_rate"], 0)

    def test_an_empty_side_has_no_numbers_and_no_division(self):
        self.approve()
        got = self.numbers()["new"]
        self.assertEqual((got["loads"], got["tokens_median"], got["cost_median"], got["error_rate"], got["few"]),
                         (0, None, None, None, True))

    def test_both_sides_with_five_loads_show_their_numbers(self):
        self.approve()
        self.loads(self.old, 5, 5, failed=1, tokens=2000)
        self.loads(self.new, 8, 15, failed=0, tokens=900)
        body = self.render()
        self.assertIn('id="postship"', body)
        self.assertIn("Real sessions", body)
        self.assertIn("20%", body)
        self.assertNotIn("too few to compare", body)
        self.assertIn(">5<", body)
        self.assertIn(">8<", body)

    def test_a_side_with_three_loads_gets_the_too_few_note(self):
        self.approve()
        self.loads(self.old, 6, 5)
        self.loads(self.new, 3, 15)
        body = self.render()
        self.assertIn("Only 3 loads on the new version: too few to compare.", body)
        self.assertNotIn("on the old version: too few", body)

    def test_other_versions_and_old_loads_after_the_approve_are_not_counted(self):
        self.approve()
        self.loads(self.old, 5, 5)
        self.loads(self.new, 5, 15)
        self.loads("edited-by-hand", 7, 20)
        self.loads(self.old, 2, 25)  # the old version read after the approve (a revert, a stale copy)
        got = self.numbers()
        self.assertEqual((got["old"]["loads"], got["new"]["loads"]), (5, 5))

    def test_loads_without_requests_stay_out_of_the_medians(self):
        self.approve()
        self.loads(self.old, 5, 6)
        conn = ingest.connect(self.db)
        conn.execute("DELETE FROM requests WHERE session_id = 's1' AND prompt_idx = 3")
        conn.commit()
        conn.close()
        got = self.numbers()["old"]
        self.assertEqual((got["loads"], got["errors"], got["few"]), (5, 0, False))
        self.assertEqual(got["tokens_median"], 102)  # 100, 101, 103, 104

    def test_bench_session_loads_are_left_out_of_loads_errors_and_medians(self):
        self.approve()
        self.loads(self.old, 3, 5, session="sb", failed=2, tokens=9000, cost=9.0)
        self.loads(self.old, 3, 6, tokens=100, cost=0.1)
        got = self.numbers()["old"]
        self.assertEqual((got["loads"], got["errors"], got["error_rate"], got["few"]), (3, 0, 0, True))
        self.assertEqual(got["tokens_median"], 101)
        self.assertAlmostEqual(got["cost_median"], 0.11)

    def test_an_unapproved_run_has_no_section_and_keeps_decide(self):
        self.approve()
        body = self.render(REJECT_RUN)
        self.assertNotIn('id="postship"', body)
        self.assertIn("Decide", body)

    def test_an_approved_run_with_unreadable_numbers_says_so_instead_of_hiding_the_card(self):
        self.approve()
        with mock.patch.object(postship, "post_ship", side_effect=ValueError("bad ts")):
            body = self.render()
        self.assertIn('id="postship"', body)
        self.assertIn("could not be read", body)
        self.assertIn("Decide", body)

    def test_an_approved_run_without_loads_renders_and_keeps_decide(self):
        self.approve()
        body = self.render()
        self.assertIn('id="postship"', body)
        self.assertIn("Only 0 loads on the old version: too few to compare.", body)
        self.assertIn("Decide", body)


class MainGuardTest(unittest.TestCase):
    def test_main_guard_is_the_last_statement(self):
        """Classes after the guard never run when the file is executed directly."""
        import ast
        last = ast.parse(Path(__file__).read_text()).body[-1]
        self.assertIsInstance(last, ast.If)
        self.assertIn("__main__", ast.unparse(last.test))


if __name__ == "__main__":
    unittest.main()
