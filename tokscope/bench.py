"""Before/after benchmark: run one fixed task per variant in fresh headless sessions, then compare cost and quality.

Variants run interleaved, the order flipping each round (a, b, b, a, a, b, ...), so prompt-cache warmth does
not favour one variant.
"""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import tarfile
import io
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from .ingest import connect, ingest_session

BENCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS bench_runs (
    run_id TEXT PRIMARY KEY, task TEXT, variant TEXT, run_idx INTEGER, session_id TEXT, started_at TEXT,
    duration_s REAL, exit_code INTEGER, is_error INTEGER, reported_cost REAL, passed INTEGER,
    result TEXT, commit_sha TEXT, cc_version TEXT, skill_check TEXT
);
"""


def _schema(conn):
    conn.executescript(BENCH_SCHEMA)
    if "skill_check" not in {c[1] for c in conn.execute("PRAGMA table_info(bench_runs)")}:
        conn.execute("ALTER TABLE bench_runs ADD COLUMN skill_check TEXT")


def load_task(path):
    return json.loads(Path(path).read_text())


def snapshot_dir(root, sha):
    # named by commit only: a reviewer reads its own path, and a task name like "pool-hold" gives the answer away
    return Path(root) / "bench" / "snapshots" / f"s-{sha[:10]}"


def prepare(root, task):
    """Export the task's paths at its commit into a snapshot dir (no git state touched). Returns (dir, sha)."""
    sha = subprocess.run(["git", "-C", task["repo"], "rev-parse", task["commit"]], check=True,
                         capture_output=True, text=True).stdout.strip()
    dest = snapshot_dir(root, sha)
    stamp = dest / ".bench-commit"
    if stamp.exists() and stamp.read_text().strip() == sha:
        return dest, sha
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    archive = subprocess.run(["git", "-C", task["repo"], "archive", sha, *task["paths"]], check=True,
                             capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(dest)
    for rel in task.get("copy", []):
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(task["repo"]) / rel, dest / rel)
    stamp.write_text(sha + "\n")
    return dest, sha


def grade(task, text):
    """All patterns must match; with `window`, all within one span of that many characters (one finding)."""
    grader = task.get("grader", {})
    hits = [[m.start() for m in re.finditer(p, text or "", re.IGNORECASE)] for p in grader.get("all", [])]
    if not all(hits):
        return False
    window = grader.get("window")
    if window is None:
        return True
    # the span starting at each hit of the first pattern must reach a hit of every other pattern
    return any(all(any(abs(pos - start) <= window for pos in other) for other in hits[1:]) for start in hits[0])


def schedule(variants, runs):
    """Interleaved run order: [(run_idx, variant), ...]. Each round runs the variants in the reverse order of the
    round before, so the first run of a benchmark, which writes the prompt cache the rest read, is not always the
    same variant's."""
    return [(i, v) for i in range(runs) for v in (variants if i % 2 == 0 else variants[::-1])]


def _claude_bin():
    local = Path.home() / ".local" / "bin" / "claude"
    return str(local) if local.exists() else shutil.which("claude")


def version_dir(snapshot, skill, version):
    """The task's snapshot with one skill version pinned: hard links to the snapshot's files (cheap, read-only use),
    real copies for the skill, so each variant reads its own version and runs can interleave."""
    from .skills import pin

    dest = snapshot.parent / f"{snapshot.name}-{version[:8]}"
    if not dest.exists():
        shutil.copytree(snapshot, dest, copy_function=os.link)
    pin(skill, version, dest)
    return dest


def run_one(task, variant, run_idx, cwd, sha):
    run_id = uuid.uuid4().hex[:12]
    # a skill-version variant has no entry in the task; its prompt may name {version} and {skill}
    prompt = task["prompt"].format(**{"version": variant, "skill": task.get("skill", ""), **task.get("variants", {}).get(variant, {})})
    env = dict(os.environ)
    # tags every OTel event of the run, so a run can also be read from data/otel/
    env["OTEL_RESOURCE_ATTRIBUTES"] = f"bench.task={task['name']},bench.variant={variant},bench.run={run_id}"
    cmd = [_claude_bin(), "-p", prompt, "--model", task["main_model"], "--max-budget-usd", str(task["max_budget_usd"]),
           "--allowedTools", " ".join(task["allowed_tools"]), "--output-format", "json"]
    started = time.time()
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=task.get("timeout_s", 900))
        exit_code, stdout = proc.returncode, proc.stdout
    except subprocess.TimeoutExpired:
        exit_code, stdout = -1, ""
    try:
        out = json.loads(stdout)
    except json.JSONDecodeError:
        out = {"is_error": True, "result": stdout[-2000:]}
    return {
        "run_id": run_id, "task": task["name"], "variant": variant, "run_idx": run_idx,
        "session_id": out.get("session_id"), "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(),
        "duration_s": round(time.time() - started, 1), "exit_code": exit_code,
        "is_error": int(bool(out.get("is_error")) or exit_code != 0), "reported_cost": out.get("total_cost_usd"),
        "passed": int(grade(task, out.get("result", ""))), "result": out.get("result", ""), "commit_sha": sha,
        "cc_version": (subprocess.run([_claude_bin(), "--version"], capture_output=True, text=True).stdout.split() or ["?"])[0],
    }


