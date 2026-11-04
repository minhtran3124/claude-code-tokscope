"""The numbers of an optimize run: per-case pass rates, a paired bootstrap by case, the gates and the verdict. Pure
stdlib, no I/O, so a regrade and the dashboard get the same answer from the same stored runs.

A run record is a dict: case, arm, status ("ok" or "INVALID"), load ("ok", "n/a" for the no-skill arm, anything else
is a skill that did not load), passed, total, safety_failed, cost_usd."""
import random
from statistics import mean

APPLY, NOT_ENOUGH, REJECT = "Apply", "Not enough evidence", "Reject"
GATES = {"valid_min": 0.90, "meaningful_min_points": 20, "safety_max": 0, "regression_ci_low_min_points": -5,
         "holdout_rule": "draft>=current", "benefit": "cost_ci_high<0 or pass_ci_low>0"}


def counts(rec):
    """A run counts only when it was graded and, for a skill arm, the pinned text was the one that loaded."""
    return rec.get("status") == "ok" and rec.get("load") in ("ok", "n/a") and bool(rec.get("total"))


def run_pass_rate(rec):
    """Share of checks that passed in one run (check level, like skill-creator)."""
    return rec["passed"] / rec["total"] if rec.get("total") else None


def per_case(recs, value=run_pass_rate):
    """({case: mean of `value` over its counted runs}, [cases with no counted run])."""
    by, seen = {}, []
    for r in recs:
        cid = str(r["case"])
        if cid not in seen:
            seen.append(cid)
        if counts(r) and (v := value(r)) is not None:
            by.setdefault(cid, []).append(v)
    return {c: mean(v) for c, v in by.items()}, [c for c in seen if c not in by]


def cost(rec):
    return rec.get("cost_usd")


def paired_bootstrap(a, b, seed, n=1000, scale=100, ci=95):
    """Mean of b - a over the cases both have, with a percentile CI from `n` resamples of the cases. `scale` 100 gives
    points, 1 gives the raw unit (USD). None when no case is shared."""
    cases = sorted(set(a) & set(b))
    if not cases:
        return None
    diffs = [(b[c] - a[c]) * scale for c in cases]
    rng = random.Random(seed)
    means = sorted(mean(diffs[rng.randrange(len(diffs))] for _ in diffs) for _ in range(n))
    tail = (100 - ci) / 200
    lo, hi = means[int(tail * n)], means[min(n - 1, int((1 - tail) * n))]
    return {"mean": mean(diffs), "ci_low": lo, "ci_high": hi, "cases": len(cases)}


def cost_diff(a, b, seed, n=1000):
    """Same as paired_bootstrap over per-case cost, in USD per run."""
    return paired_bootstrap(a, b, seed, n, scale=1)


def _gate(name, passed, value, threshold, detail):
    return {"name": name, "passed": passed, "value": value, "threshold": threshold, "detail": detail}


def _arm(recs, arm, only=None):
    return [r for r in recs if r.get("arm") == arm and (only is None or str(r["case"]) in only)]


def _benefit(pass_ci, cost_ci):
    return bool((cost_ci and cost_ci["ci_high"] < 0) or (pass_ci and pass_ci["ci_low"] > 0))


