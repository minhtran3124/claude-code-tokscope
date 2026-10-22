"""Read your Managed Agents (Claude Developer Platform) through the `ant` CLI, for the dashboard's Managed page.

tokscope never sees a token: `ant` signs in, refreshes and picks the workspace, and tokscope reads what its list
commands print. The list commands and one write, pausing or unpausing a deployment (act), are all that run here, each
with an argument list (no shell) and a timeout. A failure comes back as text to show, so the page still answers.
Results are kept CACHE_S seconds; refresh=True reads again, and a write clears them."""

import json
import re
import shutil
import subprocess
import time

TIMEOUT = 30
CACHE_S = 60.0
SESSIONS = 100  # the latest sessions read; deployment and agent totals count these only
ACTIONS = ("pause", "unpause")
DEPLOYMENT_ID = re.compile(r"^depl_[A-Za-z0-9]{8,64}$")
_cache = {}


def _run(args):
    """One `ant` list command as a list of objects; jsonl prints one object per line."""
    exe = shutil.which("ant")
    if not exe:
        raise RuntimeError("ant is not installed")
    try:
        out = subprocess.run([exe, *args, "--format", "jsonl"], capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ant did not answer in {TIMEOUT} s") from None
    if out.returncode:
        lines = [l for l in (out.stderr or out.stdout).strip().splitlines() if l.strip()]
        raise RuntimeError(" ".join(lines[:3])[:300] or f"ant exited with {out.returncode}")
    try:
        return [json.loads(l) for l in out.stdout.splitlines() if l.strip()]
    except ValueError:
        raise RuntimeError("ant printed something that is not JSON") from None


def _cents(money):
    """{amount: "2500", currency: "USD"} (minor units) -> 25.0; anything else -> None."""
    try:
        return int((money or {}).get("amount")) / 100
    except (TypeError, ValueError):
        return None


def _tokens(usage):
    u = usage or {}
    cc = u.get("cache_creation") or {}
    return sum(int(x or 0) for x in (u.get("input_tokens"), u.get("output_tokens"), u.get("cache_read_input_tokens"),
                                     cc.get("ephemeral_5m_input_tokens"), cc.get("ephemeral_1h_input_tokens")))


def _ref(v):
    """An agent field is an id string or an object with an id."""
    return v.get("id") if isinstance(v, dict) else v


def session(s):
    usage = s.get("usage") or {}
    return {"id": s.get("id", ""), "title": s.get("title") or "", "status": s.get("status") or "",
            "created_at": s.get("created_at") or "", "agent": _ref(s.get("agent")) or "",
            "deployment": s.get("deployment_id") or "", "active_s": float(usage.get("active_seconds") or 0),
            "tokens": _tokens(usage), "cost": _cents(usage.get("list_cost"))}


def _sums(sessions, key):
    out = {}
    for s in sessions:
        t = out.setdefault(s[key], {"sessions": 0, "tokens": 0, "cost": 0.0})
        t["sessions"] += 1
        t["tokens"] += s["tokens"]
        t["cost"] += s["cost"] or 0
    return out


def deployment(d, sums):
    sched = d.get("schedule") or {}
    upcoming = sched.get("upcoming_runs_at") or []
    return {"id": d.get("id", ""), "name": d.get("name") or "", "status": d.get("status") or "",
            "paused": (d.get("paused_reason") or {}).get("type") or "", "agent": _ref(d.get("agent")) or "",
            "cron": sched.get("expression") or "", "tz": sched.get("timezone") or "",
            "next": upcoming[0] if upcoming else "", "budget": _cents((d.get("budget") or {}).get("max_list_cost")),
            **sums.get(d.get("id"), {"sessions": 0, "tokens": 0, "cost": 0.0})}


def agent(a, sums):
    model = a.get("model") or {}
    effort = model.get("effort")
    return {"id": a.get("id", ""), "name": a.get("name") or "", "model": model.get("id") or "",
            "effort": (effort.get("type") if isinstance(effort, dict) else effort) or "",
            "mcp": [m.get("name") or m.get("url") or "" for m in a.get("mcp_servers") or []],
            "skills": [k.get("skill_id") or k.get("name") or k.get("id") or "" for k in a.get("skills") or [] if isinstance(k, dict)],
            **sums.get(a.get("id"), {"sessions": 0, "tokens": 0, "cost": 0.0})}


def read(refresh=False, run=None):
    """{"deployments", "sessions", "agents", "read_at"} or {"error", "read_at"}; one error stops the read."""
    run = run or _run
    hit = _cache.get("all")
    if hit and not refresh and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    try:
        sessions = [session(s) for s in run(["beta:sessions", "list", "--max-items", str(SESSIONS)])]
        deps = run(["beta:deployments", "list"])
        agents = run(["beta:agents", "list"])
        by_dep, by_agent = _sums(sessions, "deployment"), _sums(sessions, "agent")
        data = {"deployments": [deployment(d, by_dep) for d in deps], "sessions": sessions,
                "agents": [agent(a, by_agent) for a in agents]}
    except RuntimeError as e:
        data = {"error": str(e)}
    except (AttributeError, KeyError, TypeError, ValueError) as e:  # a field of a shape this code does not know
        data = {"error": f"ant printed data tokscope cannot read ({type(e).__name__}: {str(e)[:200]})"}
    data["read_at"] = time.time()
    _cache["all"] = (time.monotonic(), data)
    return data


def forget():
    _cache.clear()


def act(action, dep_id, run=None):
    """Pause or unpause one deployment and return its new status. ValueError: not an action or not a deployment id,
    checked before ant runs; RuntimeError: ant failed."""
    if action not in ACTIONS:
        raise ValueError("pause or unpause only")
    if not isinstance(dep_id, str) or not DEPLOYMENT_ID.match(dep_id):
        raise ValueError("not a deployment id")
    try:
        out = (run or _run)(["beta:deployments", action, "--deployment-id", dep_id])
    finally:
        forget()  # whatever ant did, the next read shows it
    return (out[0].get("status") if out and isinstance(out[0], dict) else None) or ""