def save_run(conn, row):
    _schema(conn)
    cols = list(row)
    conn.execute(f"INSERT INTO bench_runs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [row[c] for c in cols])
    conn.commit()


def run(root, db_path, phases_path, task, runs, variants=None, skill=None, versions=None, log=print):
    """Run the task's variants, or with skill and versions, one variant per pinned skill version."""
    from .skills import check_load, check_pinnable, resolve_version

    if skill:  # fail before exporting or spending anything
        check_pinnable(skill)
        versions = [resolve_version(skill, v) for v in versions]
    cwd, sha = prepare(root, task)
    dirs = {}
    if skill:
        task = {**task, "skill": skill}
        dirs = {v: version_dir(cwd, skill, v) for v in versions}
        variants = versions
    variants = variants or list(task["variants"])
    conn = connect(db_path)
    for run_idx, variant in schedule(variants, runs):
        row = run_one(task, variant, run_idx, dirs.get(variant, cwd), sha)
        if row["session_id"]:
            ingest_session(db_path, phases_path, row["session_id"])
        if skill:
            # the transcript says which text the model read; a run on the wrong version must not count as this one
            row["skill_check"] = check_load(conn, row["session_id"], skill, variant) if row["session_id"] else "not loaded"
        save_run(conn, row)
        log(f"{variant:<12} run {run_idx}  {'PASS' if row['passed'] else 'FAIL'}  "
            f"${row['reported_cost'] or 0:.3f}  {row['duration_s']}s  error={row['is_error']}  session={row['session_id']}"
            + (f"  skill={row['skill_check']}" if skill else ""))
    conn.close()


def regrade(db_path, task, skill=None):
    """Re-apply the task's current grader to stored answers (the task's own runs and its -leaky ones); with skill,
    also re-check which version each run read (a newer ingest may have found text an older one missed)."""
    from .skills import check_load

    conn = sqlite3.connect(db_path)
    _schema(conn)
    rows = conn.execute("SELECT run_id, result, passed FROM bench_runs WHERE task IN (?, ?)",
                        (task["name"], task["name"] + "-leaky")).fetchall()
    changed = [(int(grade(task, text)), run_id) for run_id, text, passed in rows if int(grade(task, text)) != passed]
    conn.executemany("UPDATE bench_runs SET passed = ? WHERE run_id = ?", changed)
    if skill:
        conn.executemany("UPDATE bench_runs SET skill_check = ? WHERE run_id = ?",
                         [(check_load(conn, sid, skill, variant), run_id) for run_id, sid, variant in conn.execute(
                             "SELECT run_id, session_id, variant FROM bench_runs WHERE task = ? AND skill_check IS NOT NULL",
                             (task["name"],)).fetchall()])
    conn.commit()
    return len(rows), len(changed)


def _spread(values):
    if not values:
        return "–"
    return f"{median(values):.3f} [{min(values):.3f}–{max(values):.3f}]"


def diff(db_path, task_name):
    """Per-variant median [min–max] of cost split by owner, tokens, time and pass rate."""
    conn = sqlite3.connect(db_path)
    _schema(conn)
    rows = conn.execute(
        """SELECT b.variant, b.passed, b.is_error, b.duration_s, b.reported_cost, b.skill_check,
                  sum(r.cost_usd), sum(CASE WHEN r.agent_id IS NULL THEN r.cost_usd END),
                  sum(CASE WHEN r.agent_id IS NOT NULL THEN r.cost_usd END), sum(r.output),
                  group_concat(DISTINCT CASE WHEN r.agent_id IS NOT NULL THEN r.model END)
           FROM bench_runs b LEFT JOIN requests r USING (session_id)
           WHERE b.task = ? GROUP BY b.run_id ORDER BY b.variant, b.run_idx""",
        (task_name,),
    ).fetchall()
    by_variant = {}
    for v, passed, err, dur, reported, check, total, main, agents, out, models in rows:
        d = by_variant.setdefault(v, {"n": 0, "pass": 0, "err": 0, "total": [], "main": [], "agents": [], "out": [],
                                      "dur": [], "reported": [], "models": set(), "checks": {}})
        if check:
            d["checks"][check] = d["checks"].get(check, 0) + 1
        d["n"] += 1
        d["pass"] += passed
        d["err"] += err
        for key, val in (("total", total), ("main", main), ("agents", agents), ("out", out), ("dur", dur),
                         ("reported", reported)):
            if val is not None:
                d[key].append(val)
        d["models"].update((models or "").split(","))
    lines = [f"task {task_name}: median [min–max] per run"]
    header = f"{'variant':<10} {'runs':>4} {'pass':>5} {'err':>4}  {'total $':<22} {'main $':<22} {'subagents $':<22} {'output tok':<26} {'seconds':<22} subagent model"
    lines.append(header)
    for v, d in by_variant.items():
        out_spread = "–" if not d["out"] else f"{median(d['out']):,.0f} [{min(d['out']):,}–{max(d['out']):,}]"
        lines.append(
            f"{v:<10} {d['n']:>4} {d['pass']:>3}/{d['n']:<1} {d['err']:>4}  {_spread(d['total']):<22} {_spread(d['main']):<22} "
            f"{_spread(d['agents']):<22} {out_spread:<26} {_spread(d['dur']):<22} {','.join(sorted(m for m in d['models'] if m))}"
            + (f"  skill: {', '.join(f'{k} {n}' for k, n in sorted(d['checks'].items()))}" if d["checks"] else "")
        )
    if any(set(d["checks"]) - {"ok"} for d in by_variant.values()):
        lines.append("skill check: only 'ok' runs read the pinned version; compare variants on those, or rerun.")
    return "\n".join(lines)
