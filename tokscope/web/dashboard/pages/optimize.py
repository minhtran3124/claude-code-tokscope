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
from pathlib import Path

from .... import paths
from ....core import skills
from ....core.ingest import connect
from ....experiments.skillopt import apply, loop, sandbox, stats, store, suite
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
    """Epoch seconds the process `pid` started: Linux /proc, else `ps -o etime=` (macOS). None when neither works."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
        ticks = int(stat.rsplit(")", 1)[1].split()[19])
        boot = next(int(ln.split()[1]) for ln in Path("/proc/stat").read_text().splitlines() if ln.startswith("btime"))
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
    """True when run.lock names a live pid, unless the lock was written before that pid started: then the OS reused the
    pid for an unrelated process. When the start time cannot be read, a lock younger than RUN_MAX_AGE counts as
    running (a double click must not pay twice) and an older one as stopped (a reused pid must not block for ever)."""
    lock = Path(run) / store.LOCK
    pid = store._holder(lock)
    if not (pid and store._alive(pid)):
        return False
    started = _started_at(pid)
    try:
        written = lock.stat().st_mtime
    except OSError:
        return False
    if started is None:
        return time.time() - written < RUN_MAX_AGE
    return written >= started - CLOCK_SLACK


# the list

def _summary(run):
    plan, verdict, decision = _dict(run / store.PLAN), _dict(run / loop.VERDICT), _dict(run / apply.DECISION_JSON)
    done = (run / loop.VERDICT).is_file()
    return {"id": run.name, "skill": _str(plan.get("skill"), run.name), "created": _str(plan.get("created")),
            "state": "done" if done else "running" if _holder_alive(run) else "stopped",
            "verdict": verdict.get("verdict"), "spent": store.spent(run), "budget": _usd_or_none(plan.get("budget_usd")),
            "decision": _str(decision.get("decision")) or None}


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


# the page

def _e(x):
    return html.escape("" if x is None else str(x))


def _time(iso):
    iso = iso if isinstance(iso, str) else ""
    return (f'<time data-ts="{_e(iso)}" data-fmt="dt">{_e(iso[:16].replace("T", " "))} UTC</time>' if iso else "–")


def _state(s):
    return f'<span class="state {_e(s)}">{_e(s)}</span>'


def _runs_list(found, notice=""):
    if not found:
        body = ('<div class="empty"><b>No optimize runs yet</b>Start one from a skill in the Library (it shows a cost estimate '
                'first), or run <code>tokscope optimize run &lt;skill&gt; --budget 2</code>.</div>')
    else:
        rows = "".join(
            f'<tr><td><a href="/optimize?run={_e(r["id"])}">{_e(r["skill"])}</a></td><td>{_time(r["created"])}</td>'
            f'<td>{_state(r["state"])}</td><td>{_e(r["verdict"] or "–")}</td>'
            f'<td>{_usd(r["spent"])} of {_usd(r["budget"])}</td><td>{_e(r["decision"] or "–")}</td></tr>' for r in found)
        body = ('<div class="scroll"><table><thead><tr><th>Skill</th><th>Started</th><th>State</th><th>Verdict</th>'
                f'<th>Spent</th><th>Decision</th></tr></thead><tbody>{rows}</tbody></table></div>')
    return (f'{notice}<section class="card"><h2 class="sec">Optimize runs</h2><p class="note">Each run measures a draft of a skill '
            f'against the current one. Open a run to read its evidence, then approve or reject it.</p>{body}</section>')


def _plan_section(d):
    p, s = d["plan"], d["summary"]
    cap = _usd_or_none(p.get("per_run_cap_usd"))
    facts = [("Skill", f"<code>{_e(p.get('skill'))}</code>"), ("State", _state(s["state"])), ("Started", _time(s["created"])),
             ("Model", _e(p.get("model"))), ("Runs per case and arm", _e(p.get("runs"))),
             ("Cases", f"{_count(p.get('dev'))} dev · {_count(p.get('holdout'))} holdout"),
             ("Budget", f"{_usd(s['spent'])} spent of {_usd(_usd_or_none(p.get('budget_usd')))}" + (f" · {_usd(cap)} at most per call" if cap else "")),
             ("Versions", ", ".join(f"<code>{_e(v)}</code>" for v in d["versions"]) or "–"),
             ("Measured version", f"<code>{_e(p.get('base_fingerprint'))}</code>")]
    return ('<section class="card" id="plan"><h2 class="sec">Plan</h2><dl class="ids">'
            + "".join(f"<dt>{a}</dt><dd>{b}</dd>" for a, b in facts) + "</dl></section>")


def _value(v):
    return _e(json.dumps(v, sort_keys=True)) if isinstance(v, (dict, list)) else _e("–" if v is None else v)


def _gates_section(d):
    v = d["verdict"]
    if not d["gates"] and not v.get("verdict"):
        return ('<section class="card" id="gates"><h2 class="sec">Gates</h2><p class="note">No verdict yet: the run has not finished '
                f'(resume it with <code>tokscope optimize resume {_e(d["id"])}</code>).</p></section>')
    cls = {stats.APPLY: "ok", stats.REJECT: "bad"}.get(v.get("verdict"), "off")
    head = (f'<div class="outcome {cls}"><b>Verdict: {_e(v.get("verdict") or "unknown")}</b><span>{_e(v.get("reason"))}</span></div>'
            if v.get("verdict") else "")
    rows = "".join(f'<tr><td>{_e(g.get("name"))}</td><td>{"not run" if g.get("passed") is None else "pass" if g.get("passed") else "FAIL"}</td>'
                   f'<td>{_value(g.get("value"))}</td><td>{_value(g.get("threshold"))}</td><td>{_e(g.get("detail"))}</td></tr>'
                   for g in d["gates"])
    table = ('<div class="scroll"><table><thead><tr><th>Gate</th><th>Result</th><th>Value</th><th>Threshold</th><th>Detail</th></tr>'
             f'</thead><tbody>{rows}</tbody></table></div>') if rows else ""
    t = v.get("trigger")
    trig = ""
    if isinstance(t, dict) and t:
        keys = ("status", "reason", "prompts", "current", "draft", "passed", "reverted")
        trig = ('<h3 class="sub3">Trigger check</h3><dl class="ids">'
                + "".join(f"<dt>{k}</dt><dd>{_value(t.get(k))}</dd>" for k in keys if k in t) + "</dl>")
    return f'<section class="card" id="gates"><h2 class="sec">Gates</h2>{head}{table}{trig}</section>'


def _expectations(r):
    items = "".join(f'<li class="{"ok" if e.get("passed") else "bad"}">{"✓" if e.get("passed") else "✕"} {_e(e.get("text"))} '
                    f'<span class="note">{_e(e.get("evidence"))}</span></li>' for e in r["expectations"])
    why = "" if stats.counts(r) else f'<p class="note">Does not count: {_e(r.get("reason") or r.get("status") or "not loaded")}.</p>'
    answer = (f'<details class="more"><summary><span class="ttl">Answer</span></summary><pre class="src">{_e(r["answer"])}</pre></details>'
              if r.get("answer") else "")
    return f'{why}<ul class="plain">{items}</ul>{answer}'


def _cases_section(d):
    if not d["cases"]:
        return '<section class="card" id="cases"><h2 class="sec">Cases</h2><p class="note">No cases in the plan.</p></section>'
    label = {"dev": "Dev cases", "holdout": "Holdout cases"}
    out = ['<section class="card" id="cases"><h2 class="sec">Cases</h2><p class="note">Checks passed over checks run, per arm. '
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
    out.append("</section>")
    return "".join(out)


def _rounds_section(d):
    if not d["rounds"]:
        return '<section class="card" id="editor"><h2 class="sec">Editor</h2><p class="note">The editor did not run.</p></section>'
    items = []
    for r in d["rounds"]:
        word = "accepted" if r["accepted"] else "rejected" if r["accepted"] is False else "unknown"
        score = (f' · dev score {r["score"][0]:.0f} points, {_usd(r["score"][1])} per case' if r["score"] else "")
        items.append(f'<li><b>Round {r["round"]}</b> {_state("done" if r["accepted"] else "stopped")} {word}'
                     f'{" · became the draft" if r["draft"] else ""}{score}<br>'
                     f'<span>{_e(r["hypothesis"]) or "<i>no hypothesis</i>"}</span>'
                     + (f'<br><span class="note">{_e(r["reason"])}</span>' if r["reason"] else "") + "</li>")
    return ('<section class="card" id="editor"><h2 class="sec">Editor</h2><p class="note">An accepted round that lost on its dev '
            f'score has no reason of its own: its score is the reason.</p><ul class="plain">{"".join(items)}</ul></section>')


def _num(ci, fmt):
    return "–" if not ci else f'{fmt(ci["mean"])} <span class="note">[{fmt(ci["ci_low"])}, {fmt(ci["ci_high"])}]</span>'


def _compare_section(d):
    if not d["draft"]:
        return ('<section class="card" id="compare"><h2 class="sec">Compare</h2><p class="note">No draft was made, so there is '
                'nothing to compare. The editor rounds above say why.</p></section>')
    files = "".join(f'<section class="card"><h3 class="path">{_e(rel)} <span class="note">{kind}</span></h3>'
                    f'<div class="scroll">{_side_by_side(before, after)}</div></section>' for rel, kind, before, after in d["files"])
    rows = "".join(f'<tr><td>{_e(a["stage"])}</td><td>{_e(a["arm"])}</td><td>{a["counted"]} of {a["runs"]}</td>'
                   f'<td>{_num(a["pass"], lambda x: f"{x:.1f}")}</td><td>{_num(a["cost"], _usd)}</td>'
                   f'<td>{_num(a["tokens"], lambda x: _tok(round(x)))}</td></tr>' for a in d["arms"])
    table = ('<h3 class="sub3">Per arm</h3><p class="note">Mean per run over cases, with a 95% interval (bootstrap by case, '
             'the plan\'s seed). Pass rate is in points.</p><div class="scroll"><table><thead><tr><th>Stage</th><th>Arm</th><th>Counted runs</th>'
             f'<th>Pass rate</th><th>Cost per run</th><th>Tokens per run</th></tr></thead><tbody>{rows}</tbody></table></div>') if rows else ""
    return (f'<section class="card" id="compare"><h2 class="sec">Before and after</h2><p class="note">{len(d["files"])} file'
            f'{"s" * (len(d["files"]) != 1)} changed between <code>v0</code> and <code>{_e(d["draft"])}</code>.</p>{table}</section>{files}')


def _report(d, decide):
    s = d["summary"]
    head = (f'<p><a href="/optimize">← All runs</a></p><section class="card libhead"><h2 class="sec">{_e(d["plan"].get("skill") or d["id"])} · '
            f'{_state(s["state"])}</h2><p class="note">Run <code>{_e(d["id"])}</code></p></section>')
    return (head + _plan_section(d) + _gates_section(d) + _cases_section(d) + _rounds_section(d) + _compare_section(d) + decide)


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
            return _report(d, _decide_section(conn, d))
    return _runs_list(runs(), notice)


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


def _decide_section(conn, d):
    code, why, need = approve_check(d["run"])
    verdict = d["verdict"].get("verdict")
    want = {f for f in (d["verdict"].get("base_fingerprint"), d["verdict"].get("draft_fingerprint"),
                        d["plan"].get("base_fingerprint")) if f}  # the same set decide() uses, so a run without a verdict still matches
    _, k, _ = owner_root(conn, d["plan"].get("skill"), want)
    approve = ""
    if verdict:
        blocked = "" if code == 200 else f' disabled data-block="1" title="{_e(why)}"'
        approve = (f'<button type="button" class="primary" data-opt-act="approve"{blocked or (" disabled" if need else "")}>'
                   'Approve</button>')
    block = f'<p class="note">Approve is off: {_e(why)}.</p>' if verdict and why else ""
    label = "Reason (required to approve)" if need else "Reason (optional)"
    return ('<section class="card" id="decide-card"><h2 class="sec">Decide</h2>' + _decision_box(d) + block
            + f'<div class="optform" id="decide" data-run="{_e(d["id"])}" data-need="{int(need)}">'
            + f'<label class="wide">{label}<textarea id="opt-reason" rows="2"{" required" if need else ""}></textarea></label>'
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
