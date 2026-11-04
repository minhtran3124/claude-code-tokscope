"""`tokscope optimize run|resume|regrade`: lock a plan, then preflight, baseline (current and no skill), up to 3 edit rounds
that see dev cases only, an interleaved confirm and a verdict. Files are the source of truth (store.py): every step
reads what is on disk, so a stopped run resumes without running a case twice for the same arm and index.

Order of paid calls: preflight; baseline, run index outer, arm in bench.schedule order, case inner; each round's editor
and then its draft on dev cases; confirm, like baseline over all cases."""
import json
import random
import re
import shutil
import statistics
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ...core import skills
from .. import bench
from . import grade, sandbox, stats, store, suite, trigger

MAX_ROUNDS = 3
PREFLIGHT_TRIES = 2
RESAMPLES, CI = 1000, 95
VERDICT, BENCHMARK, TRIGGER = "verdict.json", "benchmark.json", "trigger.json"
EDITOR_TIMEOUT = 20 * 60


class Stop(Exception):
    """The budget does not allow another paid call; `stage` is where the run ended."""

    def __init__(self, stage):
        super().__init__(stage)
        self.stage = stage


def _plain(cid):
    return sandbox._name("case id", cid)


def _front_description(path):
    """The frontmatter `description` of a SKILL.md (a folded or multi-line value too), None when there is none."""
    front = skills._split_front(Path(path).read_text(errors="replace"))[0]
    if front is None:
        return None
    out, taking = [], False
    for line in front.splitlines():
        if taking and (not line.strip() or line[:1] in (" ", "\t")):  # a blank line stays inside a folded value
            out.append(line.strip())
        elif line.startswith("description:"):
            out, taking = [line.split(":", 1)[1].strip()], True
        else:
            taking = False
    return " ".join(x for x in out if x) if out else None


def _claude_version():
    try:
        done = subprocess.run([sandbox.claude(), "--version"], capture_output=True, text=True, timeout=30)
        return done.stdout.strip() or None if done.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


class Ctx:
    """One run, read from its folder."""

    def __init__(self, run, log=print):
        self.run, self.log = Path(run), log
        self.plan = store.read_plan(run)
        self.skill = self.plan["skill"]
        self.suite = suite.load_folder(self.run / "suite", self.skill)
        self.dev, self.holdout = self.plan["dev"], self.plan["holdout"]
        self.cases = self.dev + self.holdout
        self.triggers = trigger.load(self.run / "suite") if self.plan.get("triggers_usable") else []

    def inputs(self, cid):
        """(case, checks, fixtures) from the frozen suite."""
        case = next(c for c in self.suite.cases if str(c["id"]) == cid)
        checks = [grade.check_shape(c) for c in (case.get("checks") or []) + (self.suite.data.get("checks") or [])]
        return case, checks, suite._fixture_paths(self.suite.folder, case)[0]

    def trigger_input(self, cid):
        """(case, checks, fixtures) of a trigger prompt: the bare prompt, nothing checked, no fixtures."""
        item = next(i for i in self.triggers if i["id"] == cid)
        return {"id": cid, "prompt": item["prompt"]}, [], []

    def source(self, arm):
        """Folder an arm pins, None for the no-skill arm."""
        if arm == "none":
            return None
        return self.run / "versions" / ("v0" if arm == "current" else arm)

    def records(self, stage=None, arm=None, cases=None):
        return [r for r in store.records(self.run) if (stage is None or r["stage"] == stage)
                and (arm is None or r["arm"] == arm) and (cases is None or r["case"] in cases)]


# steps

def run_one(ctx, stage, case, arm, i):
    """One result, resolved from the files: done is skipped, a finished folder without its line is recovered, a
    `.tmp` left behind is charged as lost and run again. Stop when the budget does not cover another call."""
    plan, run = ctx.plan, ctx.run
    args = (stage, case, arm, i)
    state = store.result_state(run, *args)
    if state == "done":
        return
    if state == "recover":
        store.recover(run, *args)
        store.index(run)
        return
    if state == "lost":
        store.discard(run, plan, *args)
    if not store.can_spend(run, plan):
        raise Stop(_stage_name(stage))
    cap = store.start(run, plan, *args)
    case_, checks, fixtures = ctx.trigger_input(case) if stage == trigger.STAGE else ctx.inputs(case)
    source = ctx.source(arm)
    tmp = store.tmp_dir(run, *args)
    tmp.parent.mkdir(parents=True, exist_ok=True)
    sandbox.execute(ctx.skill, case_, checks, fixtures, tmp, source=source, model=plan["model"], budget=cap,
                    expect=skills.fingerprint(source) if source else None, arm=arm)
    store.finish(run, *args)
    store.index(run)


