import unittest

from tokscope.experiments.skillopt import stats

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


if __name__ == "__main__":
    unittest.main()
