"""Optimize one of your skills with `claude -p`, on a copy, and apply the result only when you say so.

A job lives in <data>/bench/optimize/<job>/: the skill to change and the guide skills (optimize-skill, asd-ste100,
unslop) copied into .claude/skills/, so the run loads them like a project's skills, and a job.json with its state.
Under bench/ the job's sessions count as experiments, not as real work. The run may write only inside the job folder,
spends at most the budget (--max-budget-usd), and its result is a diff against the skill as it was when the job
started. Apply refuses when the skill changed since then, and records the old and new versions so a benchmark can
compare them (tokscope bench --skill-versions old,new)."""

import difflib
import json
import re
import os
import shutil
import signal
import sqlite3
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .. import paths
from ..core import skills
from ..core.ingest import connect
from . import bench
from ..features import changes as changes_log, library

GUIDES = {
    "optimize-skill": "Run the optimize-skill skill on it: fewer tokens, the same output. Save its test outputs under runs/, "
                      "never in the skill folder.",
    "asd-ste100": "Rewrite its instructions in ASD-STE100 Simplified Technical English with the asd-ste100 skill. Run "
                  "`python3 .claude/skills/asd-ste100/scripts/ste-lint.py FILE` on each Markdown file you change and fix "
                  "every hard finding. Keep code, commands, paths and names as they are.",
    "unslop": "Apply the unslop skill to its prose.",
}
MODELS = ("", "sonnet", "opus", "haiku")
TIMEOUT = 1800
STEPS_SHOWN = 60
_threads, _procs, _lock = {}, {}, threading.Lock()


def jobs_dir():
    return paths.home() / "bench" / "optimize"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _claude():
    if env := os.environ.get("TOKSCOPE_CLAUDE"):
        return env
    return paths.tool("claude", first=paths.CLAUDE_FIRST) or "claude"


def _copy(src, dest):
    """The files library.files lists (no hidden files or caches), as real copies."""
    for rel, _ in library.files(src):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, target)


def prompt(target, guides):
    goals = "\n".join(f"- {GUIDES[g]}" for g in guides)
    return f"""You are improving one Claude Code skill. Its folder is .claude/skills/{target}/ in this directory.
Goals, in this order:
{goals}
Rules:
- Edit files in .claude/skills/{target}/ only; put notes and test outputs in runs/. Change nothing else.
- Keep the frontmatter name, and the trigger words of the description.
- Keep every rule that changes the output, every hard stop and every confirmation gate.
End with a short report: what changed in each file, the words before and after, and what you were not sure about."""


def guides_available(found):
    """{guide: folder} for the guide skills you have (yours or installed)."""
    have = {}
    for k in found:
        if k["dir"] in GUIDES and k["dir"] not in have:
            have[k["dir"]] = k["folder"]
    return have


def _read(job):
    return json.loads((jobs_dir() / job / "job.json").read_text())


def _write(job, data):
    path = jobs_dir() / job / "job.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)  # a reader never sees half a file


def status(job):
    """The job's state; a job left running by a server that stopped reads as interrupted."""
    data = _read(job)
    if data["state"] == "running" and job not in _threads:
        data["state"], data["error"] = "interrupted", "the dashboard stopped while the run was going"
    return data


def steps(job):
    """(the last steps of the run, how many there are, seconds since the last one)."""
    path = jobs_dir() / job / "steps.jsonl"
    lines = path.read_text().splitlines() if path.is_file() else []
    out = [json.loads(line) for line in lines[-STEPS_SHOWN:]]
    last = out[-1]["t"] if out else datetime.fromisoformat(_read(job)["started"]).timestamp()
    return out, len(lines), round(time.time() - last)


def jobs_for(folder):
    out = []
    for d in sorted(jobs_dir().glob("*/job.json"), reverse=True) if jobs_dir().is_dir() else []:
        try:
            data = status(d.parent.name)
        except (OSError, ValueError):
            continue
        if data.get("source") == str(folder):
            out.append(data)
    return sorted(out, key=lambda j: j["started"], reverse=True)


def running():
    with _lock:
        return [j for j, t in _threads.items() if t.is_alive()]


