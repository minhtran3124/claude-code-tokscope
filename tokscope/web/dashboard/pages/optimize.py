"""The Optimize page: the runs of `tokscope optimize run`, one run's plan, gates, cases with their evidence, editor rounds
and before/after, and the Approve and Reject that call the same code as the CLI. It reads the run files directly
(experiments/skillopt/store.py); a missing or broken file leaves its section empty and never fails the page."""

import html
import json
import math
import os
import re
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .... import paths
from ....core import skills
from ....core.ingest import connect
from ....experiments.skillopt import apply, loop, sandbox, stats, store, suite
from ....features import library, postship
from ...report.widgets import _tok, _usd, skill_chip
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


def _str(v, default=""):
    return v if isinstance(v, str) and v else default


def _usd_or_none(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _count(v):
    return len(v) if isinstance(v, list) else 0


def _text(path, limit=None):
    try:
        t = Path(path).read_text(errors="replace")
    except OSError:
        return ""
    return t[:limit] if limit else t


def _etime_seconds(text):
    """Seconds in a ps `etime` value, [[dd-]hh:]mm:ss."""
    days, _, clock = text.strip().rpartition("-")
    parts = [int(x) for x in clock.split(":")]
    if not 2 <= len(parts) <= 3:
        raise ValueError(text)
    secs = 0
    for x in parts:
        secs = secs * 60 + x
    return int(days or 0) * 86400 + secs


def _started_at(pid):
    """Epoch seconds the process `pid` started: Linux /proc, else `ps -o etime=` (macOS). None when neither works.
    The /proc value moves with a wall-clock step (btime is recomputed from the wall clock on every read); _holder_alive
    uses it only for a lock without start ticks."""
    try:
        ticks = store.start_ticks(pid)
        boot = next(int(ln.split()[1]) for ln in Path("/proc/stat").read_text().splitlines() if ln.startswith("btime"))
        if ticks is not None:
            return boot + ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration):
        pass
    try:
        out = subprocess.run(["ps", "-o", "etime=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout
        return time.time() - _etime_seconds(out)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


CLOCK_SLACK = 10  # seconds the lock may predate its pid's start (tick rounding, small clock steps); the worker writes
# the lock after it starts and never touches it again, so a lock older than that names a pid the OS reused
RUN_MAX_AGE = 24 * 3600  # seconds; with no start time to compare, a lock older than this is a dead run's


def _holder_alive(run):
    """True when run.lock names a live pid that is still the process that wrote it. On Linux the lock carries the
    writer's boot-relative start ticks: the same ticks now mean the same process, whatever the wall clock did since;
    other ticks mean the OS reused the pid. A lock without ticks (macOS, older tokscope) falls back to comparing its
    mtime with the pid's start time: written before that pid started means reused. When the start time cannot be read
    either, a lock younger than RUN_MAX_AGE counts as running (a double click must not pay twice) and an older one as
    stopped (a reused pid must not block for ever)."""
    lock = Path(run) / store.LOCK
    pid, ticks = store._read_lock(lock)
    if not (pid and store._alive(pid)):
        return False
    if ticks is not None:
        now = store.start_ticks(pid)
        if now is not None:
            return now == ticks
    started = _started_at(pid)
    try:
        written = lock.stat().st_mtime
    except OSError:
        return False
    if started is None:
        return time.time() - written < RUN_MAX_AGE
    return written >= started - CLOCK_SLACK


# the list

STOPPED_LINE = "Stopped before confirm"
_RESULTS = {}  # run id -> (verdict.json mtime, result line): the line is computed once per verdict file, never stored in it
_LAST = ("approve", "reject", "revert")


def _decided_at(run, decision):
    """When the latest decision was made: its `at`, else decision.json's mtime, else ''."""
    at = _str(decision.get("at"))
    if at:
        return at
    try:
        return datetime.fromtimestamp((run / apply.DECISION_JSON).stat().st_mtime, timezone.utc).isoformat()
    except OSError:
        return ""


def _bucket(state, verdict, decided):
    """running | decided | needs (an Apply nobody decided) | noaction (Not enough evidence, Reject, Stopped)."""
    if state == "running":
        return "running"
    if decided:
        return "decided"
    return "needs" if verdict == stats.APPLY else "noaction"


def _summary(run):
    plan, verdict, decision = _dict(run / store.PLAN), _dict(run / loop.VERDICT), _dict(run / apply.DECISION_JSON)
    done = (run / loop.VERDICT).is_file()
    state = "done" if done else "running" if _holder_alive(run) else "stopped"
    gates = verdict.get("gates") if isinstance(verdict.get("gates"), list) else []
    label = page_verdict(verdict.get("verdict"), gates)  # a failed gate on an Apply reads Do not apply, as on the run page
    act = _str(decision.get("decision"))
    decided = act if act in _LAST else None
    return {"id": run.name, "skill": _str(plan.get("skill"), run.name), "created": _str(plan.get("created")),
            "state": state, "verdict": verdict.get("verdict"), "label": label, "spent": store.spent(run),
            "budget": _usd_or_none(plan.get("budget_usd")), "decision": _str(decision.get("decision")) or None,
            "decided": decided, "decided_at": _decided_at(run, decision) if decided else "",
            "bucket": _bucket(state, label, decided)}


def _result(run, summary):
    """The one result line of a finished run, built by the run page's number code and cached by verdict.json's mtime.
    The verdict reason when a number is missing; STOPPED_LINE for a run with no verdict that is not running."""
    if summary["state"] == "stopped":
        return STOPPED_LINE
    if summary["state"] != "done":
        return ""
    try:
        mtime = (run / loop.VERDICT).stat().st_mtime
    except OSError:
        return ""
    hit = _RESULTS.get(run.name)
    if hit and hit[0] == mtime:
        return hit[1]
    plan, verdict = _dict(run / store.PLAN), _dict(run / loop.VERDICT)
    recs, _ = _records(run)
    draft = verdict.get("draft_version") if isinstance(verdict.get("draft_version"), str) else None
    label = summary["label"]
    line = summary_sentence(label, headline_numbers(arm_numbers(plan, recs, draft)), verdict.get("reason"))
    if label and line.startswith(f"{label}: "):
        line = line[len(label) + 2:]  # the pill already says the label
    _RESULTS[run.name] = (mtime, line)
    return line


def runs():
    """Every run under the data home, newest first. A folder without plan.json is not a run. Each has its bucket, the
    time of its decision and its one-line `result`."""
    try:
        found = [d for d in store.runs_dir().iterdir() if (d / store.PLAN).is_file()]
    except OSError:
        return []
    out = []
    for d in found:
        r = _summary(d)
        r["result"] = _result(d, r)
        out.append(r)
    return sorted(out, key=lambda r: (r["created"], r["id"]), reverse=True)


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


# the decide block: what the page says in words (pure, so the rule is testable)

DO_NOT_APPLY = "Do not apply"


def page_verdict(verdict, gates):
    """The label the page shows for a stored verdict: a Reject, or an Apply with a failed gate, reads "Do not apply" (the
    stored value stays as it is); Not enough evidence reads as stored even with a failed gate, because the verdict code
    stores it for a failed Valid, Meaningful suite or Benefit gate and Approve stays possible with a reason. None when
    there is no verdict."""
    if not verdict:
        return None
    failed = any(isinstance(g, dict) and g.get("passed") is False for g in gates or [])
    if verdict == stats.REJECT or (failed and verdict == stats.APPLY):
        return DO_NOT_APPLY
    return str(verdict)


def _mean(ci):
    v = ci.get("mean") if isinstance(ci, dict) else None
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def headline_numbers(arms):
    """{"pass", "cost", "tokens"}: (old, new) means of the confirm stage, old = the current arm, new = the draft arm
    (pass in points, cost in USD, tokens per run). A metric is None when an arm or its mean is missing."""
    by = {a["arm"]: a for a in arms or [] if a.get("stage") == "confirm"}
    out = {}
    for key in ("pass", "cost", "tokens"):
        old, new = _mean((by.get("current") or {}).get(key)), _mean((by.get("draft") or {}).get(key))
        out[key] = None if old is None or new is None else (old, new)
    return out


def summary_sentence(label, numbers, reason):
    """`<Label>: pass rate A% to B%, cost per run $X to $Y, tokens per run X to Y.`, or the verdict reason when a number
    is missing (or "" when there is neither)."""
    n = numbers or {}
    if not label or any(n.get(k) is None for k in ("pass", "cost", "tokens")):
        return reason if isinstance(reason, str) else ""
    (p0, p1), (c0, c1), (t0, t1) = n["pass"], n["cost"], n["tokens"]
    return (f"{label}: pass rate {p0:.0f}% to {p1:.0f}%, cost per run {_usd(c0)} to {_usd(c1)}, "
            f"tokens per run {_tok(round(t0))} to {_tok(round(t1))}.")


# the page

def _e(x):
    return html.escape("" if x is None else str(x))


def _time(iso):
    iso = iso if isinstance(iso, str) else ""
    return (f'<time data-ts="{_e(iso)}" data-fmt="dt">{_e(iso[:16].replace("T", " "))} UTC</time>' if iso else "–")


def _state(s):
    return f'<span class="state {_e(s)}">{_e(s)}</span>'


RELATIVE_DAYS = 7  # a run older than this shows its date, not "N d ago"
FILTERS = (("needs", "Needs decision"), ("running", "Running"), ("noaction", "No action"), ("decided", "Decided"))
_BUCKETS = (("needs", "Needs your decision"), ("running", "Running"), ("noaction", "No action needed"), ("decided", "Decided"))


def _when(iso):
    try:
        t = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _ago(iso, now=None):
    """(text, full time) of a time: "just now", "36 min ago", "3 h ago", "2 d ago" up to RELATIVE_DAYS, then the date."""
    t = _when(iso)
    if t is None:
        return "–", ""
    t = t.astimezone(timezone.utc)
    secs = ((now or datetime.now(timezone.utc)) - t).total_seconds()
    if secs < 60:
        text = "just now"
    elif secs < 3600:
        text = f"{int(secs // 60)} min ago"
    elif secs < 86400:
        text = f"{int(secs // 3600)} h ago"
    elif secs <= RELATIVE_DAYS * 86400:
        text = f"{int(secs // 86400)} d ago"
    else:
        text = t.strftime("%Y-%m-%d")
    return text, t.strftime("%Y-%m-%d %H:%M UTC")


def _stamp(iso, now=None):
    """The relative time with its full time on hover, and the clock time beside it."""
    text, full = _ago(iso, now)
    if not full:
        return "–"
    return (f'<span class="ol-when" title="{_e(full)}">{_e(text)}</span> '
            f'<time class="ol-clock" data-ts="{_e(iso)}" data-fmt="hm" title="{_e(full)}">{_e(full[11:])}</time>')


def _pill(r):
    if r["state"] == "running":
        return '<span class="ol-pill run">Running</span>'
    if r["state"] == "stopped":
        return '<span class="ol-pill off">Stopped</span>'
    label = r["label"] or "No verdict"
    cls = {stats.APPLY: "ok", DO_NOT_APPLY: "bad", stats.NOT_ENOUGH: "warn"}.get(label, "off")
    return f'<span class="ol-pill {cls}">{_e(label)}</span>'


def _action(r, now=None):
    href = f'/optimize?run={quote(r["id"], safe="")}'
    if r["bucket"] == "decided":
        word = {"approve": "Approved", "reject": "Rejected", "revert": "Reverted"}[r["decided"]]
        text, full = _ago(r["decided_at"], now)
        return (f'<span class="ol-done" title="{_e(full)}">{word} {_e(text)}</span> '
                f'<a class="btn" href="{href}">Open</a>')
    return f'<a class="{"primary" if r["bucket"] == "needs" else "btn"}" href="{href}">{"Review" if r["bucket"] == "needs" else "Open"}</a>'


def _meter(spent, budget):
    """A short bar of the share of the budget spent, red once all of it is spent; nothing without a budget."""
    if not budget or spent is None:
        return ""
    share = min(max(spent / budget, 0), 1)
    return f'<span class="ol-bar{" full" if share >= 1 else ""}" aria-hidden="true"><i style="width:{share * 100:.0f}%"></i></span>'


def _orow(r, now=None):
    result = f'<p class="ol-result">{_e(r["result"])}</p>' if r["result"] else ""
    return (f'<li class="ol-row">{_pill(r)}<div class="ol-main">{result}<p class="ol-meta">{_stamp(r["created"], now)}'
            f' <span class="ol-spent">{_meter(r["spent"], r["budget"])}{_usd(r["spent"])} of {_usd(r["budget"])}</span></p></div>'
            f'<div class="ol-act">{_action(r, now)}</div></li>')


def _query(flt, skill):
    parts = [f"filter={flt}"] if flt else []
    if skill:
        parts.append(f"skill={quote(skill, safe='')}")
    return "/optimize" + ("?" + "&".join(parts) if parts else "")


def _filter(qs, found):
    """(filter, skill) from the query: an unknown value is ignored."""
    qs = qs if isinstance(qs, dict) else {}
    flt = (qs.get("filter") or [""])[0]
    skill = (qs.get("skill") or [""])[0]
    return (flt if flt in dict(FILTERS) else ""), (skill if any(r["skill"] == skill for r in found) else "")


def _chips_row(found, flt, skill):
    scoped = [r for r in found if not skill or r["skill"] == skill]  # a count is what the chip shows with the skill chosen
    counts = {k: sum(1 for r in scoped if r["bucket"] == k) for k, _ in FILTERS}
    out = []
    for key, name in FILTERS:
        on = flt == key
        out.append(f'<a class="chip" href="{_query("" if on else key, skill)}"{" aria-current=true" if on else ""}>'
                   f'{name} <b>{counts[key]}</b></a>')
    names = list(dict.fromkeys(r["skill"] for r in found))
    out.append(f'<a class="chip" href="{_query(flt, "")}"{"" if skill else " aria-current=true"}>All skills</a>')
    for n in names:
        on = skill == n
        out.append(f'<a class="chip" href="{_query(flt, "" if on else n)}"{" aria-current=true" if on else ""}>{_e(n)}</a>')
    return f'<nav class="ol-chips" aria-label="Filter runs">{"".join(out)}</nav>'


def _empty():
    return ('<div class="empty"><b>No runs yet</b>Start one from a skill in the <a href="/library">Library</a> (it shows a cost '
            'estimate first), or run <code>tokscope optimize run &lt;skill&gt; --budget 2</code>.</div>')


def _runs_list(found, notice="", qs=None, now=None):
    if not found:
        return f'{notice}<section class="card"><h2 class="sec">Optimize runs</h2>{_empty()}</section>'
    flt, skill = _filter(qs, found)
    need = [r for r in found if r["bucket"] == "needs" and (not skill or r["skill"] == skill)]  # newest first, in the chosen skill
    n = len(need)
    review = (f'<a class="primary" href="/optimize?run={quote(need[0]["id"], safe="")}">Review newest</a>' if need else "")
    names = list(dict.fromkeys(r["skill"] for r in found))
    facts = (f'{len(found)} run{"s" * (len(found) != 1)} · {_usd(sum(r["spent"] or 0 for r in found))} spent · '
             f'{len(names)} skill{"s" * (len(names) != 1)}')
    head = (f'<section class="card ol-top"><div><h2 class="sec">{n} run{"s" * (n != 1)} {"need" if n != 1 else "needs"} your decision'
            if n else '<section class="card ol-top"><div><h2 class="sec">No runs need your decision')
    head += f'</h2><p class="note">{facts}</p></div>{review}</section>'
    groups = []
    for name in names:
        if skill and name != skill:
            continue
        subs = []
        for key, title in _BUCKETS:
            if flt and key != flt:
                continue
            rs = [r for r in found if r["skill"] == name and r["bucket"] == key]
            if rs:
                subs.append(f'<h4 class="ol-sub">{title} <span>{len(rs)}</span></h4><ul class="ol-rows">'
                            + "".join(_orow(r, now) for r in rs) + "</ul>")
        if subs:
            groups.append(f'<section class="card ol-group"><h3 class="ol-skill">{skill_chip(name)}</h3>{"".join(subs)}</section>')
    body = "".join(groups) or '<div class="empty"><b>No runs match</b>Clear a filter above to see the others.</div>'
    return f'{notice}{head}{_chips_row(found, flt, skill)}{body}'


def _plain(v):
    """A value as words for a cell: no JSON."""
    if isinstance(v, dict):
        return ", ".join(f"{k} {_plain(x)}" for k, x in v.items()) or "–"
    if isinstance(v, list):
        return ", ".join(_plain(x) for x in v) or "–"
    return "–" if v is None else "yes" if v is True else "no" if v is False else str(v)


def _num_or_none(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _signed(x, fmt):
    return ("+" if x > 0 else "-" if x < 0 else "") + fmt(abs(x))


def _gate_found(g):
    """One plain sentence for what a gate found, from its stored value; the stored detail when the value is not as expected."""
    name, val, detail = g.get("name"), g.get("value"), _str(g.get("detail"))
    if g.get("passed") is None:
        return "Not run." + (f" {detail[0].upper() + detail[1:]}." if detail and detail != "not run" else "")
    if name == "Valid" and _num_or_none(val) is not None:
        return f"{val * 100:.0f}% of the runs counted in the weaker arm."
    if name == "Meaningful suite" and _num_or_none(val) is not None:
        return f"The skill scores {val:+.1f} points against no skill."
    if name == "Safety" and _num_or_none(val) is not None:
        return f"{val:g} safety check{'s' * (val != 1)} failed in the draft."
    if name == "No regression" and isinstance(val, dict):
        lo, ho = _num_or_none(val.get("ci_low")), _num_or_none(val.get("holdout_points"))
        if lo is not None and ho is not None:
            return f"Worst likely change {lo:+.1f} points; the holdout cases changed {ho:+.1f} points."
    if name == "Benefit" and isinstance(val, dict):
        pm, cm = _mean(val.get("pass")), _mean(val.get("cost"))
        if pm is not None and cm is not None:
            return f"Pass rate {pm:+.1f} points and cost per run {_signed(cm, _usd)} against the current version."
    return (detail[0].upper() + detail[1:] + ".") if detail else "–"


def _gate_rule(g):
    """The gate's threshold in words."""
    name, th = g.get("name"), g.get("threshold")
    if name == "Valid" and _num_or_none(th) is not None:
        return f"At least {th * 100:.0f}% of runs count."
    if name == "Meaningful suite" and _num_or_none(th) is not None:
        return f"At least {th:g} points above no skill."
    if name == "Safety" and _num_or_none(th) is not None:
        return f"At most {th:g} failed safety checks."
    if name == "No regression" and isinstance(th, dict) and _num_or_none(th.get("ci_low_min")) is not None:
        return f"Worst likely change no lower than {th['ci_low_min']:g} points, and holdout not worse than current."
    if name == "Benefit" and th:
        return "Cost clearly lower, or pass rate clearly higher."
    return _plain(th)


def _gate_pill(passed):
    return ('<span class="pill">not run</span>' if passed is None else '<span class="pill ok">pass</span>' if passed
            else '<span class="pill bad">FAIL</span>')


def _gates_section(d):
    if not d["gates"]:
        return ""
    rows = "".join(f'<tr><td class="nw">{_e(g.get("name"))}</td>'
                   f'<td>{_gate_pill(g.get("passed"))}</td>'
                   f'<td>{_e(_gate_found(g))}</td><td>{_e(_gate_rule(g))}</td></tr>' for g in d["gates"])
    return ('<section class="card" id="gates"><h2 class="sec">Gates</h2><div class="scroll"><table class="gtable"><thead><tr>'
            f'<th>Gate</th><th>Result</th><th>What it found</th><th>Rule</th></tr></thead><tbody>{rows}</tbody></table></div></section>')


def _row(anchor, title, fact, body, opened=False):
    """A collapsed one-line row: the title and its key fact, the body behind it."""
    return (f'<details class="more" id="{anchor}"{" open" if opened else ""}><summary><span class="ttl">{title}</span>'
            f'<span class="note">{fact}</span></summary>{body}</details>')


def _settings_row(d):
    p, s = d["plan"], d["summary"]
    cap = _usd_or_none(p.get("per_run_cap_usd"))
    facts = [("Skill", f"<code>{_e(p.get('skill'))}</code>"), ("State", _state(s["state"])), ("Started", _time(s["created"])),
             ("Model", _e(p.get("model"))), ("Runs per case and arm", _e(p.get("runs"))),
             ("Cases", f"{_count(p.get('dev'))} dev · {_count(p.get('holdout'))} holdout"),
             ("Budget", f"{_usd(s['spent'])} spent of {_usd(_usd_or_none(p.get('budget_usd')))}" + (f" · {_usd(cap)} at most per call" if cap else "")),
             ("Versions", ", ".join(f"<code>{_e(v)}</code>" for v in d["versions"]) or "–"),
             ("Measured version", f"<code>{_e(p.get('base_fingerprint'))}</code>")]
    fact = f"{_e(p.get('model') or 'model unknown')}, {_usd(s['spent'])} spent of {_usd(_usd_or_none(p.get('budget_usd')))}"
    return _row("plan", "Run settings", fact, '<dl class="ids">' + "".join(f"<dt>{a}</dt><dd>{b}</dd>" for a, b in facts) + "</dl>")


def _trigger_row(d):
    t = d["verdict"].get("trigger")
    if not (isinstance(t, dict) and t):
        return ""
    prompts = t.get("prompts")
    evidence = ((isinstance(prompts, dict) and any(_num_or_none(x) for x in prompts.values())) or t.get("current") is not None
                or t.get("draft") is not None or t.get("passed") is not None or t.get("reverted") is True)
    fact = _e(": ".join(x for x in (_str(t.get("status")), _str(t.get("reason"))) if x) or "no detail")
    keys = ("status", "reason", "prompts", "current", "draft", "passed", "reverted") if evidence else ("status", "reason")
    body = '<dl class="ids">' + "".join(f"<dt>{k}</dt><dd>{_e(_plain(t.get(k)))}</dd>" for k in keys if k in t) + "</dl>"
    return _row("trigger", "Trigger check", fact, body, opened=evidence)


def _raw_row(d):
    v = d["verdict"]
    if not v and not d["gates"]:
        return ""
    dump = lambda x: _e(json.dumps(x, indent=2, sort_keys=True))
    parts = (("Gates", d["gates"]), ("Verdict", {k: x for k, x in v.items() if k not in ("gates", "trigger")}),
             ("Trigger check", v.get("trigger")))
    body = "".join(f'<h4 class="sub3">{n}</h4><pre class="src">{dump(x)}</pre>' for n, x in parts)
    return _row("raw", "Raw values", "the gates, the verdict and the trigger check as stored", body)


def _expectations(r):
    items = "".join(f'<li class="{"ok" if e.get("passed") else "bad"}">{"✓" if e.get("passed") else "✕"} {_e(e.get("text"))} '
                    f'<span class="note">{_e(e.get("evidence"))}</span></li>' for e in r["expectations"])
    why = "" if stats.counts(r) else f'<p class="note">Does not count: {_e(r.get("reason") or r.get("status") or "not loaded")}.</p>'
    answer = (f'<details class="more"><summary><span class="ttl">Answer</span></summary><pre class="src">{_e(r["answer"])}</pre></details>'
              if r.get("answer") else "")
    return f'{why}<ul class="plain">{items}</ul>{answer}'


def _cases_row(d):
    if not d["cases"]:
        return _row("cases", "Cases", "no cases in the plan", "")
    label = {"dev": "Dev cases", "holdout": "Holdout cases"}
    n = {sp: len([c for c in d["cases"] if c["split"] == sp]) for sp in label}
    out = ['<p class="note">Checks passed over checks run, per arm. '
           'Open a case for each check and the evidence the grader found. Baseline: current and no skill. Confirm: current and the draft.</p>']
    if d["skipped"]:
        out.append(f'<p class="warn">{d["skipped"]} result{"s" * (d["skipped"] != 1)} could not be read and {"are" if d["skipped"] != 1 else "is"} left out.</p>')
    for split in ("dev", "holdout"):
        mine = [c for c in d["cases"] if c["split"] == split]
        if not mine:
            continue
        out.append(f'<h3 class="sub3">{label[split]} ({len(mine)})</h3>')
        for c in mine:
            counts = []
            blocks = []
            for g in c["groups"]:
                tot = [(r["passed"] or 0, r["total"] or 0) for r in g["runs"] if stats.counts(r)]
                counts.append(f'{_e(g["stage"])} {_e(g["arm"])} {sum(p for p, _ in tot)}/{sum(t for _, t in tot)}')
                for r in g["runs"]:
                    blocks.append(f'<h4 class="sub3">{_e(g["stage"])} · {_e(g["arm"])} · run {r["i"] + 1} · '
                                  f'{r["passed"] if r["passed"] is not None else "–"}/{r["total"] if r["total"] is not None else "–"}</h4>'
                                  + _expectations(r))
            out.append(f'<details class="more"><summary><span class="ttl">{_e(c["case"])}</span>'
                       f'<span class="note">{" · ".join(counts) or "no results"}</span></summary>{"".join(blocks)}</details>')
    total = len(d["cases"])
    return _row("cases", "Cases", f"{total} case{'s' * (total != 1)}, {n['dev']} dev, {n['holdout']} holdout", "".join(out))


def _rounds_row(d):
    if not d["rounds"]:
        return _row("editor", "Editor rounds", "the editor did not run", '<p class="note">The editor did not run.</p>')
    items = []
    for r in d["rounds"]:
        word = "accepted" if r["accepted"] else "rejected" if r["accepted"] is False else "unknown"
        score = (f' · dev score {r["score"][0]:.0f} points, {_usd(r["score"][1])} per case' if r["score"] else "")
        items.append(f'<li><b>Round {r["round"]}</b> {_state("done" if r["accepted"] else "stopped")} {word}'
                     f'{" · became the draft" if r["draft"] else ""}{score}<br>'
                     f'<span>{_e(r["hypothesis"]) or "<i>no hypothesis</i>"}</span>'
                     + (f'<br><span class="note">{_e(r["reason"])}</span>' if r["reason"] else "") + "</li>")
    n = len(d["rounds"])
    won = next((r["round"] for r in d["rounds"] if r["draft"]), None)
    fact = f"{n} round{'s' * (n != 1)}, " + (f"round {won} became the draft" if won else "no round became the draft")
    return _row("editor", "Editor rounds", fact, '<p class="note">An accepted round that lost on its dev '
                f'score has no reason of its own: its score is the reason.</p><ul class="plain">{"".join(items)}</ul>')


def _num(ci, fmt):
    return "–" if not ci else f'{fmt(ci["mean"])} <span class="note">[{fmt(ci["ci_low"])}, {fmt(ci["ci_high"])}]</span>'


def _diff_section(d):
    if not d["draft"]:
        return ('<section class="card" id="diff"><h2 class="sec">What changed</h2><p class="note">No draft was made, so there is '
                'nothing to compare. The editor rounds below say why.</p></section>')
    won = next((r for r in d["rounds"] if r["draft"]), None)
    why = f'<p class="note">Editor\'s reason: {_e(won["hypothesis"])}</p>' if won and won["hypothesis"] else ""
    files = "".join(f'<section class="card"><h3 class="path">{_e(rel)} <span class="note">{kind}</span></h3>'
                    f'<div class="scroll">{_side_by_side(before, after)}</div></section>' for rel, kind, before, after in d["files"])
    return (f'<section class="card" id="diff"><h2 class="sec">What changed</h2><p class="note">{len(d["files"])} file'
            f'{"s" * (len(d["files"]) != 1)} changed between <code>v0</code> and <code>{_e(d["draft"])}</code>.</p>{why}</section>{files}')


def _change_section(d, title, anchor, left, right, names):
    """A table of one pair of arms, three metrics, with a Change column (right minus left)."""
    pick = lambda stage, arm: next((a for a in d["arms"] if (a["stage"], a["arm"]) == (stage, arm)), None)
    a, b = pick(*left), pick(*right)
    if not (a and b):
        return ""
    metrics = (("Pass rate", "pass", lambda x: f"{x:.1f}%", lambda x: f"{x:.1f} points"),
               ("Cost per run", "cost", _usd, _usd), ("Tokens per run", "tokens", lambda x: _tok(round(x)), lambda x: _tok(round(x))))
    rows = []
    for label, key, cell, delta in metrics:
        x, y = _mean(a[key]), _mean(b[key])
        change = "–" if x is None or y is None else _signed(y - x, delta)
        rows.append(f'<tr><td>{label}</td><td>{_num(a[key], cell)}</td><td>{_num(b[key], cell)}</td><td>{_e(change)}</td></tr>')
    return (f'<section class="card" id="{anchor}"><h2 class="sec">{title}</h2><p class="note">Per arm, the mean per run over cases with '
            f'a 95% interval (bootstrap by case, the plan\'s seed). Counted runs: {a["counted"]} of {a["runs"]} and {b["counted"]} of '
            f'{b["runs"]}. Change is {names[1]} minus {names[0]}.</p><div class="scroll"><table><thead><tr><th></th><th>{names[0]}</th>'
            f'<th>{names[1]}</th><th>Change</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>')


def _rows_section(d):
    rows = [_cases_row(d), _rounds_row(d), _trigger_row(d), _settings_row(d), _raw_row(d)]
    return f'<section class="card runrows">{"".join(rows)}</section>'


def _post_ship_section(conn, d):
    """Real sessions: the old and the new version side by side, only for an approved run."""
    got = conn is not None and postship.approved(conn, d["id"])
    if not got:
        return ""
    skill, old, new, at = got
    try:
        sides = postship.post_ship(conn, skill, old, new, at)
    except (ValueError, TypeError):
        return ('<section class="card" id="postship"><h2 class="sec">Real sessions</h2><p class="warn" role="note">'
                "The numbers from your sessions could not be read for this approve (its time or versions look malformed).</p></section>")
    o, n = sides["old"], sides["new"]
    dash = lambda v, f: "–" if v is None else f(v)
    rows = "".join(f"<tr><td>{label}</td><td>{dash(o[key], f)}</td><td>{dash(n[key], f)}</td></tr>" for label, key, f in (
        ("Loads", "loads", str), ("Median tokens per load", "tokens_median", lambda x: _tok(round(x))),
        ("Median cost per load", "cost_median", _usd), ("Error rate", "error_rate", lambda x: f"{x * 100:.0f}%")))
    notes = "".join(f'<p class="warn" role="note">Only {side["loads"]} load{"s" * (side["loads"] != 1)} on the {name} version: '
                    "too few to compare.</p>" for name, side in (("old", o), ("new", n)) if side["few"])
    return ('<section class="card" id="postship"><h2 class="sec">Real sessions</h2><p class="note">From your own sessions after the approve. '
            "Counts only loads of these two versions; loads after a later edit and tokscope's own bench runs are left out. "
            "Tokens and cost are the turn after a load; a turn with several loads counts once.</p>"
            f'<div class="scroll"><table><thead><tr><th></th><th>Old <code>{_e(str(old)[:8])}</code></th>'
            f'<th>New <code>{_e(str(new)[:8])}</code></th></tr></thead><tbody>{rows}</tbody></table></div>{notes}</section>')


def _report(d, decide, post=""):
    s = d["summary"]
    head = (f'<div class="pghead runhead"><p class="crumb"><a href="/optimize">Optimize</a> / <code>{_e(d["id"])}</code></p>'
            f'<h1>{_e(d["plan"].get("skill") or d["id"])} {_state(s["state"])}</h1></div>')
    return (head + decide + _diff_section(d) + _gates_section(d)
            + _change_section(d, "Draft vs current", "draftvs", ("confirm", "current"), ("confirm", "draft"), ("Current", "Draft"))
            + _change_section(d, "Skill vs no skill", "skillvs", ("baseline", "none"), ("baseline", "current"), ("No skill", "Skill"))
            + _rows_section(d) + post)


def page_optimize(conn, qs, level):
    if level != "full":
        return (f'<div class="empty"><b>Run text is hidden</b>The Optimize page shows skill text, answers and evidence at the full '
                f'level only (now {level}).</div>')
    pick = (qs.get("run") or [""])[0]
    notice = ""
    if pick:
        try:
            d = load(pick)
        except ValueError:
            notice = f'<p class="warn" role="note">There is no run <code>{_e(pick)}</code>.</p>'
        else:
            return _report(d, _decide_block(conn, d), _post_ship_section(conn, d))
    return _runs_list(runs(), notice, qs)


# deciding

_DECIDE_LOCK = threading.Lock()  # every approve and reject of this server one at a time (see decide)


def approve_check(run):
    """(HTTP code, why not or None, whether a reason is needed): what Approve may do for this run. 400 for a run that
    cannot be approved at all, 409 for one that is already approved."""
    v = _dict(Path(run) / loop.VERDICT)
    kind = v.get("verdict")
    if not kind:
        return 400, "no verdict yet: the run has not finished", False
    if kind == stats.REJECT:
        return 400, f"the verdict is {stats.REJECT} ({v.get('reason') or 'no reason given'}); nothing to apply", False
    if kind not in (stats.APPLY, stats.NOT_ENOUGH):
        return 400, f"unknown verdict {kind!r}", False
    if not (v.get("draft_version") and v.get("draft_fingerprint")):
        return 400, "no draft to apply", False
    last = apply._latest_applied(run)
    if last and last.get("decision") == "approve":
        return 409, "this run is already approved; `tokscope optimize revert` undoes it", False
    return 200, None, kind == stats.NOT_ENOUGH


def owner_root(conn, skill, want, loose=False):
    """(project root, skill dict, None) of the one skill folder named `skill` whose fingerprint is in `want`; the root is
    what `cwd` must be for the optimize code to find that folder (the home folder for a personal skill). A run stores
    only the skill's name, so the fingerprint tells same-named skills apart. (None, None, why) when none or several
    match. `loose` (a reject, which records and changes nothing) falls back to the only skill of that name, else HOME."""
    found = [k for k in library.discover(conn) if k["dir"] == skill]
    hits = [k for k in found if skills.fingerprint(k["folder"]) in want]
    if len(hits) == 1 or (loose and not hits and len(found) == 1):
        k = hits[0] if hits else found[0]
        return (Path.home() if k["scope"] == "personal" else k["folder"].parents[2]), k, None
    if loose:
        return Path.home(), None, None
    where = ", ".join(str(k["folder"]) for k in (hits or found)) or "no skill folder"
    return None, None, (f"{skill}: cannot tell which skill folder this run measured ({'several match' if hits else 'none matches'} "
                        f"the measured version; checked {where}); use `tokscope optimize approve` from the project")


def decide(db, run_id, act, body):
    """(HTTP code, JSON) of POST optimize/<run>/approve|reject. One at a time: store.acquire lets a holder with the same
    pid take a lock over, so two requests of this server would otherwise both write the skill."""
    reason = body.get("reason")
    reason = reason.strip() if isinstance(reason, str) else ""
    try:
        run = store.find_run(run_id)
    except ValueError:
        return 404, {"error": f"no run {run_id!r}"}
    with _DECIDE_LOCK:
        skill = _dict(run / store.PLAN).get("skill")
        v = _dict(run / loop.VERDICT)
        want = {f for f in (v.get("base_fingerprint"), v.get("draft_fingerprint"), _dict(run / store.PLAN).get("base_fingerprint")) if f}
        if act == "approve":
            code, why, need = approve_check(run)
            if why:
                return code, {"error": why}
            if need and not reason:
                return 400, {"error": f"the verdict is {stats.NOT_ENOUGH}: give a reason to approve it anyway"}
        conn = connect(db)
        try:
            root, _, why = owner_root(conn, skill, want, loose=act == "reject")
        finally:
            conn.close()
        if root is None:
            return 409, {"error": why}
        try:
            record = (apply.approve if act == "approve" else apply.reject)(run_id, reason or None, cwd=str(root))
        except ValueError as e:  # a refusal (apply.Refused) or a lock (store.LockError): the skill is unchanged
            return 409, {"error": str(e)}
        except OSError as e:
            return 500, {"error": f"{type(e).__name__}: {e}"}
        return 200, record


def _git_note(k):
    if not k:
        return "The installed skill is not at the version this run measured, so Approve will refuse."
    top = apply._toplevel(k["folder"])
    if not top:
        return "This skill is not in git: no commit is made. tokscope keeps the old version, and `tokscope optimize revert` undoes the approve."
    branch = apply._git(top, "symbolic-ref", "-q", "--short", "HEAD").stdout.strip()
    return (f"Approve commits only this skill's files on the git branch <code>{_e(branch)}</code>." if branch
            else "Git is on a detached HEAD, so Approve will refuse; check out a branch first.")


def _decision_box(d):
    dec = d["decision"]
    if not dec:
        return ""
    word = {"approve": "Approved", "reject": "Rejected", "revert": "Reverted"}.get(dec.get("decision"), "Decided")
    cls = "ok" if dec.get("decision") == "approve" else "off"
    detail = [f"{_time(dec.get('at'))}"]
    if dec.get("reason"):
        detail.append(f"reason: {_e(dec['reason'])}")
    if dec.get("decision") != "reject" and dec.get("new_fingerprint"):
        detail.append(f"<code>{_e(dec.get('old_fingerprint'))}</code> → <code>{_e(dec['new_fingerprint'])}</code>")
    if dec.get("commit_sha"):
        detail.append(f"commit <code>{_e(dec['commit_sha'][:10])}</code>")
    still = (dec.get("decision") == "reject" and (apply._latest_applied(d["run"]) or {}).get("decision") == "approve")
    note = ('<span class="warn">An earlier approve is still applied: the skill was not changed back. '
            f'Run <code>tokscope optimize revert {_e(d["id"])}</code> to undo it.</span>' if still else "")
    return f'<div class="outcome {cls}"><b>{word}</b><span>{" · ".join(detail)}</span>{note}</div>'


FEW_CASES = 5  # fewer cases than this is thin evidence


def _tiles(numbers):
    """The three headline numbers as "A to B" tiles; "-" for a number that is not there."""
    fmt = {"pass": lambda x: f"{x:.0f}%", "cost": _usd, "tokens": lambda x: _tok(round(x))}
    out = []
    for key, name in (("pass", "Pass rate"), ("cost", "Cost per run"), ("tokens", "Tokens per run")):
        v = (numbers or {}).get(key)
        text = "-" if v is None else f"{fmt[key](v[0])} to {fmt[key](v[1])}"
        out.append(f'<div class="num"><span class="k">{name}</span><b>{_e(text)}</b></div>')
    return f'<div class="nums">{"".join(out)}</div>'


def _chips(gates):
    """One chip per gate, failed first, then not run, then passed."""
    ranked = sorted(gates, key=lambda g: {False: 0, True: 2}.get(g.get("passed"), 1) if isinstance(g.get("passed"), bool) else 1)
    return ('<ul class="gchips" aria-label="Gates">' + "".join(
        f'<li class="gchip {"bad" if g.get("passed") is False else "ok" if g.get("passed") else "off"}">'
        f'{"✕" if g.get("passed") is False else "✓" if g.get("passed") else "–"} {_e(g.get("name"))}</li>' for g in ranked)
        + "</ul>") if ranked else ""


def _decide_block(conn, d):
    """The first block of a run: verdict, one sentence, three numbers, gate chips, a caution for few cases, then the
    reason field with Approve and Reject. A run with no verdict gets a neutral block and no Approve or Reject."""
    v = d["verdict"]
    stored = v.get("verdict")
    label = page_verdict(stored, d["gates"])
    cases = _count(d["plan"].get("dev")) + _count(d["plan"].get("holdout"))
    if not stored:
        return ('<section class="card decideblock" id="decide-card"><h2 class="sec">Decide</h2>' + _decision_box(d)
                + '<div class="outcome off"><b>No verdict yet</b><span>The run has not finished. Resume it with '
                f'<code>tokscope optimize resume {_e(d["id"])}</code>.</span></div>' + _tiles(None) + "</section>")
    cls = {"Apply": "ok", DO_NOT_APPLY: "bad"}.get(label, "off")
    sentence = summary_sentence(label, headline_numbers(d["arms"]), v.get("reason"))
    code, why, need = approve_check(d["run"])
    want = {f for f in (v.get("base_fingerprint"), v.get("draft_fingerprint"), d["plan"].get("base_fingerprint")) if f}
    _, k, _ = owner_root(conn, d["plan"].get("skill"), want)
    blocked = "" if code == 200 else f' disabled data-block="1" title="{_e(why)}"'
    approve = (f'<button type="button" class="primary" data-opt-act="approve"{blocked or (" disabled" if need else "")}>'
               'Approve</button>')
    reason = _str(v.get("reason"))
    why_line = f'<p class="note vreason">{_e(reason)}</p>' if reason and reason != sentence else ""
    few = (f'<p class="warn" role="note">Only {cases} case{"s" * (cases != 1)} ran; fewer than {FEW_CASES} is thin evidence.</p>'
           if cases < FEW_CASES else "")
    block = f'<p class="note">Approve is off: {_e(why)}.</p>' if why else ""
    word = "Reason (required to approve)" if need else "Reason (optional)"
    return (f'<section class="card decideblock" id="decide-card"><h2 class="sec">Decide</h2><div class="vhead"><span class="vbadge {cls}">'
            f'{_e(label)}</span></div><p class="vsum">{_e(sentence)}</p>' + _tiles(headline_numbers(d["arms"])) + _chips(d["gates"])
            + few + why_line + _decision_box(d) + block
            + f'<div class="optform" id="decide" data-run="{_e(d["id"])}" data-need="{int(need)}">'
            + f'<label class="wide">{word}<textarea id="opt-reason" rows="1"{" required" if need else ""}></textarea></label>'
            + f'<p class="acts">{approve}<button type="button" class="btn danger" data-opt-act="reject">Reject</button></p>'
            + f'<p class="note">{_git_note(k)} Reject records your decision and never changes the skill.</p>'
            + '<p class="err" id="opt-err" hidden></p></div></section>')


# starting a run

MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\[\]-]{0,63}$")
MAX_START_BUDGET_USD, MAX_START_RUNS = 100.0, 20  # a start from the browser cannot ask for more than this
START_WAIT_S = 20  # the worker prints `run <folder>` right after it locks the plan, before any paid call
_START_LOCK = threading.Lock()


def project_root(k):
    """The folder whose `.claude/skills` holds the skill `k` (what the optimize code takes as cwd): HOME for a personal one."""
    return Path.home() if k["scope"] == "personal" else k["folder"].parents[2]


def _number(body, key, default, whole=False):
    v = body.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or (whole and v != int(v)):
        raise ValueError(f"{key} must be {'a whole ' if whole else 'a '}number")
    return int(v) if whole else float(v)


def plan_start(conn, body):
    """What a start would run, checked with no spend: the skill, its suite and the numbers. ValueError says what is wrong.
    The worker and opt_applied name a skill by its folder name (`dir`), which the Library name can differ from."""
    k = next((k for k in library.discover(conn) if k["id"] == body.get("skill")), None)
    if not k:
        raise ValueError("no such skill")
    if k["origin"] != "mine":
        raise ValueError("installed skills cannot be optimized: the next update of the installer would undo the change")
    budget, runs_, model = _number(body, "budget", 2.0), _number(body, "runs", 3, whole=True), body.get("model") or "sonnet"
    if not budget > 0:
        raise ValueError("budget must be above 0")
    if budget > MAX_START_BUDGET_USD:
        raise ValueError(f"budget must be at most {MAX_START_BUDGET_USD:g}")
    if runs_ < 1:
        raise ValueError("runs must be at least 1")
    if runs_ > MAX_START_RUNS:
        raise ValueError(f"runs must be at most {MAX_START_RUNS}")
    if not isinstance(model, str) or not MODEL.match(model):
        raise ValueError("model must be a model name such as sonnet")
    root = project_root(k)
    live = suite.load(k["dir"], str(root))
    if live.problems:
        raise ValueError("suite has problems: " + "; ".join(live.problems))
    try:
        dev, hold = suite.split(live, write=False)
    except suite.Refused as e:
        raise ValueError(str(e)) from None
    return {"skill": k["id"], "name": k["dir"], "root": root, "budget": budget, "runs": runs_, "model": model,
            "cases": len(live.cases), "dev": len(dev), "holdout": len(hold)}


def _cost_per_call(skill):
    """(median cost of a paid call, how many) over the ledgers of earlier runs of this skill, or (None, 0)."""
    costs = []
    try:
        for d in store.runs_dir().iterdir():
            if _dict(d / store.PLAN).get("skill") == skill:
                costs += [l["cost_usd"] for l in store.lines(d) if l.get("kind") == "run"
                          and isinstance(l.get("cost_usd"), (int, float)) and l["cost_usd"] > 0]
    except OSError:
        pass
    return (statistics.median(costs), len(costs)) if costs else (None, 0)


def estimate(p):
    """The size of a run, with no spend and no claude call (loop.preflight pays for its own). The call counts leave out the
    preflight and the trigger check, so they are about, not exact; the budget is the hard stop."""
    base = 2 * p["cases"] * p["runs"] * 2  # baseline and confirm, two arms each
    most = base + loop.MAX_ROUNDS * (p["dev"] * p["runs"] + 1)
    per, n = _cost_per_call(p["name"])
    cap = min(sandbox.MAX_BUDGET_USD, p["budget"])
    lines = [f"About {base} paid runs for the baseline and the confirm, up to about {most} with {loop.MAX_ROUNDS} edit rounds "
             f"({p['cases']} cases, {p['runs']} run{'s' * (p['runs'] != 1)} each, model {p['model']})."]
    if per is None:
        lines.append("The cost per run is unknown: no earlier run of this skill has a ledger to take it from.")
    else:
        lines.append(f"About ${base * per:.2f} to ${most * per:.2f} at ${per:.3f} a run (median of {n} earlier runs of this skill).")
    lines.append(f"Each call is capped at ${cap:.2f}. The run stops before it passes ${p['budget']:.2f}, whatever the estimate says.")
    return {"calls": base, "calls_max": most, "cases": p["cases"], "runs": p["runs"], "model": p["model"], "budget": p["budget"],
            "per_call_cap": cap, "cost_per_call": per, "cost": per and base * per, "cost_max": per and most * per,
            "samples": n, "lines": lines}


def _command(p):
    return [sys.executable, "-u", "-m", "tokscope.cli", "optimize", "run", "--budget", str(p["budget"]),
            "--runs", str(p["runs"]), "--model", p["model"], "--", p["name"]]  # "--": a folder name cannot act as a flag


def _stop(proc):
    try:
        os.killpg(proc.pid, signal.SIGTERM)  # the worker leads its own session
    except (AttributeError, OSError):
        proc.terminate()


def _tail(path, n=8):
    try:
        lines = [l for l in Path(path).read_text(errors="replace").splitlines() if l.strip()]
    except OSError:
        return ""
    return " | ".join(lines[-n:])


def _first_line(path):
    try:
        with open(path, errors="replace") as fh:
            line = fh.readline()
    except OSError:
        return ""
    return line if line.endswith("\n") else ""  # a half-written line is not yet the run folder


def spawn(p):
    """Start `tokscope optimize run` in its own process, as the CLI would, and return the run id it prints first. The
    process outlives this request and the run keeps its own lock. ValueError when it stops before it prints (with its
    last stderr lines), RuntimeError when it prints nothing in START_WAIT_S seconds (it is stopped; no paid call began)."""
    work = store.runs_dir().parent
    work.mkdir(parents=True, exist_ok=True)
    fd, log = tempfile.mkstemp(prefix=".worker-", suffix=".log", dir=work)  # files, not pipes: a server stop must not kill the run
    out = None
    ofd = -1
    proc = None
    try:
        ofd, out = tempfile.mkstemp(prefix=".worker-", suffix=".out", dir=work)
        root = str(Path(paths.__file__).resolve().parents[1])
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(x for x in (root, os.environ.get("PYTHONPATH")) if x)}
        proc = subprocess.Popen(_command(p), cwd=str(p["root"]), env=env, stdin=subprocess.DEVNULL, stdout=ofd,
                                stderr=fd, text=True, start_new_session=True)
    except BaseException:
        Path(log).unlink(missing_ok=True)
        if out:
            Path(out).unlink(missing_ok=True)
        raise
    finally:
        os.close(fd)
        if ofd >= 0:
            os.close(ofd)
    try:
        return _await_run(proc, log, out)
    except BaseException:
        if proc.poll() is None:
            _stop(proc)  # no paid worker may run without its run folder linked
        Path(log).unlink(missing_ok=True)
        Path(out).unlink(missing_ok=True)
        raise


def _await_run(proc, log, out):
    # reap it when it ends: an unreaped child still passes os.kill(pid, 0)
    threading.Thread(target=proc.wait, daemon=True).start()
    end = time.monotonic() + START_WAIT_S
    first = ""
    while True:
        done = proc.poll() is not None  # read once more after it ends, so a line written just before exit is seen
        first = _first_line(out)
        if first or done or time.monotonic() >= end:
            break
        time.sleep(0.05)
    line = first.strip()
    if not line.startswith("run "):
        if proc.poll() is None:
            raise RuntimeError(f"the worker printed no run folder in {START_WAIT_S} s; it was stopped before any paid call")
        tail = _tail(log)
        raise ValueError("the worker stopped before it started a run" + (f": {tail}" if tail else ""))
    run = Path(line[4:].strip())
    try:
        found = store.find_run(run.name)
    except ValueError:
        raise RuntimeError(f"the worker named a run folder that is not under the data home: {run}") from None
    os.replace(log, found / "worker.log")  # its stderr stays with the run
    os.replace(out, found / "worker.out")
    return run.name


def start(db, body):
    """(HTTP code, JSON) of POST optimize/start. Without `confirm` it only answers the estimate. With `confirm: true` it
    starts the worker, unless a run of the skill is already going (a double click must not pay twice)."""
    conn = connect(db)
    try:
        p = plan_start(conn, body)
    except ValueError as e:
        return 400, {"error": str(e)}
    finally:
        conn.close()
    est = estimate(p)
    if body.get("confirm") is not True:
        return 200, {"estimate": est}
    with _START_LOCK:
        going = running_for(p["name"])
        if going:
            return 409, {"error": f"a run of {p['name']} is already going", "run": going, "url": f"/optimize?run={going}"}
        try:
            run_id = spawn(p)
        except ValueError as e:
            return 400, {"error": str(e)}
        except (OSError, RuntimeError) as e:
            return 500, {"error": str(e)}
    return 200, {"run": run_id, "url": f"/optimize?run={run_id}", "estimate": est}


# ---- eval suite generation: one paid `claude -p` call in the background, then the owner approves the draft ----

SUITEGEN_BUDGET_USD, SUITEGEN_MAX_USD = 1.0, 10.0  # one call of a few thousand tokens; the cap guards a typo
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _suitegen_log(name):
    return store.runs_dir().parent / f".suitegen-{name}.log"


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def suitegen_status(name):
    """{"state": none | running | done | failed, "lines": last output lines}. A worker prints `exit=<code>` last, so a
    log without it and without a live worker means it was killed."""
    log = _suitegen_log(name)
    try:
        lines = [l for l in log.read_text(errors="replace").splitlines() if l.strip()]
        pid = int(log.with_suffix(".pid").read_text())
    except (OSError, ValueError):
        return {"state": "none", "lines": []}
    exits = [l for l in lines if l.startswith("exit=")]
    body = [l for l in lines if not l.startswith("exit=")][-8:]
    if exits:
        return {"state": "done" if exits[-1] == "exit=0" else "failed", "lines": body}
    return {"state": "running" if _alive(pid) else "failed", "lines": body}


def _skill_of(conn, body):
    k = next((k for k in library.discover(conn) if k["id"] == body.get("skill")), None)
    if not k:
        raise ValueError("no such skill")
    if k["origin"] != "mine" or ":" in k["dir"] or not _NAME.match(k["dir"]):
        raise ValueError("only your own skills can get an eval suite here")
    return k


def suitegen_start(db, body):
    """(HTTP code, JSON) of POST optimize/suite/generate: start the background draft. One at a time per skill."""
    conn = connect(db)
    try:
        k = _skill_of(conn, body)
    except ValueError as e:
        return 400, {"error": str(e)}
    finally:
        conn.close()
    try:
        budget = _number(body, "budget", SUITEGEN_BUDGET_USD)
    except ValueError as e:
        return 400, {"error": str(e)}
    model = body.get("model") or "sonnet"
    if not 0 < budget <= SUITEGEN_MAX_USD:
        return 400, {"error": f"budget must be above 0 and at most {SUITEGEN_MAX_USD:g}"}
    if not isinstance(model, str) or not MODEL.match(model):
        return 400, {"error": "model must be a model name such as sonnet"}
    with _START_LOCK:
        if suitegen_status(k["dir"])["state"] == "running":
            return 409, {"error": f"a draft of {k['dir']} is already being made"}
        log = _suitegen_log(k["dir"])
        log.parent.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, "-u", "-m", "tokscope.cli", "optimize", "suite", "--generate", "--budget", str(budget),
               "--model", model, "--", k["dir"]]
        root = str(Path(paths.__file__).resolve().parents[1])
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(x for x in (root, os.environ.get("PYTHONPATH")) if x)}
        try:
            with open(log, "w") as out:  # a file, not a pipe: a server stop must not kill the call
                proc = subprocess.Popen(["sh", "-c", '"$@"; echo "exit=$?"', "sh", *cmd], cwd=str(project_root(k)), env=env,
                                        stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, text=True,
                                        start_new_session=True)
            log.with_suffix(".pid").write_text(str(proc.pid))
        except OSError as e:
            return 500, {"error": str(e)}
    return 200, {"state": "running"}


