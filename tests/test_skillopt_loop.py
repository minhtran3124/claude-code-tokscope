import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from tokscope import paths
from tokscope.core import ingest
from tokscope.experiments.skillopt import stats, store, suite

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

    def test_budget_stop_leaves_gates_unrun(self):
        base = arm_recs("current", 4) + arm_recs("none", 0)
        out = stats.gates(PLAN, base, [], stopped="confirm")
        self.assertEqual(out["verdict"], stats.NOT_ENOUGH)
        self.assertTrue(next(g for g in out["gates"] if g["name"] == "Meaningful suite")["passed"])
        self.assertEqual([g["passed"] for g in out["gates"] if g["name"] != "Meaningful suite"], [None] * 4)

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


if __name__ == "__main__":
    unittest.main()