def start(k, found, guides, model="", budget=2.0, wait=False):
    """Copy the skill and its guides into a new job folder and run claude -p there in the background; returns the job id."""
    if k["origin"] != "mine":
        raise ValueError("only your own skills can be optimized; an installer would overwrite the change")
    have = guides_available(found)
    guides = [g for g in GUIDES if g in guides]
    if not guides or any(g not in have for g in guides):
        raise ValueError("pick one or more guide skills you have: " + ", ".join(have) if have else "no guide skill is installed")
    if model not in MODELS:
        raise ValueError(f"model must be one of {', '.join(m or 'default' for m in MODELS)}")
    budget = float(budget)
    if not 0 < budget <= 50:
        raise ValueError("the budget must be more than $0 and at most $50")
    if running():
        raise ValueError("another optimize run is going; wait for it to finish")
    job = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    root = jobs_dir() / job
    work = root / ".claude" / "skills"
    _copy(k["folder"], work / k["dir"])
    for g in guides:
        if g != k["dir"]:
            _copy(have[g], work / g)
    (root / "runs").mkdir()
    data = {"job": job, "skill": k["dir"], "name": k["name"], "source": str(k["folder"]), "guides": guides, "model": model,
            "budget": budget, "base": skills.fingerprint(k["folder"]), "state": "running", "started": _now(),
            "prompt": prompt(k["dir"], guides)}
    _write(job, data)
    thread = threading.Thread(target=_run, args=(job,), daemon=True)
    with _lock:
        _threads[job] = thread
    thread.start()
    if wait:
        thread.join()
    return job


def _cmd(data, root):
    allowed = ["Read", "Glob", "Grep", "Skill", "Agent", "TodoWrite", f"Edit(/{root}/**)", f"Write(/{root}/**)",
               "Bash(wc:*)", "Bash(python3 .claude/skills/asd-ste100/scripts/ste-lint.py:*)"]
    # stream-json: one event per line, so the page can show each step while the run goes
    cmd = [_claude(), "-p", data["prompt"], "--output-format", "stream-json", "--verbose", "--max-budget-usd", str(data["budget"]),
           "--permission-mode", "default", "--allowedTools", *allowed,
           "--disallowedTools", "WebFetch", "WebSearch", "NotebookEdit", "Bash(rm:*)", "Bash(git:*)"]
    return cmd + (["--model", data["model"]] if data["model"] else [])


def _describe(block, root):
    """One line for a tool call: what a reader needs to see the run is moving."""
    name, args = block.get("name", "?"), block.get("input") or {}
    path = args.get("file_path") or args.get("path") or ""
    if path:
        path = str(path).removeprefix(str(root) + "/")
    detail = {"Skill": args.get("skill") or args.get("command"), "Agent": args.get("description"), "Task": args.get("description"),
              "Bash": args.get("command"), "Glob": args.get("pattern"), "Grep": args.get("pattern"),
              "TodoWrite": "update the plan"}.get(name, path)
    return f"{name} {str(detail or '')[:140]}".strip()


def _step(job, kind, text, sub=False):
    with (jobs_dir() / job / "steps.jsonl").open("a") as f:
        f.write(json.dumps({"t": round(time.time(), 1), "kind": kind, "text": text[:240], "sub": sub}) + "\n")