def suitegen_state(db, body):
    """(HTTP code, JSON) of POST optimize/suite/status."""
    conn = connect(db)
    try:
        k = _skill_of(conn, body)
    except ValueError as e:
        return 400, {"error": str(e)}
    finally:
        conn.close()
    return 200, suitegen_status(k["dir"])


def suitegen_approve(db, body):
    """(HTTP code, JSON) of POST optimize/suite/approve: copy a passing draft to evals.json. A suite that passes its checks
    is never overwritten; one that does not (no machine checks, bad JSON) is, after its text is kept as evals.previous.json."""
    conn = connect(db)
    try:
        k = _skill_of(conn, body)
        root = str(project_root(k))
        live = suite._folder(k["dir"], root) / "evals" / suite.NAME
        replace = False
        if live.exists():
            try:
                replace = bool(suite.load(k["dir"], root).problems)
            except ValueError:
                replace = True  # not valid JSON, or not an object
        old = live.read_bytes() if replace else None
        path = suite.approve(k["dir"], root, force=replace)
        if old is not None:  # only after the draft passed: a refused approve leaves the old file and any earlier backup alone
            live.with_name("evals.previous.json").write_bytes(old)
    except suite.Refused as e:
        return 400, {"error": str(e)}
    except ValueError as e:
        return 400, {"error": str(e)}
    finally:
        conn.close()
    return 200, {"path": str(path)}
