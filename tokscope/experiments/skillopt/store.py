"""The files of one optimize run: plan.json and its lock, the cost ledger, the run lock, per-result folders that resume
can trust, and the opt_results index. Files are the source of truth; the SQLite table is rebuilt from them."""
import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from ... import paths
from ...core import ingest
from . import suite
from .sandbox import MAX_BUDGET_USD, _name

SCHEMA_VERSION = 1
PLAN, LEDGER, LOCK = "plan.json", "ledger.jsonl", "run.lock"
PAID = ("run", "editor", "lost")  # ledger kinds that spend money

TABLE = """
CREATE TABLE IF NOT EXISTS opt_results(
    run_id TEXT, skill TEXT, stage TEXT, case_id TEXT, arm TEXT, idx INTEGER, fingerprint TEXT, session_id TEXT,
    status TEXT, load TEXT, passed INTEGER, total INTEGER, pass_rate REAL, safety_failed INTEGER, cost_usd REAL,
    duration_s REAL, tokens INTEGER, PRIMARY KEY(run_id, stage, case_id, arm, idx));
CREATE INDEX IF NOT EXISTS opt_results_session ON opt_results(session_id);
"""


class LockError(ValueError):
    """The plan was edited, the frozen suite changed, or another process holds the run (the CLI exits 2)."""


def runs_dir():
    return paths.home() / "bench" / "optimize" / "runs"


def new_run(skill, now=None):
    """Create <runs>/<skill>-<UTC yyyymmddThhmmssZ>/ and return it."""
    _name("skill", skill)
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    base = runs_dir()
    base.mkdir(parents=True, exist_ok=True)
    for n in range(1, 100):
        run = base / (f"{skill}-{stamp}" + (f"-{n}" if n > 1 else ""))
        try:
            run.mkdir()
            return run
        except FileExistsError:
            continue
    raise ValueError(f"{skill}: could not create a run folder")


def find_run(run_id):
    _name("run id", run_id)
    run = runs_dir() / run_id
    if not (run / PLAN).is_file():
        raise ValueError(f"no run {run_id!r} under {runs_dir()}")
    return run


def read_plan(run):
    return json.loads((Path(run) / PLAN).read_text())


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def write_plan(run, plan):
    """plan.json, then the first ledger line, which holds the hash of plan.json's bytes. Kept outside plan.json so a
    hand edit of the plan cannot update the hash it is checked against."""
    run = Path(run)
    data = (json.dumps(plan, indent=2, sort_keys=True) + "\n").encode()
    (run / PLAN).write_bytes(data)
    append(run, {"kind": "lock", "plan_sha256": _sha(data)})


def check_lock(run):
    """LockError when plan.json no longer has the hash locked in the ledger, or the frozen suite no longer has the
    plan's suite hash. Run before every resume and regrade."""
    run = Path(run)
    first = next(iter(lines(run)), {})
    try:
        data = (run / PLAN).read_bytes()
    except OSError:
        raise LockError(f"{run.name}: no {PLAN}") from None
    if first.get("kind") != "lock" or first.get("plan_sha256") != _sha(data):
        raise LockError(f"{run.name}: {PLAN} changed after it was locked; start a new run")
    try:
        frozen = suite.suite_hash(json.loads((run / "suite" / "evals" / suite.NAME).read_text()))
    except (OSError, ValueError):
        raise LockError(f"{run.name}: the frozen suite is missing or unreadable") from None
    if frozen != json.loads(data.decode())["suite_hash"]:
        raise LockError(f"{run.name}: the frozen suite changed after it was locked; start a new run")


# ledger

