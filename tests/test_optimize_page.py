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
from tokscope.web.dashboard import shell
from tokscope.web.dashboard.pages import optimize as page

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

    def make_run(self, name, verdict, created):
        run = store.runs_dir() / name
        for rel, text in (("SKILL.md", BASE_BODY), ("refs/a.md", "a\n")):
            write(run / "versions" / "v0" / rel, text)
        for rel, text in (("SKILL.md", DRAFT_BODY), ("refs/b.md", "b\n")):
            write(run / "versions" / "v1" / rel, text)
        new = skills.fingerprint(run / "versions" / "v1")
        plan = {"schema": 1, "skill": "demo", "run_id": name, "base_fingerprint": self.old, "dev": ["d1", "d2"],
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
            "draft_fingerprint": new, "base_fingerprint": self.old, "run_id": name, "skill": "demo", "spent_usd": 1.0,
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

    def test_a_level_below_full_hides_the_text(self):
        for level in ("redacted", "minimal"):
            body = self.render(f"run={APPLY_RUN}", level)
            self.assertIn("Run text is hidden", body)
            self.assertNotIn("evidence d1", body)
            self.assertNotIn("old body", body)


if __name__ == "__main__":
    unittest.main()