def _event(job, root, ev):
    """Note what one stream-json event says; returns the final result event, else None."""
    kind, sub = ev.get("type"), bool(ev.get("parent_tool_use_id"))
    if kind == "result":
        return ev
    if kind == "system" and ev.get("subtype") == "init":
        _step(job, "start", f"started · {ev.get('model', '')}")
    elif kind == "system" and ev.get("subtype") == "api_retry":
        _step(job, "retry", f"API retry {ev.get('attempt')}/{ev.get('max_retries')}: {ev.get('error', '')}")
    elif kind == "system" and ev.get("subtype") == "permission_denied":
        _step(job, "denied", f"denied: {ev.get('tool_name') or ev.get('message') or ''}")
    elif kind == "assistant":
        for block in (ev.get("message") or {}).get("content") or []:
            if block.get("type") == "tool_use":
                _step(job, "tool", _describe(block, root), sub)
            elif block.get("type") == "text" and block.get("text", "").strip() and not sub:
                _step(job, "say", block["text"].strip().splitlines()[0])
    elif kind == "user":
        for block in (ev.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                body = block.get("content")
                text = body if isinstance(body, str) else " ".join(b.get("text", "") for b in body or [] if isinstance(b, dict))
                _step(job, "error", f"tool error: {text.strip()[:160]}", sub)
    return None


def _run(job):
    root = jobs_dir() / job
    data = _read(job)
    t0, result, err = time.time(), None, ""
    try:
        log = (root / "stderr.log").open("w")  # a file, not a pipe: a full stderr pipe would stall the run
        proc = subprocess.Popen(_cmd(data, root), cwd=root, stdout=subprocess.PIPE, stderr=log, text=True)
        with _lock:
            _procs[job] = proc
        timer = threading.Timer(TIMEOUT, proc.kill)  # a run that never ends still ends
        timer.start()
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            result = _event(job, root, ev) or result
        proc.wait()
        timer.cancel()
        log.close()
        err = (root / "stderr.log").read_text(errors="replace")[-1000:]
        data = _read(job)  # cancel() may have marked it meanwhile
        if data.get("cancelled"):
            data.update(state="cancelled", error="cancelled from the dashboard", cost=(result or {}).get("total_cost_usd"))
        elif time.time() - t0 >= TIMEOUT:
            data.update(state="failed", error=f"no end in {TIMEOUT // 60} minutes")
        else:
            out = result or {"is_error": True, "result": err or "claude -p ended without a result"}
            failed = proc.returncode != 0 or out.get("is_error")
            data.update(state="failed" if failed else "done", cost=out.get("total_cost_usd"), report=out.get("result", ""),
                        session_id=out.get("session_id"), turns=out.get("num_turns"),
                        error=(out.get("result") or err or f"claude -p exited {proc.returncode}") if failed else None)
    except OSError as e:  # no claude binary
        data.update(state="failed", error=str(e))
    _step(job, "end", data["state"])
    data.update(finished=_now(), duration_s=round(time.time() - t0, 1))
    _write(job, data)
    with _lock:
        _threads.pop(job, None)
        _procs.pop(job, None)


def cancel(job):
    """Stop a running job: SIGINT first, so claude -p ends its turn and reports its cost; a kill after 15 seconds."""
    with _lock:
        proc = _procs.get(job)
    if not proc:
        raise ValueError("the job is not running")
    data = _read(job)
    data["cancelled"] = True
    _write(job, data)
    proc.send_signal(signal.SIGINT)
    threading.Timer(15, lambda: proc.poll() is None and proc.kill()).start()


def changes(job):
    """[(path, kind, diff lines)] between the skill as it is now and the job's copy; kind is added, removed or changed."""
    data = _read(job)
    return changes_between(Path(data["source"]), jobs_dir() / job / ".claude" / "skills" / data["skill"])


def compared(job):
    """(old folder, new folder) to show: the skill and the draft, or once applied the two kept versions."""
    data = _read(job)
    if data["state"] == "applied":
        return skills.snapshot_dir(data["skill"], data["old_version"]), skills.snapshot_dir(data["skill"], data["new_version"])
    return Path(data["source"]), _draft(job)


def changes_between(old_dir, new_dir):
    old, new = dict(library.files(old_dir)) if old_dir.is_dir() else {}, dict(library.files(new_dir)) if new_dir.is_dir() else {}
    out = []
    for rel in sorted(set(old) | set(new), key=lambda r: (r != "SKILL.md", r)):
        a = (old_dir / rel).read_bytes() if rel in old else b""
        b = (new_dir / rel).read_bytes() if rel in new else b""
        if a == b:
            continue
        kind = "added" if rel not in old else "removed" if rel not in new else "changed"
        try:
            lines = list(difflib.unified_diff(a.decode().splitlines(), b.decode().splitlines(), f"before/{rel}", f"after/{rel}",
                                              lineterm="", n=2))
        except UnicodeDecodeError:
            lines = ["(a binary file)"]
        out.append((rel, kind, lines))
    return out


def apply(conn, job):
    """Write the job's copy over the skill; returns (old version, new version). Hidden files in the skill stay."""
    data = status(job)
    if data["state"] != "done":
        raise ValueError(f"the job is {data['state']}, not done")
    src = Path(data["source"])
    if skills.fingerprint(src) != data["base"]:
        raise ValueError("the skill changed after this job started; start a new job")
    new_dir = jobs_dir() / job / ".claude" / "skills" / data["skill"]
    now = _now()
    old = skills.record(conn, data["skill"], src, now, "optimize")  # keeps the old files, for a diff and a benchmark
    for rel, kind, _ in changes(job):
        target = src / rel
        if kind == "removed":
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(new_dir / rel, target)
    new = skills.record(conn, data["skill"], src, now, "optimize")
    conn.commit()
    data.update(state="applied", applied=now, old_version=old, new_version=new)
    _write(job, data)
    try:
        changes_log.add_change(conn, "Optimize applied", skill=data["skill"], at=now)
    except sqlite3.Error as e:  # the apply worked; keep it and note why the row is missing
        data["change_error"] = str(e)
        _write(job, data)
    return old, new


def discard(job):
    if job in running() or job in _bench_threads:
        raise ValueError("the job or its benchmark is still running")
    shutil.rmtree(jobs_dir() / job)


# ---- benchmark a draft against the skill as it is, before you approve it

BENCH_RUNS = (1, 2, 3, 5)
_bench_threads = {}


def _draft(job):
    data = _read(job)
    return jobs_dir() / job / ".claude" / "skills" / data["skill"]


def bench_versions(job):
    """(current version, draft version), each with its files kept where `tokscope bench` pins versions from."""
    data = _read(job)
    src, draft = Path(data["source"]), _draft(job)
    versions = []
    for folder in (src, draft):
        v = skills.fingerprint(folder)
        skills._snapshot(data["skill"], v, folder)
        versions.append(v)
    return tuple(versions)


def bench_tasks(skill):
    """[(task name, about, cost cap per run, uses the skill)] from the tasks folder; tasks that call the skill first."""
    out = []
    for f in sorted(paths.tasks().glob("*.json")) if paths.tasks().is_dir() else []:
        try:
            t = json.loads(f.read_text())
        except ValueError:
            continue
        uses = f"/{skill}" in t.get("prompt", "") or skill in json.dumps(t.get("variants", {}))
        out.append((t.get("name", f.stem), t.get("about", ""), float(t.get("max_budget_usd", 1)), uses))
    return sorted(out, key=lambda t: (not t[3], t[0]))


def new_task(skill, folder, form):
    """Write a small task for the skill (its project at HEAD, the paths you name) and return its name."""
    name = re.sub(r"[^a-z0-9-]+", "-", str(form.get("name") or f"{skill}-quick").lower()).strip("-")[:60]
    target = paths.tasks() / f"{name}.json"
    if not name or target.exists():
        raise ValueError(f"a task named {name!r} exists already; pick another name")
    prompt = str(form.get("prompt", "")).strip()
    if len(prompt) < 5:
        raise ValueError("write the prompt the benchmark sends, for example /" + skill + " and a question")
    repo = Path(folder).resolve().parent.parent.parent  # <repo>/.claude/skills/<skill>
    if not (repo / ".git").exists():
        raise ValueError("the skill is not in a git repository, so the benchmark has no snapshot to pin it into")
    words = [w.strip() for w in str(form.get("grader", "")).split(",") if w.strip()]
    task = {"name": name, "about": f"Made from the dashboard for {skill}.", "repo": str(repo), "commit": "HEAD",
            "paths": [p.strip() for p in str(form.get("paths") or ".").split(",") if p.strip()],
            "main_model": form.get("model") or "sonnet", "max_budget_usd": min(float(form.get("budget") or 1.5), 10),
            "timeout_s": 900, "allowed_tools": ["Skill", "Read", "Grep", "Glob"], "prompt": prompt, "variants": {},
            "grader": {"about": "Pass when the answer has every word.", "all": [re.escape(w) for w in words]}}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(task, indent=2) + "\n")
    return name


