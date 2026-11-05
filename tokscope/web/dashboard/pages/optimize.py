"""The Optimize page: the runs of `tokscope optimize run`, one run's plan, gates, cases with their evidence, editor rounds
and before/after, and the Approve and Reject that call the same code as the CLI. It reads the run files directly
(experiments/skillopt/store.py); a missing or broken file leaves its section empty and never fails the page."""

import html
import json
import re
import statistics
import threading
from pathlib import Path

from ....core import skills
from ....experiments.skillopt import apply, loop, sandbox, stats, store
from ....features import library
from ...report.widgets import _tok, _usd
from .library import _side_by_side

ARMS = (("baseline", "current"), ("baseline", "none"), ("confirm", "current"), ("confirm", "draft"))
ANSWER_MAX = 4000


def _json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _dict(path):
    v = _json(path)
    return v if isinstance(v, dict) else {}


def _text(path, limit=None):
    try:
        t = Path(path).read_text(errors="replace")
    except OSError:
        return ""
    return t[:limit] if limit else t


def _holder_alive(run):
    pid = store._holder(Path(run) / store.LOCK)
    return bool(pid) and store._alive(pid)


# the list

def _summary(run):
    plan, verdict, decision = _dict(run / store.PLAN), _dict(run / loop.VERDICT), _dict(run / apply.DECISION_JSON)
    done = (run / loop.VERDICT).is_file()
    return {"id": run.name, "skill": plan.get("skill") or run.name, "created": plan.get("created") or "",
            "state": "done" if done else "running" if _holder_alive(run) else "stopped",
            "verdict": verdict.get("verdict"), "spent": store.spent(run), "budget": plan.get("budget_usd"),
            "decision": decision.get("decision")}


def runs():
    """Every run under the data home, newest first. A folder without plan.json is not a run."""
    try:
        found = [d for d in store.runs_dir().iterdir() if (d / store.PLAN).is_file()]
    except OSError:
        return []
    return sorted((_summary(d) for d in found), key=lambda r: (r["created"], r["id"]), reverse=True)


def running_for(skill):
    """The id of a run of `skill` that has no verdict and whose worker is alive, else None."""
    return next((r["id"] for r in runs() if r["skill"] == skill and r["state"] == "running"), None)


# one run

def _record(grading_path):
    """One finished result as store.records builds it, plus the answer. None when a file is missing or broken."""
    folder = Path(grading_path).parent
    try:
        if folder.name.endswith(".tmp") or not (folder / "run.json").is_file():
            return None
        grading, meta = json.loads(Path(grading_path).read_text()), json.loads((folder / "run.json").read_text())
        usage = meta.get("usage") or {}
        return {"stage": folder.parts[-4], "case": folder.parts[-3], "arm": folder.parts[-2], "i": int(folder.name),
                "status": grading.get("status"), "load": meta.get("load"), "passed": grading.get("passed"),
                "total": grading.get("total"), "safety_failed": grading.get("safety_failed") or 0,
                "cost_usd": meta.get("cost_usd"), "reason": grading.get("reason"),
                "tokens": sum(v for v in usage.values() if isinstance(v, (int, float))) or None,
                "expectations": [e for e in grading.get("expectations") or [] if isinstance(e, dict)],
                "answer": _text(folder / "final.md", ANSWER_MAX)}
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _records(run):
    found = sorted(Path(run).glob("results/*/*/*/*/grading.json"))
    recs = [r for r in map(_record, found) if r]
    return recs, len([g for g in found if not g.parent.name.endswith(".tmp")]) - len(recs)


def _ci(by_case, seed, n, scale):
    """mean and 95% CI over cases of one arm: the paired bootstrap of stats against zero, with the plan's seed."""
    return stats.paired_bootstrap({c: 0 for c in by_case}, by_case, seed, n, scale) if by_case else None


