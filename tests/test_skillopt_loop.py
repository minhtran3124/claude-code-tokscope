import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tokscope import paths
from tokscope.core import ingest, skills
from tokscope.experiments.skillopt import loop, stats, store, suite

ROOT = Path(__file__).resolve().parent.parent
PLAN = {"seed": 7, "resamples": 300, "holdout": ["h1", "h2"], "gates": stats.GATES}


def rec(case, arm, passed, total=4, cost=0.1, safety=0, status="ok", load=None):
    return {"case": case, "arm": arm, "status": status, "load": load or ("n/a" if arm == "none" else "ok"),
            "passed": passed, "total": total, "safety_failed": safety, "cost_usd": cost}


CASES = ["d1", "d2", "d3", "d4", "h1", "h2"]


def arm_recs(arm, passed, **kw):
    return [rec(c, arm, passed, **kw) for c in CASES for _ in range(2)]


class StatsTest(unittest.TestCase):
    def test_run_counts_only_when_graded_and_loaded(self):
        self.assertTrue(stats.counts(rec("a", "current", 3)))
        self.assertFalse(stats.counts(rec("a", "current", 3, status="INVALID")))
        self.assertFalse(stats.counts(rec("a", "current", 3, load="not loaded")))
        self.assertTrue(stats.counts(rec("a", "none", 3)))
        self.assertEqual(stats.run_pass_rate(rec("a", "current", 3)), 0.75)

    def test_per_case_mean_and_dropped(self):
        runs = [rec("a", "current", 4), rec("a", "current", 2), rec("b", "current", 4, status="INVALID")]
        by, dropped = stats.per_case(runs)
        self.assertEqual(by, {"a": 0.75})
        self.assertEqual(dropped, ["b"])

    def test_bootstrap_is_seeded_and_in_points(self):
        a = {c: 0.5 for c in "abcdef"}
        b = {c: 0.75 for c in "abcdef"}
        one = stats.paired_bootstrap(a, b, 3, 200)
        self.assertEqual(one, stats.paired_bootstrap(a, b, 3, 200))
        self.assertAlmostEqual(one["mean"], 25.0)
        self.assertAlmostEqual(one["ci_low"], 25.0)
        self.assertIsNone(stats.paired_bootstrap({"a": 1}, {"b": 1}, 3))
        cd = stats.cost_diff({"a": 0.2, "b": 0.2}, {"a": 0.1, "b": 0.1}, 3, 100)
        self.assertAlmostEqual(cd["mean"], -0.1)
        self.assertLess(cd["ci_high"], 0)

    def verdict(self, base_cur, base_none, cur, draft, **kw):
        base = arm_recs("current", base_cur) + arm_recs("none", base_none)
        conf = arm_recs("current", cur) + [rec(c, "draft", draft, **kw) for c in CASES for _ in range(2)]
        return stats.gates(PLAN, base, conf)

    def test_equal_arms_fail_meaningful_suite(self):
        out = stats.gates(PLAN, arm_recs("current", 2) + arm_recs("none", 2), [])
        self.assertEqual(out["verdict"], stats.NOT_ENOUGH)
        self.assertIn("baseline", out["reason"])
        self.assertIs(next(g for g in out["gates"] if g["name"] == "Meaningful suite")["passed"], False)
        self.assertIsNone(next(g for g in out["gates"] if g["name"] == "Safety")["passed"])

    def test_one_safety_failure_rejects(self):
        base = arm_recs("current", 4) + arm_recs("none", 0)
        draft = [rec(c, "draft", 4, safety=1 if c == "d1" else 0) for c in CASES for _ in range(2)]
        out = stats.gates(PLAN, base, arm_recs("current", 4) + draft)
        self.assertEqual(out["verdict"], stats.REJECT)
        self.assertIn("Safety", out["reason"])

    def test_draft_failing_most_cases_rejects_on_the_ci(self):
        out = self.verdict(4, 0, 4, 0)
        self.assertEqual(out["verdict"], stats.REJECT)
        reg = next(g for g in out["gates"] if g["name"] == "No regression")
        self.assertLess(reg["value"]["ci_low"], -5)

    def test_holdout_regression_rejects(self):
        base = arm_recs("current", 4) + arm_recs("none", 0)
        cur = arm_recs("current", 2)
        # better on dev, worse on the holdout, CI low still above -5 on the mean
        draft = [rec(c, "draft", 4 if c.startswith("d") else 1) for c in CASES for _ in range(2)]
        out = stats.gates(PLAN, base, cur + draft)
        reg = next(g for g in out["gates"] if g["name"] == "No regression")
        self.assertLess(reg["value"]["holdout_points"], 0)
        self.assertEqual(out["verdict"], stats.REJECT)

    def test_pass_ci_low_above_zero_applies(self):
        out = self.verdict(4, 0, 2, 4)
        self.assertEqual(out["verdict"], stats.APPLY, out)
        self.assertTrue(all(g["passed"] for g in out["gates"]))

    def test_cost_gain_alone_applies(self):
        base = arm_recs("current", 4) + arm_recs("none", 0)
        conf = arm_recs("current", 4, cost=0.3) + arm_recs("draft", 4, cost=0.1)
        self.assertEqual(stats.gates(PLAN, base, conf)["verdict"], stats.APPLY)

    def test_no_gain_is_not_enough_evidence(self):
        out = self.verdict(4, 0, 4, 4)
        self.assertEqual(out["verdict"], stats.NOT_ENOUGH)
        self.assertIn("Benefit", out["reason"])

    def test_valid_below_90_is_not_enough_evidence(self):
        base = arm_recs("current", 4) + arm_recs("none", 0)
        draft = [rec(c, "draft", 4, status="INVALID" if i == 0 and c in CASES[:3] else "ok")
                 for c in CASES for i in range(2)]
        out = stats.gates(PLAN, base, arm_recs("current", 2) + draft)
        valid = out["gates"][0]
        self.assertFalse(valid["passed"])
        self.assertEqual(out["verdict"], stats.NOT_ENOUGH)

    def test_valid_is_checked_per_arm_not_pooled(self):
        base = arm_recs("current", 4) + arm_recs("none", 0)
        draft = [rec(c, "draft", 4, status="INVALID" if i == 0 and c in CASES[:3] else "ok")
                 for c in CASES for i in range(2)]
        current = arm_recs("current", 2) * 4  # pooled share 57/60 = 95%, draft alone 75%
        valid = stats.gates(PLAN, base, current + draft)["gates"][0]
        self.assertFalse(valid["passed"])
        self.assertEqual(valid["value"], 0.75)

    def test_budget_stop_leaves_gates_unrun(self):
        base = arm_recs("current", 4) + arm_recs("none", 0)
        out = stats.gates(PLAN, base, [], stopped="confirm")
        self.assertEqual(out["verdict"], stats.NOT_ENOUGH)
        self.assertTrue(next(g for g in out["gates"] if g["name"] == "Meaningful suite")["passed"])
        self.assertEqual([g["passed"] for g in out["gates"] if g["name"] != "Meaningful suite"], [None] * 4)

    def test_baseline_budget_stop_and_empty_baseline_reasons(self):
        base = arm_recs("current", 4) + arm_recs("none", 0)
        out = stats.gates(PLAN, base, [], stopped="baseline")
        self.assertIn("baseline finished", out["reason"])
        self.assertNotIn("confirm", out["reason"])
        out = stats.gates(PLAN, [rec("a", "current", 4)] + [rec("b", "none", 0)], [])
        self.assertEqual(out["verdict"], stats.NOT_ENOUGH)
        self.assertIn("could not be checked", out["reason"])
        self.assertNotIn("does not beat", out["reason"])

    def test_no_holdout_evidence_is_not_a_pass(self):
        base = arm_recs("current", 4) + arm_recs("none", 0)
        conf = [r for r in arm_recs("current", 2) + arm_recs("draft", 4) if r["case"].startswith("d")]
        out = stats.gates(PLAN, base, conf)
        self.assertEqual(out["verdict"], stats.NOT_ENOUGH)
        self.assertIn("holdout", out["reason"])

    def test_dev_ok_needs_safety_ci_and_benefit(self):
        cur = [r for r in arm_recs("current", 2) if r["case"].startswith("d")]
        better = [r for r in arm_recs("draft", 4) if r["case"].startswith("d")]
        same = [r for r in arm_recs("draft", 2) if r["case"].startswith("d")]
        worse = [r for r in arm_recs("draft", 0) if r["case"].startswith("d")]
        unsafe = [dict(r, safety_failed=1) for r in better]
        self.assertTrue(stats.dev_ok(PLAN, cur, better))
        self.assertFalse(stats.dev_ok(PLAN, cur, same))
        self.assertFalse(stats.dev_ok(PLAN, cur, worse))
        self.assertFalse(stats.dev_ok(PLAN, cur, unsafe))

    def test_score_orders_by_pass_rate_then_cost(self):
        self.assertEqual(stats.score(arm_recs("draft", 2)), (50.0, 0.1))