def bench_start(job, db, task_name, runs):
    data = status(job)
    if data["state"] not in ("done", "applied"):
        raise ValueError("benchmark a run that ended well")
    if (data.get("bench") or {}).get("state") == "running":
        raise ValueError("a benchmark of this run is going")
    if int(runs) not in BENCH_RUNS:
        raise ValueError(f"runs per version must be one of {BENCH_RUNS}")
    skills.check_pinnable(data["skill"])  # a personal skill wins over a pinned copy: refuse before spending
    task_path = paths.tasks() / f"{task_name}.json"
    if not re.match(r"^[A-Za-z0-9_.-]+$", str(task_name)) or not task_path.is_file():
        raise ValueError("no such task")
    task = bench.load_task(task_path)
    versions = bench_versions(job)
    if versions[0] == versions[1]:
        raise ValueError("the draft is the same as the skill: nothing to compare")
    data["bench"] = {"state": "running", "task": task["name"], "runs": int(runs), "versions": list(versions),
                     "started": _now(), "cap": round(2 * int(runs) * float(task.get("max_budget_usd", 1)), 2)}
    _write(job, data)
    (jobs_dir() / job / "bench.log").write_text("")
    thread = threading.Thread(target=_bench_run, args=(job, db, task), daemon=True)
    with _lock:
        _bench_threads[job] = thread
    thread.start()
    return data["bench"]