def _stage_name(stage):
    return "rounds" if re.fullmatch(r"r\d+", stage) else stage


def preflight(ctx):
    """One cheap run of the first dev case with the current skill: it must load the pinned text and be valid. Prints
    the cost estimate. An INVALID run is tried again once. False (and no baseline) when it does not."""
    for i in range(PREFLIGHT_TRIES):
        run_one(ctx, "preflight", ctx.dev[0], "current", i)
        rec = next(r for r in ctx.records("preflight") if r["i"] == i)
        if rec["status"] == "ok":  # an INVALID run (timeout, API error) is retried once; a load failure is not
            break
    cost, n, runs = rec["cost_usd"] or 0, len(ctx.cases), ctx.plan["runs"]
    base = 2 * n * runs * 2  # baseline and confirm, two arms each
    most = base + MAX_ROUNDS * (len(ctx.dev) * runs + 1)
    ctx.log(f"preflight: load {rec['load']}, ${cost:.4f}; estimate about ${cost * base:.2f} for {base} runs "
            f"(baseline and confirm), up to ${cost * most:.2f} for {most} runs with {MAX_ROUNDS} edit rounds; "
            f"budget ${ctx.plan['budget_usd']:.2f}")
    return stats.counts(rec)


def baseline(ctx):
    for i, arm in bench.schedule(["current", "none"], ctx.plan["runs"]):
        for case in ctx.cases:
            run_one(ctx, "baseline", case, arm, i)


def _dev_score(ctx, base_arm_dir):
    stage, arm = ("baseline", "current") if base_arm_dir == "v0" else (f"r{base_arm_dir[1:]}", base_arm_dir)
    return stats.score(ctx.records(stage, arm, ctx.dev))


def _best_base(ctx, n):
    """The version the editor of round n starts from: the best measured so far, v0 included."""
    best, best_key = "v0", None
    for name in ["v0"] + [f"v{k}" for k in range(1, n) if (ctx.run / "versions" / f"v{k}").is_dir()]:
        rate, cost = _dev_score(ctx, name)
        key = (rate, -cost)
        if best_key is None or key > best_key:
            best, best_key = name, key
    return best


def _clip(text, n=300):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n] + "..."