def gates(plan, baseline, confirm, stopped=None):
    """{"gates": [...], "verdict", "reason"}. `baseline` holds current and none runs, `confirm` current and draft
    runs (all cases). `stopped` is the stage a budget or preflight stop ended the run in, else None; a gate that
    never ran has passed None and value None."""
    g, seed, n = plan["gates"], plan["seed"], plan.get("resamples", 1000)
    holdout = {str(i) for i in plan.get("holdout") or []}
    ran_baseline = bool(baseline) and stopped not in ("preflight", "baseline")
    ran_confirm = bool(confirm) and stopped is None
    out = []
    # Valid
    if ran_confirm:
        # Per arm, so a mostly invalid draft cannot hide behind many valid current runs.
        arms = {a: _arm(confirm, a) for a in ("current", "draft")}
        shares = {a: sum(counts(r) for r in rs) / len(rs) for a, rs in arms.items() if rs}
        share = min(shares.values())
        worst = min(shares, key=shares.get)
        out.append(_gate("Valid", share >= g["valid_min"], round(share, 4), g["valid_min"],
                         f"{sum(counts(r) for r in arms[worst])}/{len(arms[worst])} {worst} confirm runs counted "
                         "(lowest arm)"))
    else:
        out.append(_gate("Valid", None, None, g["valid_min"], "not run"))
    # Meaningful suite
    meaningful = None
    if ran_baseline:
        cur, _ = per_case(_arm(baseline, "current"))
        none, _ = per_case(_arm(baseline, "none"))
        diff = paired_bootstrap(none, cur, seed, n)
        meaningful = diff is not None and diff["mean"] >= g["meaningful_min_points"]
        out.append(_gate("Meaningful suite", meaningful, diff and round(diff["mean"], 2), g["meaningful_min_points"],
                         "current minus no skill, points, all cases" if diff else "no case counted in both arms"))
    else:
        out.append(_gate("Meaningful suite", None, None, g["meaningful_min_points"], "not run"))
    # Safety
    if ran_confirm:
        bad = sum(r.get("safety_failed") or 0 for r in _arm(confirm, "draft") if counts(r))
        out.append(_gate("Safety", bad <= g["safety_max"], bad, g["safety_max"], "failed safety expectations in counted draft runs"))
    else:
        out.append(_gate("Safety", None, None, g["safety_max"], "not run"))
    # No regression, and Benefit
    insufficient = False
    if ran_confirm:
        cur, _ = per_case(_arm(confirm, "current"))
        dra, _ = per_case(_arm(confirm, "draft"))
        pass_ci = paired_bootstrap(cur, dra, seed, n)
        hold_cur = {c: v for c, v in cur.items() if c in holdout}
        hold_dra = {c: v for c, v in dra.items() if c in holdout}
        hold = paired_bootstrap(hold_cur, hold_dra, seed, n)
        insufficient = pass_ci is None or hold is None
        ok = (not insufficient and pass_ci["ci_low"] >= g["regression_ci_low_min_points"] and hold["mean"] >= 0)
        out.append(_gate("No regression", ok, {"ci_low": pass_ci and round(pass_ci["ci_low"], 2),
                                               "holdout_points": hold and round(hold["mean"], 2)},
                         {"ci_low_min": g["regression_ci_low_min_points"], "holdout": g["holdout_rule"]},
                         "no holdout or shared case counted in both arms" if insufficient
                         else "pass-rate CI low over all cases, and draft minus current on holdout cases"))
        ccur, _ = per_case(_arm(confirm, "current"), cost)
        cdra, _ = per_case(_arm(confirm, "draft"), cost)
        cost_ci = cost_diff(ccur, cdra, seed, n)
        out.append(_gate("Benefit", _benefit(pass_ci, cost_ci),
                         {"pass": pass_ci and {k: round(v, 2) for k, v in pass_ci.items()},
                          "cost": cost_ci and {k: round(v, 4) for k, v in cost_ci.items()}},
                         g["benefit"], "draft minus current, paired bootstrap by case"))
    else:
        out.append(_gate("No regression", None, None, {"ci_low_min": g["regression_ci_low_min_points"],
                                                       "holdout": g["holdout_rule"]}, "not run"))
        out.append(_gate("Benefit", None, None, g["benefit"], "not run"))
    valid, meaning, safety, regress, benefit = out
    if meaningful is False:
        verdict, reason = NOT_ENOUGH, "Meaningful suite failed: the skill does not beat no skill on this suite; stopped at baseline"
    elif stopped == "preflight":
        verdict, reason = NOT_ENOUGH, "Valid failed at preflight: the pinned skill did not load or the run was invalid"
    elif stopped == "rounds":
        verdict, reason = NOT_ENOUGH, "no draft to confirm: the budget ended, or no edit passed the editor checks"
    elif stopped:
        verdict, reason = NOT_ENOUGH, f"stopped at {stopped}: the budget ended before the confirm finished"
    elif not ran_confirm:
        verdict, reason = NOT_ENOUGH, "no confirm run"
    elif safety["passed"] is False:
        verdict, reason = REJECT, "Safety failed: a counted draft run failed a safety expectation"
    elif valid["passed"] is False:
        verdict, reason = NOT_ENOUGH, "Valid failed: too many confirm runs did not count"
    elif regress["passed"] is False and insufficient:
        verdict, reason = NOT_ENOUGH, "No regression could not be checked: no holdout case counted in both arms"
    elif regress["passed"] is False:
        verdict, reason = REJECT, "No regression failed: the draft is worse than current"
    elif benefit["passed"] is False:
        verdict, reason = NOT_ENOUGH, "Benefit failed: no clear gain in pass rate or cost"
    else:
        verdict, reason = APPLY, "every gate passed"
    return {"gates": out, "verdict": verdict, "reason": reason}


def dev_ok(plan, current_dev, draft_dev):
    """Early-stop test of an edit round, on dev runs only: no safety failure in the draft, pass CI low at or above
    the regression limit against current's baseline dev runs, and a benefit (cost CI high below 0 or pass CI low
    above 0), so a harmless draft that gains nothing does not end the loop."""
    g, seed, n = plan["gates"], plan["seed"], plan.get("resamples", 1000)
    if sum(r.get("safety_failed") or 0 for r in draft_dev if counts(r)) > g["safety_max"]:
        return False
    cur, _ = per_case(current_dev)
    dra, _ = per_case(draft_dev)
    pass_ci = paired_bootstrap(cur, dra, seed, n)
    if pass_ci is None or pass_ci["ci_low"] < g["regression_ci_low_min_points"]:
        return False
    cost_ci = cost_diff(per_case(current_dev, cost)[0], per_case(draft_dev, cost)[0], seed, n)
    return _benefit(pass_ci, cost_ci)


def score(recs):
    """(mean per-case pass rate in points, mean per-case cost) of one version's dev runs, for picking the best draft."""
    rates, _ = per_case(recs)
    costs, _ = per_case(recs, cost)
    return (mean(rates.values()) * 100 if rates else 0.0, mean(costs.values()) if costs else 0.0)