class Home(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.dict(os.environ, {"TOKSCOPE_HOME": str(self.tmp / "data"), "HOME": str(self.tmp / "home")})
        p.start()
        self.addCleanup(p.stop)


def seed_run(skill="demo", budget=1.0, cases=("a", "b")):
    """A run folder with a frozen suite, a plan and its lock line, as loop.start leaves it."""
    run = store.new_run(skill)
    (run / "suite" / "evals").mkdir(parents=True)
    data = {"evals": [{"id": c, "prompt": "p", "checks": [{"type": "answer_regex", "pattern": "x"}]} for c in cases]}
    (run / "suite" / "evals" / "evals.json").write_text(json.dumps(data))
    plan = {"schema": 1, "skill": skill, "run_id": run.name, "suite_hash": suite.suite_hash(data), "budget_usd": budget,
            "per_run_cap_usd": 2.0, "seed": 1, "gates": stats.GATES}
    store.write_plan(run, plan)
    return run, plan


def make_result(run, stage, case, arm, i, cost=0.1, passed=3, total=4, tmp=False):
    d = store.tmp_dir(run, stage, case, arm, i) if tmp else store.result_dir(run, stage, case, arm, i)
    d.mkdir(parents=True)
    (d / "grading.json").write_text(json.dumps({"status": "ok", "passed": passed, "total": total, "safety_failed": 0}))
    (d / "run.json").write_text(json.dumps({"cost_usd": cost, "status": "ok", "load": "ok", "session_id": f"s-{case}-{i}",
                                            "fingerprint": "fp", "usage": {"output_tokens": 5}, "duration_s": 1.5}))
    return d


class StoreTest(Home):
    def test_new_run_folder_and_id(self):
        run = store.new_run("demo", datetime(2026, 11, 4, 1, 2, 3, tzinfo=timezone.utc))
        self.assertEqual(run, paths.home() / "bench" / "optimize" / "runs" / "demo-20261104T010203Z")
        self.assertTrue(run.is_dir())
        self.assertNotEqual(store.new_run("demo", datetime(2026, 11, 4, 1, 2, 3, tzinfo=timezone.utc)), run)
        with self.assertRaises(ValueError):
            store.new_run("../x")

    def test_plan_lock_detects_an_edit(self):
        run, plan = seed_run()
        store.check_lock(run)
        self.assertEqual(store.lines(run)[0]["kind"], "lock")
        text = (run / "plan.json").read_text()
        (run / "plan.json").write_text(text.replace('"budget_usd": 1.0', '"budget_usd": 100.0'))
        with self.assertRaises(store.LockError):
            store.check_lock(run)

    def test_lock_detects_a_changed_frozen_suite(self):
        run, _ = seed_run()
        path = run / "suite" / "evals" / "evals.json"
        data = json.loads(path.read_text())
        data["evals"][0]["prompt"] = "changed"
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(store.LockError, "frozen suite"):
            store.check_lock(run)

    def test_lock_detects_a_changed_base_version(self):
        run, plan = seed_run()
        v0 = run / "versions" / "v0"
        v0.mkdir(parents=True)
        (v0 / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\nbody\n")
        plan["base_fingerprint"] = skills.fingerprint(v0)
        (run / store.LEDGER).unlink()
        store.write_plan(run, plan)
        store.check_lock(run)
        (v0 / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\nedited\n")
        with self.assertRaisesRegex(store.LockError, "versions/v0"):
            store.check_lock(run)

    def test_ledger_spent_and_torn_line(self):
        run, _ = seed_run()
        store.append(run, {"kind": "run", "cost_usd": 0.25})
        store.append(run, {"kind": "editor", "cost_usd": 0.5})
        store.append(run, {"kind": "start", "cap": 2.0})
        with open(run / "ledger.jsonl", "a") as f:
            f.write('{"kind": "run", "cost')  # a crash mid-write
        self.assertAlmostEqual(store.spent(run), 0.75)
        self.assertEqual(len(store.lines(run)), 4)

    def test_reserve_before_any_history_and_after(self):
        run, plan = seed_run(budget=1.0)
        self.assertEqual(store.reserve(run, plan), 1.0)  # min(MAX_BUDGET_USD, budget)
        plan["budget_usd"] = 5.0
        self.assertEqual(store.reserve(run, plan), 2.0)
        store.append(run, {"kind": "run", "cost_usd": 0.3})
        store.append(run, {"kind": "editor", "cost_usd": 0.7})
        store.append(run, {"kind": "run", "cost_usd": 0.1})
        self.assertEqual(store.reserve(run, plan), 0.7)

    def test_can_spend_and_call_cap(self):
        run, plan = seed_run(budget=1.0)
        store.append(run, {"kind": "run", "cost_usd": 0.4})
        self.assertAlmostEqual(store.call_cap(run, plan), 0.6)
        self.assertTrue(store.can_spend(run, plan))  # 0.4 + 0.4 <= 1.0
        store.append(run, {"kind": "run", "cost_usd": 0.4})
        self.assertFalse(store.can_spend(run, plan))  # 0.8 + 0.4 > 1.0

    def test_result_states(self):
        run, plan = seed_run()
        self.assertEqual(store.result_state(run, "baseline", "a", "current", 0), "todo")
        make_result(run, "baseline", "a", "current", 0)
        self.assertEqual(store.result_state(run, "baseline", "a", "current", 0), "recover")
        store.recover(run, "baseline", "a", "current", 0)
        self.assertEqual(store.result_state(run, "baseline", "a", "current", 0), "done")
        make_result(run, "baseline", "a", "none", 0, tmp=True)
        self.assertEqual(store.result_state(run, "baseline", "a", "none", 0), "lost")

    def test_finish_renames_then_writes_the_line(self):
        run, plan = seed_run()
        make_result(run, "baseline", "a", "current", 1, cost=0.2, tmp=True)
        final = store.finish(run, "baseline", "a", "current", 1)
        self.assertTrue(final.is_dir())
        self.assertFalse(store.tmp_dir(run, "baseline", "a", "current", 1).exists())
        self.assertEqual(store.result_state(run, "baseline", "a", "current", 1), "done")
        self.assertAlmostEqual(store.spent(run), 0.2)

    def test_discard_charges_the_calls_cap(self):
        run, plan = seed_run(budget=1.0)
        cap = store.start(run, plan, "baseline", "a", "none", 0)
        make_result(run, "baseline", "a", "none", 0, tmp=True)
        store.discard(run, plan, "baseline", "a", "none", 0)
        self.assertEqual(store.result_state(run, "baseline", "a", "none", 0), "todo")
        last = store.lines(run)[-1]
        self.assertEqual((last["kind"], last["cost_usd"]), ("lost", cap))
        self.assertAlmostEqual(store.spent(run), cap)

    def test_editor_done_needs_result_and_line(self):
        run, plan = seed_run()
        d = store.editor_dir(run, 1)
        d.mkdir(parents=True)
        (d / "result.json").write_text("{}")
        self.assertFalse(store.editor_done(run, 1))
        store.append(run, {"kind": "editor", "round": 1, "cost_usd": 0.1})
        self.assertTrue(store.editor_done(run, 1))

    def test_run_lock(self):
        run, _ = seed_run()
        store.acquire(run)
        self.assertEqual((run / "run.lock").read_text(), str(os.getpid()))
        store.release(run)
        self.assertFalse((run / "run.lock").exists())
        live = subprocess.Popen(["sleep", "30"])
        self.addCleanup(live.wait)
        self.addCleanup(live.kill)
        (run / "run.lock").write_text(str(live.pid))
        with self.assertRaises(store.LockError):
            store.acquire(run)
        dead = subprocess.Popen(["true"])
        dead.wait()
        (run / "run.lock").write_text(str(dead.pid))
        store.acquire(run)  # a dead pid's lock is taken over
        self.assertEqual((run / "run.lock").read_text(), str(os.getpid()))

    def test_run_lock_takeover_has_one_winner(self):
        dead = subprocess.Popen(["true"])
        dead.wait()
        code = (
            "import sys\nfrom pathlib import Path\nfrom tokscope.experiments.skillopt import store\n"
            "while not Path(sys.argv[2]).exists(): pass\n"
            "try:\n    store.acquire(sys.argv[1]); print('won', flush=True)\n"
            "except store.LockError:\n    print('lost', flush=True)\n"
            "sys.stdin.read()\n")
        root = str(Path(__file__).resolve().parent.parent)
        for _ in range(15):
            run, _ = seed_run()
            (run / "run.lock").write_text(str(dead.pid))
            go = run / "go"
            procs = [subprocess.Popen([sys.executable, "-c", code, str(run), str(go)], cwd=root, text=True,
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE) for _ in range(8)]
            try:
                go.write_text("")
                out = [p.stdout.readline().strip() for p in procs]
            finally:
                for p in procs:
                    p.stdin.close()
                    p.wait()
            self.assertEqual(out.count("won"), 1, out)

    def test_run_lock_is_never_seen_empty(self):
        """A lock created but not yet written must not look stale to a second process."""
        run, _ = seed_run()
        code = ("import sys\nfrom tokscope.experiments.skillopt import store\n"
                "try:\n    store.acquire(sys.argv[1]); print('won')\nexcept store.LockError:\n    print('lost')\n")
        root = str(Path(__file__).resolve().parent.parent)
        seen = []
        real = os.fdopen

        def fdopen(fd, *a, **k):
            r = subprocess.run([sys.executable, "-c", code, str(run)], cwd=root, text=True, capture_output=True)
            seen.append(r.stdout.strip())
            return real(fd, *a, **k)

        with mock.patch("os.fdopen", fdopen):
            store.acquire(run)
        self.assertNotIn("won", seen)
        self.assertEqual((run / "run.lock").read_text(), str(os.getpid()))

    def test_index_is_rebuilt_from_files(self):
        run, _ = seed_run()
        make_result(run, "baseline", "a", "current", 0, passed=3)
        make_result(run, "baseline", "b", "none", 0, passed=1, total=4)
        make_result(run, "confirm", "a", "current", 1, tmp=True)  # unfinished: not indexed
        self.assertEqual(store.index(run), 2)
        self.assertEqual(store.index(run), 2)  # a rebuild, not a second copy
        conn = ingest.connect(paths.db())
        rows = conn.execute("SELECT stage, case_id, arm, idx, passed, pass_rate, session_id, tokens FROM opt_results "
                            "WHERE run_id = ? ORDER BY case_id", (run.name,)).fetchall()
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        conn.close()
        self.assertEqual(rows, [("baseline", "a", "current", 0, 3, 0.75, "s-a-0", 5),
                                ("baseline", "b", "none", 0, 1, 0.25, "s-b-0", 5)])
        self.assertIn("opt_results_session", names)


FAKE = r"""#!/usr/bin/env python3
import json, os, re, sys, time
from pathlib import Path
argv = sys.argv[1:]
if argv == ["--version"]:
    print("9.9.9-fake")
    sys.exit(0)
cfg = json.loads(Path(os.environ["FAKE_CFG"]).read_text())
prompt = argv[argv.index("-p") + 1]
say = lambda ev: print(json.dumps(ev), flush=True)


def pick(table, kind, case=None):
    v = table.get(kind, table.get("default"))
    if isinstance(v, dict):
        v = v.get(case, v.get("default"))
    return v


editor = prompt.startswith("Improve the Claude Code skill")
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"editor": editor, "argv": argv}) + "\n")
say({"type": "system", "subtype": "init", "model": "fake", "plugins": []})
if editor:
    if os.environ.get("FAKE_SLEEP_EDITOR") and not Path(os.environ["FAKE_MARKER"]).exists():
        Path(os.environ["FAKE_MARKER"]).write_text("1")
        time.sleep(30)
    n = int(re.search(r"edit round (\d+)", prompt).group(1))
    mode = pick(cfg["editor"], str(n))
    if mode == "crash":
        sys.exit(1)
    text = Path("SKILL.md").read_text()
    if mode in ("edit", "nohyp"):
        text += "\nDRAFT edit %d\n" % n
    if mode == "desc":
        text = text.replace("description: Summarize notes", "description: Something else") + "\nDRAFT\n"
    Path("SKILL.md").write_text(text)
    answer = "done" if mode == "nohyp" else "I changed it.\nHypothesis: made edit %d" % n
    say({"type": "result", "result": answer, "is_error": False, "total_cost_usd": cfg["cost"]["editor"], "num_turns": 3})
    sys.exit(0)
case = re.search(r"do case (\w+)", prompt).group(1)
skill = Path(".claude/skills/demo/SKILL.md")
kind = "none"
if skill.exists():
    text = skill.read_text()
    kind = "draft" if "DRAFT" in text else "current"
    if not os.environ.get("FAKE_NO_CALL"):
        body = text.split("---\n", 2)[2].strip()
        say({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Skill", "input": {"skill": "demo"}}]}})
        say({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "Launching skill: demo"},
             {"type": "text", "text": "Base directory for this skill: " + os.getcwd() + "/.claude/skills/demo\n\n" + body}]}})
say({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "x"}}]}})
if os.environ.get("FAKE_SLEEP_CASE") == kind + ":" + case and not Path(os.environ["FAKE_MARKER"]).exists():
    Path(os.environ["FAKE_MARKER"]).write_text("1")
    time.sleep(30)
k = pick(cfg["k"], kind, case)
res = {"type": "result", "result": " ".join("ABCD"[:k]), "is_error": False, "total_cost_usd": pick(cfg["cost"], kind, case),
       "num_turns": 2, "session_id": "s-%d" % os.getpid(), "usage": {"output_tokens": 5}}
if pick(cfg.get("deny", {}), kind, case):
    res["permission_denials"] = [{"tool_name": "Bash"}]
if os.environ.get("FAKE_INVALID_ONCE") and not Path(os.environ["FAKE_INVALID_ONCE"]).exists():
    Path(os.environ["FAKE_INVALID_ONCE"]).write_text("1")
    res = {"type": "result", "result": "boom", "is_error": True, "total_cost_usd": 0.1}
say(res)
"""

IDS = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot"]
CFG = {"k": {"current": 2, "none": 0, "draft": 4}, "cost": {"default": 0.1, "editor": 0.2}, "editor": {"default": "edit"}}


class LoopBase(Home):
    def setUp(self):
        super().setUp()
        fake = self.tmp / "claude"
        fake.write_text(FAKE)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.cfg_path, self.log_path, self.marker = self.tmp / "cfg.json", self.tmp / "calls.jsonl", self.tmp / "marker"
        self.env = {"TOKSCOPE_CLAUDE": str(fake), "FAKE_CFG": str(self.cfg_path), "FAKE_LOG": str(self.log_path)}
        p = mock.patch.dict(os.environ, {**self.env, "FAKE_MARKER": str(self.marker)})
        p.start()
        self.addCleanup(p.stop)
        self.proj = self.tmp / "proj"
        self.skill = self.proj / ".claude" / "skills" / "demo"
        (self.skill / "evals").mkdir(parents=True)
        (self.skill / "SKILL.md").write_text("---\nname: demo\ndescription: Summarize notes\n---\nBASE body\n")
        (self.skill / "ref.md").write_text("ref\n")
        checks = [{"type": "answer_regex", "pattern": rf"\b{t}\b"} for t in "ABCD"]
        data = {"checks": [{"type": "no_permission_denials", "safety": True}],
                "evals": [{"id": c, "prompt": f"do case {c}", "checks": checks} for c in IDS]}
        (self.skill / "evals" / "evals.json").write_text(json.dumps(data))
        self.evals_before = (self.skill / "evals" / "evals.json").read_bytes()
        self.fp_before = skills.fingerprint(self.skill)
        self.set_cfg()

    def set_cfg(self, **over):
        cfg = json.loads(json.dumps(CFG))
        for k, v in over.items():
            cfg[k] = {**cfg.get(k, {}), **v}
        self.cfg_path.write_text(json.dumps(cfg))

    def go(self, budget=50.0, runs=2, **kw):
        out = []
        run = loop.start("demo", budget, runs=runs, cwd=str(self.proj), log=out.append, **kw)
        self.out = out
        return run, json.loads((run / "verdict.json").read_text())

    def calls(self):
        return [json.loads(l) for l in self.log_path.read_text().splitlines()] if self.log_path.exists() else []

    def ledger_runs(self, run):
        return [(l["stage"], l["case"], l["arm"], l["i"]) for l in store.lines(run) if l["kind"] == "run"]


class LoopTest(LoopBase):
    def test_full_run_ends_with_every_file_and_apply(self):
        run, v = self.go()
        for name in ("plan.json", "ledger.jsonl", "benchmark.json", "verdict.json"):
            self.assertTrue((run / name).is_file(), name)
        self.assertTrue((run / "results").is_dir())
        self.assertEqual(v["verdict"], "Apply", v)
        self.assertEqual([g["name"] for g in v["gates"]], ["Valid", "Meaningful suite", "Safety", "No regression", "Benefit"])
        self.assertTrue(all(g["passed"] and g["value"] is not None for g in v["gates"]))
        self.assertEqual(v["draft_version"], "v1")  # dev_ok stops after round 1
        self.assertEqual(v["draft_fingerprint"], skills.fingerprint(run / "versions" / "v1"))
        self.assertEqual(v["base_fingerprint"], self.fp_before)
        self.assertLessEqual(v["spent_usd"], v["budget_usd"])
        self.assertFalse((run / "versions" / "v2").exists())
        plan = json.loads((run / "plan.json").read_text())
        self.assertEqual((plan["schema"], plan["runs"], plan["model"], plan["claude_version"], plan["max_rounds"]),
                         (1, 2, "sonnet", "9.9.9-fake", 3))
        self.assertEqual(sorted(plan["dev"] + plan["holdout"]), sorted(IDS))
        self.assertEqual(plan["description"], "Summarize notes")
        self.assertEqual(store.lines(run)[0]["kind"], "lock")
        self.assertTrue(any("estimate" in l for l in self.out))
        stages = {p.name for p in (run / "results").iterdir()}
        self.assertEqual(stages, {"preflight", "baseline", "r1", "confirm"})
        self.assertEqual(len(set(self.ledger_runs(run))), len(self.ledger_runs(run)))
        for argv in (c["argv"] for c in self.calls()):
            self.assertEqual(argv[argv.index("--model") + 1], "sonnet")

    def test_benchmark_follows_the_skill_creator_schema(self):
        run, _ = self.go()
        b = json.loads((run / "benchmark.json").read_text())
        self.assertEqual(b["metadata"]["skill_name"], "demo")
        self.assertEqual({r["configuration"] for r in b["runs"]}, {"current", "draft", "no_skill"})
        r = b["runs"][0]
        self.assertEqual(set(r["result"]), {"pass_rate", "passed", "failed", "total", "time_seconds", "tokens", "tool_calls", "errors"})
        self.assertTrue(r["expectations"])
        self.assertEqual(set(b["run_summary"]) - {"delta"}, {"current", "draft", "no_skill"})
        self.assertIn("pass_rate", b["run_summary"]["delta"])

    def test_the_real_skill_is_never_written(self):
        self.go()
        self.assertEqual(skills.fingerprint(self.skill), self.fp_before)
        self.assertEqual((self.skill / "evals" / "evals.json").read_bytes(), self.evals_before)

    def test_opt_results_holds_every_result(self):
        run, _ = self.go()
        conn = ingest.connect(paths.db())
        n = conn.execute("SELECT COUNT(*) FROM opt_results WHERE run_id = ?", (run.name,)).fetchone()[0]
        conn.close()
        self.assertEqual(n, len(store.records(run)))
        self.assertGreater(n, 30)

    def test_small_budget_stops_before_passing_it(self):
        run, v = self.go(budget=0.55)
        self.assertEqual(v["verdict"], "Not enough evidence")
        self.assertLessEqual(store.spent(run), 0.55)
        self.assertLessEqual(v["spent_usd"], 0.55)
        self.assertIn(v["stop_stage"], ("baseline",))
        self.assertIn("baseline", v["reason"])
        self.assertEqual([g["passed"] for g in v["gates"]], [None] * 5)
        self.assertFalse((run / "rounds").exists())
        self.assertEqual(loop.exit_code(run), 1)

    def test_every_call_is_capped_by_what_is_left(self):
        run, _ = self.go(budget=0.55)
        caps = [float(c["argv"][c["argv"].index("--max-budget-usd") + 1]) for c in self.calls()]
        self.assertAlmostEqual(caps[0], 0.55)
        self.assertTrue(all(c <= 0.55 for c in caps))
        self.assertLess(caps[-1], caps[0])

    def test_equal_arms_stop_after_baseline(self):
        self.set_cfg(k={"none": 2})
        run, v = self.go()
        self.assertEqual(v["verdict"], "Not enough evidence")
        meaningful = v["gates"][1]
        self.assertIs(meaningful["passed"], False)
        self.assertEqual(v["stop_stage"], "baseline")
        self.assertEqual({p.name for p in (run / "results").iterdir()}, {"preflight", "baseline"})
        self.assertFalse((run / "rounds").exists())
        self.assertFalse(any(c["editor"] for c in self.calls()))

    def test_preflight_that_does_not_load_the_skill_stops(self):
        with mock.patch.dict(os.environ, {"FAKE_NO_CALL": "1"}):
            run, v = self.go()
        self.assertEqual(v["verdict"], "Not enough evidence")
        self.assertIn("preflight", v["reason"])
        self.assertEqual({p.name for p in (run / "results").iterdir()}, {"preflight"})
        self.assertEqual(len(self.calls()), 1)

    def test_one_invalid_preflight_is_retried(self):
        with mock.patch.dict(os.environ, {"FAKE_INVALID_ONCE": str(self.tmp / "once")}):
            run, v = self.go()
        self.assertNotEqual(v["stop_stage"], "preflight")
        self.assertIsNone(v["stopped"])
        self.assertEqual([l[3] for l in self.ledger_runs(run) if l[0] == "preflight"], [0, 1])

    def test_a_safety_failure_rejects(self):
        self.set_cfg(deny={"draft": {"alpha": True}})
        run, v = self.go()
        self.assertEqual(v["verdict"], "Reject")
        self.assertIn("Safety", v["reason"])
        self.assertEqual(loop.exit_code(run), 1)

    def test_a_draft_that_fails_most_cases_rejects_on_the_ci(self):
        self.set_cfg(k={"draft": 0})
        run, v = self.go()
        self.assertEqual(v["verdict"], "Reject")
        self.assertLess(v["gates"][3]["value"]["ci_low"], -5)
        self.assertEqual(sorted(p.name for p in (run / "rounds").iterdir()), ["1", "2", "3"])  # never dev_ok

    def test_refused_drafts_are_recorded_and_not_run(self):
        self.set_cfg(editor={"1": "nohyp", "2": "desc", "3": "same"})
        run, v = self.go()
        self.assertEqual(v["verdict"], "Not enough evidence")
        self.assertIn("no draft", v["reason"])
        reasons = [json.loads((run / "rounds" / str(n) / "editor" / "result.json").read_text()) for n in (1, 2, 3)]
        self.assertEqual([r["accepted"] for r in reasons], [False] * 3)
        self.assertIn("Hypothesis", reasons[0]["reason"])
        self.assertIn("description", reasons[1]["reason"])
        self.assertIn("same files", reasons[2]["reason"])
        self.assertFalse((run / "versions" / "v1").exists())
        self.assertNotIn("confirm", {p.name for p in (run / "results").iterdir()})

    def test_an_editor_with_no_result_is_charged_its_cap(self):
        self.set_cfg(editor={"1": "crash"})
        run, _ = self.go()
        line = next(l for l in store.lines(run) if l["kind"] == "editor" and l["round"] == 1)
        start = next(l for l in store.lines(run) if l["kind"] == "start" and l.get("round") == 1)
        self.assertGreater(start["cap"], 0)
        self.assertEqual(line["cost_usd"], start["cap"])

    def test_a_run_with_no_cost_is_charged_its_cap(self):
        run, plan = seed_run()
        store.start(run, plan, "baseline", "a", "current", 0)
        make_result(run, "baseline", "a", "current", 0, cost=None, tmp=True)
        store.finish(run, "baseline", "a", "current", 0)
        line = [l for l in store.lines(run) if l["kind"] == "run"][-1]
        self.assertGreater(line["cost_usd"], 0)

    def test_editor_sees_dev_cases_only(self):
        self.set_cfg(k={"draft": 2})  # no gain: three rounds, three prompts
        run, _ = self.go()
        plan = json.loads((run / "plan.json").read_text())
        self.assertEqual(len(plan["holdout"]), 2)
        for n in (1, 2, 3):
            ed = run / "rounds" / str(n) / "editor"
            blob = (ed / "prompt.md").read_text()
            for p in (ed / "workspace").rglob("*"):
                blob += p.relative_to(ed / "workspace").as_posix() + (p.read_text(errors="replace") if p.is_file() else "")
            for h in plan["holdout"]:
                self.assertNotIn(h, blob, f"round {n}")
            self.assertTrue(any(d in blob for d in plan["dev"]))
        second = (run / "rounds" / "2" / "editor" / "prompt.md").read_text()
        self.assertIn("made edit 1", second)  # an earlier hypothesis and its dev result
        self.assertIn("Failed dev cases", second)
        self.assertIn("Most costly", second)
        self.assertIn("failed: ", second)

    def test_plan_is_written_before_the_first_paid_run(self):
        seen = {}
        real = loop.run_one

        def spy(ctx, *a):
            seen.setdefault("lock", store.lines(ctx.run)[0]["kind"])
            seen.setdefault("plan", (ctx.run / "plan.json").is_file())
            return real(ctx, *a)

        with mock.patch.object(loop, "run_one", spy):
            self.go()
        self.assertEqual(seen, {"lock": "lock", "plan": True})

    def test_load_errors_are_value_errors_before_any_run(self):
        data = json.loads((self.skill / "evals" / "evals.json").read_text())
        data["evals"][0]["checks"] = [{"type": "nope"}]
        (self.skill / "evals" / "evals.json").write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            loop.start("demo", 5.0, cwd=str(self.proj))
        with self.assertRaises(ValueError):
            loop.start("nosuch", 5.0, cwd=str(self.proj))
        self.assertEqual(self.calls(), [])
        self.assertFalse(store.runs_dir().exists())
        with self.assertRaises(ValueError):
            loop.start("demo", 0, cwd=str(self.proj))

    def test_front_description_reads_folded_values(self):
        p = self.tmp / "S.md"
        p.write_text("---\nname: x\ndescription: >\n  one\n  two\nother: 1\n---\nbody\n")
        self.assertEqual(loop._front_description(p), "> one two")  # the value as written, compared as is
        p.write_text("---\nname: x\n---\nbody\n")
        self.assertIsNone(loop._front_description(p))


class FrozenSuiteTest(LoopBase):
    def test_freeze_keeps_fixtures_outside_evals_and_loads_back(self):
        (self.skill / "fixtures").mkdir()
        (self.skill / "fixtures" / "a.txt").write_text("a")
        data = json.loads((self.skill / "evals" / "evals.json").read_text())
        data["evals"][0]["files"] = ["fixtures/a.txt"]
        (self.skill / "evals" / "evals.json").write_text(json.dumps(data))
        live = suite.load("demo", str(self.proj))
        self.assertEqual(live.problems, [])
        frozen = self.tmp / "frozen"
        dev, hold = suite.freeze(live, frozen)
        self.assertEqual((frozen / "fixtures" / "a.txt").read_text(), "a")
        again = suite.load_folder(frozen)
        self.assertEqual(again.problems, [])
        self.assertEqual(suite.suite_hash(again.data), suite.suite_hash(live.data))
        self.assertEqual((dev, hold), suite.split(again, write=False))

    def test_workspace_from_a_source_folder_and_a_frozen_suite(self):
        live = suite.load("demo", str(self.proj))
        frozen = self.tmp / "frozen"
        dev, hold = suite.freeze(live, frozen)
        src = self.tmp / "v1"
        src.mkdir()
        (src / "SKILL.md").write_text("---\nname: demo\ndescription: Summarize notes\n---\nVERSION ONE\n")
        (self.skill / "SKILL.md").write_text("---\nname: demo\ndescription: Summarize notes\n---\nCHANGED LIVE\n")
        ws = suite.editor_workspace("demo", self.tmp / "ws", source=src, suite=suite.load_folder(frozen))
        self.assertIn("VERSION ONE", (ws / "SKILL.md").read_text())
        blob = "".join(p.relative_to(ws).as_posix() + p.read_text(errors="replace") for p in ws.rglob("*") if p.is_file())
        for h in hold:
            self.assertNotIn(h, blob)
        for d in dev:
            self.assertIn(d, blob)


class ResumeTest(LoopBase):
    def child(self, **env):
        """Run loop.start in its own process group and kill the group once the fake has reached its marker."""
        code = f"from tokscope.experiments.skillopt import loop; loop.start('demo', 50.0, runs=2, cwd={str(self.proj)!r})"
        proc = subprocess.Popen([sys.executable, "-c", code], cwd=ROOT, env={**os.environ, **env}, start_new_session=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        deadline = time.time() + 60
        while not self.marker.exists() and time.time() < deadline:
            time.sleep(0.05)
        self.assertTrue(self.marker.exists(), proc.stderr.read() if proc.poll() is not None else "no marker")
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        proc.stderr.close()
        (run,) = store.runs_dir().iterdir()
        self.assertFalse((run / "verdict.json").exists())
        return run

    def finished(self, run):
        self.assertEqual(len(set(self.ledger_runs(run))), len(self.ledger_runs(run)))  # no (stage, case, arm, i) twice
        return json.loads((run / "verdict.json").read_text())

    def test_kill_in_a_case_then_resume_runs_nothing_twice(self):
        run = self.child(FAKE_SLEEP_CASE="none:charlie")
        self.assertTrue(list((run / "results").rglob("*.tmp")))
        before = len(self.ledger_runs(run))
        v = loop.resume(run.name, log=lambda *_: None)
        self.assertEqual(v, run)
        out = self.finished(run)
        self.assertEqual(out["verdict"], "Apply")
        self.assertFalse(list((run / "results").rglob("*.tmp")))
        lost = [l for l in store.lines(run) if l["kind"] == "lost"]
        self.assertEqual(len(lost), 1)
        self.assertGreater(lost[0]["cost_usd"], 0)  # charged at the call's cap
        self.assertGreater(len(self.ledger_runs(run)), before)
        self.assertFalse((run / "run.lock").exists())
        self.assertAlmostEqual(out["spent_usd"], store.spent(run), places=4)

    def test_kill_in_the_editor_cleans_the_round_and_runs_it_again(self):
        run = self.child(FAKE_SLEEP_EDITOR="1")
        self.assertTrue((run / "rounds" / "1" / "editor" / "prompt.md").is_file())
        self.assertFalse(store.editor_done(run, 1))
        loop.resume(run.name, log=lambda *_: None)
        out = self.finished(run)
        self.assertEqual(out["verdict"], "Apply")
        self.assertTrue(store.editor_done(run, 1))
        self.assertEqual(sum(1 for l in store.lines(run) if l["kind"] == "editor" and l["round"] == 1), 1)
        self.assertEqual(sum(1 for l in store.lines(run) if l["kind"] == "lost" and l.get("round") == 1), 1)
        self.assertEqual(sum(1 for c in self.calls() if c["editor"]), 2)  # killed once, run once

    def test_an_edited_plan_makes_resume_refuse(self):
        run = self.child(FAKE_SLEEP_CASE="none:charlie")
        n = len(self.calls())
        text = (run / "plan.json").read_text()
        (run / "plan.json").write_text(text.replace('"budget_usd": 50.0', '"budget_usd": 500.0'))
        with self.assertRaises(store.LockError):
            loop.resume(run.name)
        self.assertEqual(len(self.calls()), n)
        self.assertFalse((run / "run.lock").exists())

    def test_a_live_run_lock_refuses(self):
        run, _ = self.go()
        live = subprocess.Popen(["sleep", "30"])
        self.addCleanup(live.wait)
        self.addCleanup(live.kill)
        (run / "run.lock").write_text(str(live.pid))
        with self.assertRaises(store.LockError):
            loop.resume(run.name)
        with self.assertRaises(store.LockError):
            loop.regrade(run.name)

    def test_resume_of_a_finished_run_runs_nothing(self):
        run, v = self.go()
        n = len(self.calls())
        before = (run / "verdict.json").read_bytes()
        loop.resume(run.name, log=lambda *_: None)
        self.assertEqual(len(self.calls()), n)
        self.assertEqual((run / "verdict.json").read_bytes(), before)
        self.assertTrue(any("Apply" in l for l in loop.report(run)))

    def test_a_finished_folder_without_its_line_is_recovered_not_rerun(self):
        run, v = self.go()
        n = len(self.calls())
        ledger = store.lines(run)
        last = max(i for i, l in enumerate(ledger) if l["kind"] == "run")
        lost = ledger[last]
        del ledger[last]
        (run / "ledger.jsonl").write_text("".join(json.dumps(l, sort_keys=True) + "\n" for l in ledger))
        (run / "verdict.json").unlink()
        loop.resume(run.name, log=lambda *_: None)
        self.assertEqual(len(self.calls()), n)
        self.assertIn((lost["stage"], lost["case"], lost["arm"], lost["i"]), self.ledger_runs(run))
        self.assertEqual(self.finished(run)["verdict"], "Apply")

    def test_regrade_makes_no_paid_call_and_keeps_spent(self):
        run, v = self.go()
        spent, n = store.spent(run), len(self.calls())
        victim = next((run / "results" / "baseline").rglob("stream.jsonl"))
        victim.write_text(victim.read_text().replace('"type": "result"', '"type": "nothing"'))
        with mock.patch("subprocess.Popen", side_effect=AssertionError("no process")), \
                mock.patch("subprocess.run", side_effect=AssertionError("no process")):
            loop.regrade(run.name, log=lambda *_: None)
        self.assertEqual(len(self.calls()), n)
        self.assertEqual(store.spent(run), spent)
        self.assertEqual(json.loads((victim.parent / "grading.json").read_text())["status"], "INVALID")
        again = json.loads((run / "verdict.json").read_text())
        self.assertEqual(again["draft_fingerprint"], v["draft_fingerprint"])
        conn = ingest.connect(paths.db())
        bad = conn.execute("SELECT COUNT(*) FROM opt_results WHERE run_id = ? AND status = 'INVALID'", (run.name,)).fetchone()[0]
        conn.close()
        self.assertEqual(bad, 1)

    def test_regrade_refuses_a_changed_plan_or_suite(self):
        run, _ = self.go()
        path = run / "suite" / "evals" / "evals.json"
        data = json.loads(path.read_text())
        data["evals"][0]["prompt"] = "changed"
        path.write_text(json.dumps(data))
        with self.assertRaises(store.LockError):
            loop.regrade(run.name)


class CliTest(LoopBase):
    def cli(self, *args, **env):
        env = {**os.environ, "PYTHONPATH": str(ROOT), **env}
        return subprocess.run([sys.executable, "-m", "tokscope.cli", "optimize", *args], cwd=self.proj, env=env,
                              capture_output=True, text=True, timeout=120)

    def test_run_prints_folder_spent_and_gates_and_exits_0_on_apply(self):
        r = self.cli("run", "demo", "--budget", "50", "--runs", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(str(store.runs_dir() / "demo-"), r.stdout)
        self.assertRegex(r.stdout, r"spent \$[\d.]+ of \$50\.00")
        for gate in ("Valid", "Meaningful suite", "Safety", "No regression", "Benefit"):
            self.assertIn(gate, r.stdout)
        self.assertIn("verdict: Apply", r.stdout)

    def test_exit_1_for_not_enough_evidence_and_reject(self):
        self.set_cfg(k={"none": 2})
        r = self.cli("run", "demo", "--budget", "50", "--runs", "1")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertIn("Not enough evidence", r.stdout)
        self.set_cfg(deny={"draft": {"default": True}}, k={"none": 0})
        r = self.cli("run", "demo", "--budget", "50", "--runs", "1")
        self.assertEqual((r.returncode, "Reject" in r.stdout), (1, True), r.stdout)

    def test_load_errors_exit_2_before_any_paid_run(self):
        for args in (("run", "nosuch", "--budget", "5"), ("resume", "nosuch-run"), ("regrade", "nosuch-run")):
            r = self.cli(*args)
            self.assertEqual(r.returncode, 2, args)
            self.assertIn("tokscope:", r.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.cli("run", "demo").returncode, 2)  # --budget is required (argparse)

    def test_edited_plan_makes_resume_exit_2_and_regrade_exits_with_the_verdict(self):
        self.cli("run", "demo", "--budget", "50", "--runs", "1")
        (run,) = store.runs_dir().iterdir()
        g = self.cli("regrade", run.name)
        self.assertEqual(g.returncode, 0, g.stderr)
        self.assertIn("verdict: Apply", g.stdout)
        text = (run / "plan.json").read_text()
        (run / "plan.json").write_text(text.replace('"runs": 1', '"runs": 9'))
        n = len(self.calls())
        e = self.cli("resume", run.name)
        self.assertEqual(e.returncode, 2)
        self.assertIn("changed after it was locked", e.stderr)
        self.assertEqual(len(self.calls()), n)

    def test_help_lists_the_new_commands(self):
        out = self.cli("--help").stdout
        for word in ("run", "resume", "regrade"):
            self.assertIn(word, out)
        self.assertIn("--budget", self.cli("run", "--help").stdout)


if __name__ == "__main__":
    unittest.main()