def _bench_run(job, db, task):
    log_path = jobs_dir() / job / "bench.log"

    def log(line):
        with log_path.open("a") as f:
            f.write(line.rstrip() + "\n")

    data = _read(job)
    b = data["bench"]
    try:
        bench.run(paths.home(), db, paths.phases(), task, b["runs"], skill=data["skill"], versions=b["versions"], log=log)
        b.update(state="done")
    except Exception as e:  # a failed export, a missing claude, a bad task: say so on the page
        import traceback
        where = traceback.extract_tb(e.__traceback__)[-1]
        log(f"failed: {type(e).__name__}: {e} (at {Path(where.filename).name}:{where.lineno}: {where.line})")
        b.update(state="failed", error=str(e)[:500])
    b["finished"] = _now()
    data = _read(job)
    data["bench"] = b
    _write(job, data)
    with _lock:
        _bench_threads.pop(job, None)


def bench_status(job):
    b = dict(_read(job).get("bench") or {})
    if b.get("state") == "running" and job not in _bench_threads:
        b.update(state="interrupted", error="the dashboard stopped while the benchmark was going")
    path = jobs_dir() / job / "bench.log"
    b["log"] = path.read_text().splitlines()[-40:] if path.is_file() else []
    return b


def bench_results(job, db):  # db: the database path
    """Per version of this benchmark: runs, passes, errors, median cost, tokens and seconds, and skill checks."""
    from statistics import median

    b = _read(job).get("bench") or {}
    if not b.get("versions"):
        return []
    conn = connect(db)
    try:
        bench._schema(conn)
        rows = conn.execute(
            "SELECT b.variant, b.passed, b.is_error, b.duration_s, b.reported_cost, b.skill_check, "
            "sum(r.input + r.cache_read + r.cache_write_5m + r.cache_write_1h + r.output) "
            "FROM bench_runs b LEFT JOIN requests r USING (session_id) WHERE b.task = ? AND b.variant IN (?, ?) "
            "AND b.started_at >= ? GROUP BY b.run_id", (b["task"], *b["versions"], b["started"])).fetchall()
    finally:
        conn.close()
    out = []
    for label, v in zip(("current", "draft"), b["versions"]):
        mine = [r for r in rows if r[0] == v]
        pick = lambda i: [r[i] for r in mine if r[i] is not None]  # noqa: E731
        checks = {}
        for r in mine:
            checks[r[5] or "–"] = checks.get(r[5] or "–", 0) + 1
        out.append({"label": label, "version": v, "runs": len(mine), "passed": sum(r[1] or 0 for r in mine),
                    "errors": sum(r[2] or 0 for r in mine), "cost": median(pick(4)) if pick(4) else None,
                    "tokens": median(pick(6)) if pick(6) else None, "seconds": median(pick(3)) if pick(3) else None,
                    "checks": checks})
    return out