def arm_numbers(plan, recs, draft):
    """Per arm of the baseline and confirm stages: runs, counted runs, and pass rate (points), cost (USD) and tokens per
    run as a mean over cases with a 95% CI. The confirm arm named after the draft version is shown as `draft`."""
    seed = plan.get("seed") if isinstance(plan.get("seed"), int) else 0
    n = plan.get("resamples") if isinstance(plan.get("resamples"), int) and plan["resamples"] > 0 else 1000
    out = []
    for stage, arm in ARMS:
        rs = [r for r in recs if r["stage"] == stage and ("draft" if draft and r["arm"] == draft else r["arm"]) == arm]
        if not rs:
            continue
        out.append({"stage": stage, "arm": arm, "runs": len(rs), "counted": sum(stats.counts(r) for r in rs),
                    "pass": _ci(stats.per_case(rs)[0], seed, n, 100),
                    "cost": _ci(stats.per_case(rs, stats.cost)[0], seed, n, 1),
                    "tokens": _ci(stats.per_case(rs, lambda r: r.get("tokens"))[0], seed, n, 1)})
    return out


def case_rows(plan, recs, draft):
    """[{split, case, groups: [{stage, arm, runs}]}] for the dev and holdout cases of the plan, in plan order."""
    out = []
    for split in ("dev", "holdout"):
        ids = plan.get(split)
        for cid in [str(c) for c in ids] if isinstance(ids, list) else []:
            mine = [dict(r, arm="draft" if draft and r["arm"] == draft else r["arm"]) for r in recs
                    if r["case"] == cid and r["stage"] in ("baseline", "confirm")]
            groups = [{"stage": s, "arm": a, "runs": sorted((r for r in mine if (r["stage"], r["arm"]) == (s, a)),
                                                           key=lambda r: r["i"])} for s, a in ARMS]
            out.append({"split": split, "case": cid, "groups": [g for g in groups if g["runs"]]})
    return out


def editor_rounds(run, recs, draft):
    """Each edit round: the editor's hypothesis, whether its edit was accepted and why not, its dev score and whether it
    became the draft. A round that was accepted but lost on dev score has no reason of its own; its score shows why."""
    out, base = [], Path(run) / "rounds"
    try:
        names = sorted((p.name for p in base.iterdir() if p.name.isdigit()), key=int)
    except OSError:
        names = []
    for name in names:
        ed = base / name / "editor"
        res = _dict(ed / "result.json")
        dev = [r for r in recs if r["stage"] == f"r{name}" and r["arm"] == f"v{name}"]
        out.append({"round": int(name), "hypothesis": res.get("hypothesis") or _text(ed / "hypothesis.txt").strip(),
                    "accepted": res.get("accepted"), "reason": res.get("reason"),
                    "score": stats.score(dev) if dev else None, "draft": bool(draft) and draft == f"v{name}"})
    return out


def changed_files(run, draft):
    """[(path, kind, before, after)] between versions/v0 and the draft, SKILL.md first."""
    if not draft:
        return []
    a, b = Path(run) / "versions" / "v0", Path(run) / "versions" / draft
    old, new = {r for r, _ in library.files(a)} if a.is_dir() else set(), {r for r, _ in library.files(b)} if b.is_dir() else set()
    out = []
    for rel in sorted(old | new, key=lambda r: (r != "SKILL.md", r)):
        before, after = _text(a / rel, library.MAX_VIEW) if rel in old else "", _text(b / rel, library.MAX_VIEW) if rel in new else ""
        if rel not in old or rel not in new or before != after:
            out.append((rel, "added" if rel not in old else "removed" if rel not in new else "changed", before, after))
    return out


def load(run_id):
    """Everything the report shows. ValueError (no such run) when the id is not a run."""
    run = store.find_run(run_id)
    plan, verdict, decision = _dict(run / store.PLAN), _dict(run / loop.VERDICT), _dict(run / apply.DECISION_JSON)
    recs, skipped = _records(run)
    draft = verdict.get("draft_version") if isinstance(verdict.get("draft_version"), str) else None
    gates = [g for g in verdict.get("gates") or [] if isinstance(g, dict)] if isinstance(verdict.get("gates"), list) else []
    try:
        versions = sorted(p.name for p in (run / "versions").iterdir() if p.is_dir())
    except OSError:
        versions = []
    return {"run": run, "id": run.name, "plan": plan, "verdict": verdict, "gates": gates, "decision": decision,
            "summary": _summary(run), "draft": draft, "skipped": skipped, "versions": versions,
            "cases": case_rows(plan, recs, draft), "arms": arm_numbers(plan, recs, draft),
            "rounds": editor_rounds(run, recs, draft), "files": changed_files(run, draft)}