def build_prompt(ctx, n, base):
    """The editor's prompt from dev records only: a holdout case is never read."""
    dev = set(ctx.dev)
    stage, arm = ("baseline", "current") if base == "v0" else (f"r{base[1:]}", base)
    recs = ctx.records(stage, arm, dev)
    prompts = {str(c["id"]): c["prompt"] for c in ctx.suite.cases if str(c["id"]) in dev}
    failed, cost = {}, {}
    for r in recs:
        if not stats.counts(r):
            continue
        cost.setdefault(r["case"], []).append(r)
        for e in r["expectations"]:
            if not e["passed"]:
                failed.setdefault(r["case"], []).append(e)
    out = [f"Improve the Claude Code skill in this folder (SKILL.md and the files next to it) so it passes more of its "
           f"eval cases. This is edit round {n} of {MAX_ROUNDS}; you start from {base}.", "",
           "Rules:", "- Edit only the skill's files. `evals/` shows the dev cases for reference; changes there are ignored.",
           *(["- The `description` in the SKILL.md frontmatter may change. `evals/triggers.json` lists prompts that should "
              "and should not make Claude load this skill. A changed description is checked on other, held-out "
              "prompts, and goes back to the old text when it loads the skill less accurately."]
             if ctx.triggers else ["- Do not change the `description` in the SKILL.md frontmatter."]),
           "- Make a small, general change that fixes the failures below; do not copy a case into the skill.",
           "- End your final answer with one line that starts with `Hypothesis:` and says what you changed and why it "
           "should help.", "", "## Failed dev cases"]
    if not failed:
        out.append("(none failed in the last measured version)")
    for cid, exps in sorted(failed.items()):
        out += [f"### {cid}", f"Prompt: {_clip(prompts[cid])}"]
        seen = set()
        for e in exps:
            if e["text"] not in seen:
                seen.add(e["text"])
                out.append(f"- failed: {e['text']} ({_clip(e['evidence'], 200)})")
        out.append("")
    out.append("## Most costly dev cases")
    ranked = sorted(cost.items(), key=lambda kv: -statistics.mean(r["cost_usd"] or 0 for r in kv[1]))[:3]
    for cid, rs in ranked:
        tools = Counter()
        try:
            stream = store.result_dir(ctx.run, rs[0]["stage"], cid, rs[0]["arm"], rs[0]["i"]) / "stream.jsonl"
            tools.update(name for name, _ in grade.tool_calls(grade.parse(stream.read_text().splitlines())))
        except OSError:
            pass
        top = ", ".join(f"{k} x{v}" for k, v in tools.most_common(3)) or "unknown"
        out.append(f"- {cid}: ${statistics.mean(r['cost_usd'] or 0 for r in rs):.4f}, "
                   f"{statistics.mean(r['num_turns'] or 0 for r in rs):.0f} turns, top tool calls: {top}")
    out += ["", "## Earlier rounds"]
    earlier = False
    for m in range(1, n):
        path = store.editor_dir(ctx.run, m) / "result.json"
        if not path.is_file():
            continue
        earlier = True
        res = json.loads(path.read_text())
        if res["accepted"]:
            rate, c = stats.score(ctx.records(f"r{m}", f"v{m}", dev))
            tail = f"dev pass rate {rate:.1f}%, ${c:.4f} per case"
        else:
            tail = f"refused: {res['reason']}"
        out.append(f"- round {m}: {res.get('hypothesis') or '(no hypothesis)'} -> {tail}")
    if not earlier:
        out.append("(none)")
    return "\n".join(out) + "\n"


def _pending_start(run, n):
    mine = [l for l in store.lines(run) if l.get("round") == n and l.get("kind") in ("start", "lost", "editor")]
    return mine[-1] if mine and mine[-1]["kind"] == "start" else None