def append(run, line):
    """One JSON line, flushed to disk before the call returns."""
    with open(Path(run) / LEDGER, "a") as f:
        f.write(json.dumps(line, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


def lines(run):
    """The ledger's lines in order; a torn last line (a crash mid-write) is skipped."""
    try:
        text = (Path(run) / LEDGER).read_text()
    except OSError:
        return []
    out = []
    for raw in text.splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if isinstance(line, dict):
            out.append(line)
    return out


def spent(run):
    return sum(l.get("cost_usd") or 0 for l in lines(run) if l.get("kind") in PAID)


def reserve(run, plan):
    """The most one more call may cost: the highest cost of a run or editor line so far; before any, the cap of one
    run (the lower of MAX_BUDGET_USD and the budget)."""
    costs = [l.get("cost_usd") or 0 for l in lines(run) if l.get("kind") in ("run", "editor")]
    return max(costs) if costs else min(MAX_BUDGET_USD, plan["budget_usd"])


def can_spend(run, plan):
    return spent(run) + reserve(run, plan) <= plan["budget_usd"] + 1e-9 and call_cap(run, plan) > 0


def call_cap(run, plan):
    """The --max-budget-usd of the next call: no more than a run's cap, and no more than what is left."""
    return round(min(MAX_BUDGET_USD, plan["per_run_cap_usd"], plan["budget_usd"] - spent(run)), 6)


def start(run, plan, stage, case, arm, i):
    """Ledger line written before a paid call: its cap is what a `lost` line charges if the call never ends."""
    cap = call_cap(run, plan)
    append(run, {"kind": "start", "stage": stage, "case": case, "arm": arm, "i": i, "cap": cap})
    return cap


# results

def key(stage, case, arm, i):
    return {"stage": stage, "case": str(case), "arm": arm, "i": int(i)}


def result_dir(run, stage, case, arm, i):
    return Path(run) / "results" / stage / str(case) / arm / str(i)


def _same(line, k):
    return all(line.get(f) == k[f] for f in k)


def result_state(run, stage, case, arm, i):
    """done: the folder and its `run` line exist. recover: the folder exists without its line. lost: only a `.tmp`
    folder is left (the process died inside the call). todo: nothing."""
    final = result_dir(run, stage, case, arm, i)
    k = key(stage, case, arm, i)
    if final.is_dir():
        return "done" if any(l.get("kind") == "run" and _same(l, k) for l in lines(run)) else "recover"
    return "lost" if final.with_name(final.name + ".tmp").exists() else "todo"


def tmp_dir(run, stage, case, arm, i):
    final = result_dir(run, stage, case, arm, i)
    return final.with_name(final.name + ".tmp")


def _line(k, meta):
    return {"kind": "run", **k, "cost_usd": meta.get("cost_usd") or 0, "status": meta.get("status")}


def recover(run, stage, case, arm, i):
    """Add the missing `run` line of a finished folder from its run.json."""
    k = key(stage, case, arm, i)
    meta = json.loads((result_dir(run, stage, case, arm, i) / "run.json").read_text())
    append(run, _line(k, meta))


def discard(run, plan, stage, case, arm, i):
    """Delete a `.tmp` folder and charge a `lost` line: the cap the call started with, else the reserve."""
    k = key(stage, case, arm, i)
    caps = [l["cap"] for l in lines(run) if l.get("kind") == "start" and _same(l, k) and "cap" in l]
    shutil.rmtree(tmp_dir(run, stage, case, arm, i), ignore_errors=True)
    append(run, {"kind": "lost", **k, "cost_usd": caps[-1] if caps else reserve(run, plan)})


def finish(run, stage, case, arm, i):
    """Rename `<i>.tmp` to `<i>` (the result is whole), then write its ledger line."""
    k = key(stage, case, arm, i)
    final = result_dir(run, stage, case, arm, i)
    os.rename(tmp_dir(run, stage, case, arm, i), final)
    append(run, _line(k, json.loads((final / "run.json").read_text())))
    return final


def editor_dir(run, n):
    return Path(run) / "rounds" / str(n) / "editor"


def editor_done(run, n):
    """An editor call is done when its result.json exists and its `editor` ledger line is written."""
    return (editor_dir(run, n) / "result.json").is_file() and any(
        l.get("kind") == "editor" and l.get("round") == n for l in lines(run))


def records(run):
    """Every finished result as a stats record, read from grading.json and run.json."""
    out = []
    for g in sorted(Path(run).glob("results/*/*/*/*/grading.json")):
        folder = g.parent
        if folder.name.endswith(".tmp") or not (folder / "run.json").is_file():
            continue
        grading, meta = json.loads(g.read_text()), json.loads((folder / "run.json").read_text())
        stage, case, arm = g.parts[-5], g.parts[-4], g.parts[-3]
        usage = meta.get("usage") or {}
        out.append({"stage": stage, "case": case, "arm": arm, "i": int(folder.name), "status": grading.get("status"),
                    "load": meta.get("load"), "passed": grading.get("passed"), "total": grading.get("total"),
                    "safety_failed": grading.get("safety_failed") or 0, "cost_usd": meta.get("cost_usd"),
                    "duration_s": meta.get("duration_s"), "session_id": meta.get("session_id"),
                    "fingerprint": meta.get("fingerprint"), "num_turns": meta.get("num_turns"),
                    "tokens": sum(v for v in usage.values() if isinstance(v, (int, float))) or None,
                    "expectations": grading.get("expectations") or [], "reason": grading.get("reason")})
    return out


def index(run):
    """Rebuild this run's rows of opt_results from the result files (DELETE, then INSERT)."""
    run = Path(run)
    rows = []
    for r in records(run):
        rate = r["passed"] / r["total"] if r.get("total") else None
        rows.append((run.name, read_plan(run)["skill"], r["stage"], r["case"], r["arm"], r["i"], r["fingerprint"],
                     r["session_id"], r["status"], r["load"], r["passed"], r["total"], rate, r["safety_failed"],
                     r["cost_usd"], r["duration_s"], r["tokens"]))
    conn = ingest.connect(paths.db())
    try:
        conn.executescript(TABLE)
        conn.execute("DELETE FROM opt_results WHERE run_id = ?", (run.name,))
        conn.executemany("INSERT INTO opt_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        conn.commit()
    finally:
        conn.close()
    return len(rows)


# run lock

def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire(run):
    """Take run.lock with this pid (O_EXCL). A live pid in it refuses; a dead pid's lock is taken over."""
    path = Path(run) / LOCK
    for _ in range(3):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                pid = int(path.read_text().strip())
            except (OSError, ValueError):
                pid = 0
            if pid and _alive(pid) and pid != os.getpid():
                raise LockError(f"{Path(run).name}: another process (pid {pid}) is running it") from None
            path.unlink(missing_ok=True)
            time.sleep(0.01)
            continue
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return path
    raise LockError(f"{Path(run).name}: could not take {LOCK}")


def release(run):
    path = Path(run) / LOCK
    try:
        if path.read_text().strip() == str(os.getpid()):
            path.unlink()
    except OSError:
        pass