def _write_json(path, data):
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def _run_editor(argv, workspace, ed):
    """Run the editor session in the workspace, stream to stream.jsonl; a timeout kills it. Returns the events."""
    with (ed / "stderr.log").open("w") as log, (ed / "stream.jsonl").open("w") as stream:
        try:
            proc = subprocess.Popen(argv, cwd=workspace, stdin=subprocess.DEVNULL, stdout=stream, stderr=log, text=True)
        except OSError:
            return []
        try:
            proc.wait(timeout=EDITOR_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    return grade.parse((ed / "stream.jsonl").read_text().splitlines())


def ensure_editor(ctx, n):
    """Round n's editor call and its draft version, resolved from the files: done needs result.json and its ledger
    line; result.json alone gets its line; anything else is deleted, charged as lost and run again."""
    run, plan = ctx.run, ctx.plan
    ed = store.editor_dir(run, n)
    if store.editor_done(run, n):
        return
    if (ed / "result.json").is_file():
        store.append(run, {"kind": "editor", "round": n, "cost_usd": json.loads((ed / "result.json").read_text())["cost_usd"]})
        return
    start = _pending_start(run, n)
    for p in (ed, run / "versions" / f"v{n}", run / "versions" / f"v{n}.tmp"):
        shutil.rmtree(p, ignore_errors=True)
    if start:
        store.append(run, {"kind": "lost", "round": n, "cost_usd": start.get("cap") or store.reserve(run, plan)})
    if not store.can_spend(run, plan):
        raise Stop("rounds")
    cap = store.call_cap(run, plan)
    store.append(run, {"kind": "start", "round": n, "cap": cap})
    base = _best_base(ctx, n)
    ed.mkdir(parents=True)
    ws = ed / "workspace"
    suite.editor_workspace(ctx.skill, ws, source=run / "versions" / base, suite=ctx.suite,
                           triggers=trigger.train_items(ctx.triggers) if ctx.triggers else None)
    prompt = build_prompt(ctx, n, base)
    (ed / "prompt.md").write_text(prompt)
    events = _run_editor(sandbox.command(prompt, ws, cap, plan["model"]), ws, ed)
    res = grade._result(events) or {}
    answer = res.get("result") or ""
    cost = res.get("total_cost_usd")
    if cost is None:  # killed, timed out or no result event: the call may have spent up to its cap
        cost = cap
    m = re.search(r"^\s*Hypothesis:\s*(.+)$", answer, re.M)
    hypothesis = m.group(1).strip() if m else None
    (ed / "hypothesis.txt").write_text(hypothesis or "")
    reason, fp = None, None
    if not events or res.get("is_error") or not res:
        reason = "the editor did not finish"
    elif not hypothesis:
        reason = "no Hypothesis: line"
    else:
        tmp = run / "versions" / f"v{n}.tmp"
        tmp.mkdir(parents=True)
        for f in skills._files(ws):
            target = tmp / f.relative_to(ws)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
        fp = skills.fingerprint(tmp)
        earlier = {skills.fingerprint(run / "versions" / f"v{k}"): f"v{k}" for k in range(0, n)
                   if (run / "versions" / f"v{k}").is_dir()}
        if fp is None:
            reason = "no SKILL.md left"
        elif fp in earlier:
            reason = f"same files as {earlier[fp]}"
        elif _front_description(tmp / "SKILL.md") != plan["description"] and not ctx.triggers:
            reason = "the description changed (locked)"
        elif ctx.triggers and _front_description(tmp / "SKILL.md") is None:
            reason = "the description was removed"
        if reason:
            shutil.rmtree(tmp, ignore_errors=True)
        else:
            tmp.rename(run / "versions" / f"v{n}")
    _write_json(ed / "result.json", {"round": n, "base": base, "hypothesis": hypothesis, "accepted": reason is None,
                                     "reason": reason, "fingerprint": fp if reason is None else None,
                                     "cost_usd": cost, "num_turns": res.get("num_turns")})
    store.append(run, {"kind": "editor", "round": n, "cost_usd": cost})


def rounds(ctx):
    """Edit rounds. Returns the best accepted draft's arm (v1..v3), or None."""
    plan = ctx.plan
    current_dev = ctx.records("baseline", "current", ctx.dev)
    drafts = []
    for n in range(1, plan["max_rounds"] + 1):
        ensure_editor(ctx, n)
        if not json.loads((store.editor_dir(ctx.run, n) / "result.json").read_text())["accepted"]:
            continue
        arm = f"v{n}"
        for i in range(plan["runs"]):
            for case in ctx.dev:
                run_one(ctx, f"r{n}", case, arm, i)
        drafts.append(arm)
        if stats.dev_ok(plan, current_dev, ctx.records(f"r{n}", arm, ctx.dev)):
            break
    if not drafts:
        return None
    return max(drafts, key=lambda a: (lambda s: (s[0], -s[1]))(stats.score(ctx.records(f"r{a[1:]}", a, ctx.dev))))


def _trigger_runs(ctx, arm, split):
    for i, a in bench.schedule(["current", arm], trigger.TRIGGER_RUNS):
        for item in trigger.by_split(ctx.triggers, split):
            run_one(ctx, trigger.STAGE, item["id"], a, i)


def _trigger_reason(acc, passed):
    """Why the gate kept or reverted the description; says 'not measured' when a test accuracy is None."""
    if acc["current"]["test"] is None or acc["draft"]["test"] is None:
        why = "test accuracy was not measured"
    else:
        why = "test accuracy " + ("kept" if passed else "dropped")
    return why + "; " + ("new description kept" if passed else "old description put back")


def trigger_gate(ctx, arm):
    """A draft that changes the description must not lower test-split trigger accuracy; else the old description is
    put back and the rest of the draft is kept. Runs nothing when the description is the same (whitespace aside) or
    there is no usable trigger set. The result is saved to trigger.json before the rewrite, so a stop between the
    two is finished on resume."""
    run, path = ctx.run, ctx.run / TRIGGER
    draft_dir = run / "versions" / arm
    if not path.is_file():
        if not ctx.triggers or not trigger.description_changed(
                ctx.plan["description"], _front_description(draft_dir / "SKILL.md")):
            return
        acc = {a: {s: None for s in trigger.SPLITS} for a in ("current", "draft")}
        stop = None
        for split in ("test", "train"):  # test first: its verdict is kept even when the budget ends the train split
            try:
                _trigger_runs(ctx, arm, split)
            except Stop as e:
                if split == "test":
                    raise
                stop = e  # train accuracy stays None (runs are kept); the test verdict below is still saved
                break
            recs = ctx.records(trigger.STAGE)
            acc["current"][split] = trigger.accuracy(recs, ctx.triggers, "current", split)
            acc["draft"][split] = trigger.accuracy(recs, ctx.triggers, arm, split)
        passed = trigger.decide(acc["current"]["test"], acc["draft"]["test"])
        _write_json(path, {"status": "ran", "reason": _trigger_reason(acc, passed),
                           "prompts": trigger.counts(ctx.triggers), "current": acc["current"], "draft": acc["draft"],
                           "passed": passed, "reverted": not passed, "draft_version": arm})
        if stop:
            if not passed and draft_dir.is_dir():
                trigger.revert_description(draft_dir, run / "versions" / "v0")
            raise stop
    res = json.loads(path.read_text())
    if res.get("reverted") and draft_dir.is_dir():
        trigger.revert_description(draft_dir, run / "versions" / "v0")


def trigger_block(ctx, stopped=None):
    """verdict.json's `trigger` block, from trigger.json and the plan."""
    plan = ctx.plan
    prompts = plan.get("triggers_prompts") or {s: 0 for s in trigger.SPLITS}
    try:
        return json.loads((ctx.run / TRIGGER).read_text())
    except (OSError, ValueError):
        pass
    if stopped == "trigger":
        status, reason = "not finished", "the budget ended the run in the trigger eval"
    elif plan.get("triggers_usable"):
        status, reason = "not needed", "the draft did not change the description"
    else:
        status = "no trigger evidence"
        reason = (f"evals/triggers.json needs at least {trigger.MIN_PROMPTS} prompts with train and test both "
                  "non-empty" if plan.get("triggers_hash") else "no evals/triggers.json")
    return {"status": status, "reason": reason, "prompts": prompts, "current": None, "draft": None,
            "passed": None, "reverted": False}


def confirm(ctx, arm):
    for i, a in bench.schedule(["current", arm], ctx.plan["runs"]):
        for case in ctx.cases:
            run_one(ctx, "confirm", case, a, i)


# outputs

def _mapped(ctx, draft):
    base = [r for r in ctx.records("baseline")]
    conf = [dict(r, arm="draft" if r["arm"] == draft else r["arm"]) for r in ctx.records("confirm")]
    return base, conf


def finalize(ctx, stopped=None, draft=None, log=True):
    """Write verdict.json and benchmark.json from the stored results and rebuild the index."""
    plan = ctx.plan
    base, conf = _mapped(ctx, draft)
    out = stats.gates(plan, base, conf, stopped=stopped)
    verdict = {"verdict": out["verdict"], "reason": out["reason"], "gates": out["gates"], "stopped": stopped,
               "stop_stage": stopped or ("confirm" if conf else "baseline"),
               "draft_version": draft,
               "draft_fingerprint": skills.fingerprint(ctx.run / "versions" / draft) if draft else None,
               "base_fingerprint": plan["base_fingerprint"], "spent_usd": round(store.spent(ctx.run), 6),
               "budget_usd": plan["budget_usd"], "run_id": ctx.run.name, "skill": ctx.skill,
               "trigger": trigger_block(ctx, stopped)}
    _write_json(ctx.run / VERDICT, verdict)
    _write_json(ctx.run / BENCHMARK, benchmark(ctx, draft))
    store.index(ctx.run)
    return verdict


def _tool_calls(run, r):
    try:
        stream = store.result_dir(run, r["stage"], r["case"], r["arm"], r["i"]) / "stream.jsonl"
        return len(grade.tool_calls(grade.parse(stream.read_text().splitlines())))
    except OSError:
        return 0


def _stats(values):
    return {"mean": round(statistics.mean(values), 4), "stddev": round(statistics.pstdev(values), 4),
            "min": min(values), "max": max(values)} if values else {"mean": None, "stddev": None, "min": None, "max": None}


def benchmark(ctx, draft):
    """skill-creator's benchmark.json: runs from baseline (current, no_skill) and confirm (current, draft)."""
    names = {"current": "current", "none": "no_skill"}
    runs, number = [], Counter()
    for r in sorted(ctx.records(), key=lambda r: (["baseline", "confirm"].index(r["stage"]) if r["stage"] in ("baseline", "confirm") else 9, r["case"], r["arm"], r["i"])):
        if r["stage"] not in ("baseline", "confirm"):
            continue
        config = "draft" if r["arm"] == draft else names.get(r["arm"], r["arm"])
        number[(r["case"], config)] += 1
        ok = r["status"] == "ok"
        runs.append({"eval_id": r["case"], "eval_name": r["case"], "configuration": config, "stage": r["stage"],
                     "run_number": number[(r["case"], config)], "load": r["load"],
                     "result": {"pass_rate": (r["passed"] / r["total"]) if ok and r["total"] else 0.0,
                                "passed": r["passed"] or 0, "failed": (r["total"] or 0) - (r["passed"] or 0),
                                "total": r["total"] or 0, "time_seconds": r["duration_s"], "tokens": r["tokens"],
                                "tool_calls": _tool_calls(ctx.run, r), "errors": 0 if ok else 1},
                     "expectations": [{k: e[k] for k in ("text", "passed", "evidence")} for e in r["expectations"]],
                     "notes": [] if ok else [r.get("reason") or "invalid run"]})
    summary = {}
    for config in ("current", "draft", "no_skill"):
        mine = [x for x in runs if x["configuration"] == config and x["result"]["errors"] == 0 and x["load"] in ("ok", "n/a")]
        if not mine:
            continue
        summary[config] = {"pass_rate": _stats([x["result"]["pass_rate"] for x in mine]),
                           "time_seconds": _stats([x["result"]["time_seconds"] for x in mine if x["result"]["time_seconds"] is not None]),
                           "tokens": _stats([x["result"]["tokens"] for x in mine if x["result"]["tokens"] is not None])}
    a, b = ("current", "draft") if "draft" in summary else ("no_skill", "current")
    if a in summary and b in summary:
        d = {k: (summary[b][k]["mean"] or 0) - (summary[a][k]["mean"] or 0) for k in ("pass_rate", "time_seconds", "tokens")}
        summary["delta"] = {"pass_rate": f"{d['pass_rate']:+.2f}", "time_seconds": f"{d['time_seconds']:+.1f}",
                            "tokens": f"{d['tokens']:+.0f}", "basis": f"{b} minus {a}"}
    return {"metadata": {"skill_name": ctx.skill, "executor_model": ctx.plan["model"], "analyzer_model": None,
                         "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         "evals_run": ctx.cases, "runs_per_configuration": ctx.plan["runs"],
                         "run_id": ctx.run.name},
            "runs": runs, "run_summary": summary}


# entry points

def drive(path, log=print):
    """Run what is left of one run. A run that has a verdict is done: nothing is run."""
    ctx = Ctx(path, log)
    if (ctx.run / VERDICT).is_file():
        return ctx.run
    draft = None
    try:
        if not preflight(ctx):
            finalize(ctx, "preflight")
            return ctx.run
        baseline(ctx)
        base, _ = _mapped(ctx, None)
        if stats.gates(ctx.plan, base, [])["gates"][1]["passed"] is False:
            finalize(ctx)  # Meaningful suite failed: stop after baseline
            return ctx.run
        draft = rounds(ctx)
        if draft is None:
            finalize(ctx, "rounds")
            return ctx.run
        trigger_gate(ctx, draft)
        confirm(ctx, draft)
        finalize(ctx, None, draft)
    except Stop as e:
        finalize(ctx, _stage_name(e.stage), draft if e.stage == "confirm" else None)
    return ctx.run


def start(skill, budget, runs=3, model="sonnet", cwd=None, log=print):
    """Lock a plan for `skill` and run it. ValueError (a load error) before any paid run; returns the run folder."""
    if not budget > 0:
        raise ValueError(f"budget {budget!r} must be above 0")
    if runs < 1:
        raise ValueError(f"runs {runs!r} must be at least 1")
    live = suite.load(skill, cwd)
    if live.problems:
        raise ValueError("suite has problems: " + "; ".join(live.problems))
    try:
        dev, hold = suite.split(live, write=False)
    except suite.Refused as e:
        raise ValueError(str(e)) from None
    for case in live.cases:
        _plain(str(case["id"]))
    description = _front_description(live.folder / "SKILL.md")
    trigger.load(live.folder)  # a bad triggers.json is a load error, before any paid run
    run = store.new_run(skill)
    store.acquire(run)
    try:
        suite.freeze(live, run / "suite")
        v0 = run / "versions" / "v0"
        for f in skills._files(live.folder):
            target = v0 / f.relative_to(live.folder)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
        base = skills.fingerprint(v0)
        if base != skills.fingerprint(live.folder):
            raise ValueError(f"{skill}: the copy of the skill is not the same version")
        items = trigger.load(run / "suite")
        store.write_plan(run, {
            "schema": store.SCHEMA_VERSION, "skill": skill, "run_id": run.name, "base_fingerprint": base,
            "description": description, "triggers_hash": trigger.file_hash(run / "suite"),
            "triggers_usable": trigger.usable(items) and description is not None,
            "triggers_prompts": trigger.counts(items), "suite_hash": suite.suite_hash(live.data), "dev": dev, "holdout": hold,
            "runs": runs, "model": model, "claude_version": _claude_version(), "budget_usd": float(budget),
            "per_run_cap_usd": min(sandbox.MAX_BUDGET_USD, float(budget)), "max_rounds": MAX_ROUNDS,
            "seed": random.SystemRandom().getrandbits(32), "resamples": RESAMPLES, "ci": CI, "gates": stats.GATES,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        log(f"run {run}")
        return drive(run, log)
    finally:
        store.release(run)


def resume(run_id, log=print):
    """Continue a stopped run. LockError (exit 2) when the plan or frozen suite changed or another process runs it."""
    run = store.find_run(run_id)
    store.acquire(run)
    try:
        store.check_lock(run)
        return drive(run, log)
    finally:
        store.release(run)


def regrade(run_id, log=print):
    """Grade every stored result again from its stream and files, then recompute verdict.json, benchmark.json and the
    index. No claude call, no cost."""
    run = store.find_run(run_id)
    store.acquire(run)
    try:
        store.check_lock(run)
        ctx = Ctx(run, log)
        n = 0
        for g in sorted(run.glob("results/*/*/*/*/grading.json")):
            folder = g.parent
            if folder.name.endswith(".tmp"):
                continue
            case = g.parts[-4]
            _, checks, _ = ctx.trigger_input(case) if g.parts[-5] == trigger.STAGE else ctx.inputs(case)
            events = grade.parse((folder / "stream.jsonl").read_text().splitlines())
            grade.write(folder, grade.grade(events, folder / "files", checks))
            n += 1
        log(f"regraded {n} results")
        old = json.loads((run / VERDICT).read_text()) if (run / VERDICT).is_file() else None
        if old:
            finalize(ctx, old.get("stopped"), old.get("draft_version"))
        else:
            store.index(run)
        return run
    finally:
        store.release(run)


def report(run):
    """Lines to print: the run folder, spent against budget, the verdict and the gate table."""
    run = Path(run)
    plan = store.read_plan(run)
    out = [f"run {run}", f"spent ${store.spent(run):.4f} of ${plan['budget_usd']:.2f}"]
    try:
        v = json.loads((run / VERDICT).read_text())
    except OSError:
        return out + ["no verdict yet; resume with: tokscope optimize resume " + run.name]
    out.append(f"verdict: {v['verdict']} ({v['reason']})")
    for g in v["gates"]:
        state = "not run" if g["passed"] is None else "pass" if g["passed"] else "FAIL"
        out.append(f"  {g['name']:<17} {state:<8} value {json.dumps(g['value'])}  threshold {json.dumps(g['threshold'])}")
    if v.get("draft_fingerprint"):
        out.append(f"draft {v['draft_version']} fingerprint {v['draft_fingerprint']} (base {v['base_fingerprint']})")
    return out


def exit_code(run):
    try:
        v = json.loads((Path(run) / VERDICT).read_text())["verdict"]
    except (OSError, ValueError, KeyError):
        return 1
    return 0 if v == stats.APPLY else 1
