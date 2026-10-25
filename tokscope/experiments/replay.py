"""Replay a real session's human prompts in fresh headless sessions and compare tokens turn by turn.

Each run gets its own detached git worktree at the commit the original session started from, with today's
local-only harness (.claude entries git does not track, CLAUDE.local.md, specs/) linked in, so the replay
measures the current harness on yesterday's task. Tool access is an allow-list of read-only tools.
"""

import json
import os
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from ..core import errors
from ..core.ingest import COMMAND_RE, find_transcripts, _is_human_prompt, _text, BUILTIN_COMMANDS, connect, ingest_session

ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
TOKENS = "(input + cache_read + cache_write_5m + cache_write_1h + output)"

# read-only by construction: anything not listed is denied in a headless run
ALLOWED_TOOLS = [
    "Read", "Grep", "Glob", "ToolSearch", "Agent", "Skill", "TodoWrite",
    "Bash(grep:*)", "Bash(rg:*)", "Bash(sed -n:*)", "Bash(cat:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(ls:*)",
    "Bash(find:*)", "Bash(wc:*)", "Bash(git log:*)", "Bash(git show:*)", "Bash(git diff:*)", "Bash(git fetch:*)",
    "Bash(git status:*)", "Bash(git blame:*)",
    "mcp__plugin_datadog_mcp__*",
    "mcp__plugin_sentry_sentry__search_issues", "mcp__plugin_sentry_sentry__search_errors",
    "mcp__plugin_sentry_sentry__search_traces", "mcp__plugin_sentry_sentry__search_logs",
    "mcp__plugin_sentry_sentry__get_sentry_resource", "mcp__plugin_sentry_sentry__find_organizations",
    "mcp__plugin_sentry_sentry__find_projects", "mcp__plugin_sentry_sentry__search_sentry_tools",
]
# named even though the allow-list already excludes them, so a later allow-list edit cannot let them in
DISALLOWED_TOOLS = [
    "Edit", "Write", "NotebookEdit", "Bash(git push:*)", "Bash(git commit:*)", "Bash(gh:*)", "Bash(rm:*)",
    "mcp__plugin_sentry_sentry__execute_sentry_tool", "mcp__plugin_sentry_sentry__update_issue",
    "mcp__plugin_sentry_sentry__analyze_issue_with_seer",
]

REPLAY_SCHEMA = """
CREATE TABLE IF NOT EXISTS replay_runs (
    run_id TEXT PRIMARY KEY, source_session TEXT, run_idx INTEGER, session_id TEXT, commit_sha TEXT,
    started_at TEXT, duration_s REAL, turns INTEGER, errors INTEGER, denials INTEGER, reported_cost REAL, status TEXT
);
CREATE TABLE IF NOT EXISTS replay_turns (
    run_id TEXT, turn INTEGER, prompt TEXT, exit_code INTEGER, is_error INTEGER, denials INTEGER,
    duration_s REAL, result TEXT, orig_idx TEXT, PRIMARY KEY (run_id, turn)
);
"""


def _schema(conn):
    conn.executescript(REPLAY_SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(replay_turns)")}
    if "orig_idx" not in cols:
        conn.execute("ALTER TABLE replay_turns ADD COLUMN orig_idx TEXT")
    run_cols = {r[1] for r in conn.execute("PRAGMA table_info(replay_runs)")}
    for col in ("variant", "skill_check"):  # a run pinned to one skill version, and whether it read that version
        if col not in run_cols:
            conn.execute(f"ALTER TABLE replay_runs ADD COLUMN {col} TEXT")


def find_transcript(session_id, projects_dir=None):
    matches = find_transcripts(session_id, projects_dir)
    if not matches:
        raise FileNotFoundError(f"no transcript for session {session_id}")
    return matches[0]


def extract_prompts(path):
    """Human prompts as the model saw them: prompts sent before any answer (typed ahead, or after an Esc) merge
    into one turn. Returns ([{"text", "orig": [original prompt indexes]}], cwd, first_ts)."""
    groups, cwd, first_ts, answered, idx = [], None, None, True, 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            first_ts = first_ts or rec.get("timestamp")
            cwd = cwd or rec.get("cwd")
            if rec.get("type") == "assistant":
                answered = True
                continue
            if rec.get("type") != "user" or not _is_human_prompt(rec):
                continue
            text = _text(rec.get("message", {}).get("content"))
            match = COMMAND_RE.search(text)
            if match:
                if match.group(1) in BUILTIN_COMMANDS:
                    continue
                args = ARGS_RE.search(text)
                text = f"/{match.group(1)} {args.group(1).strip() if args else ''}".strip()
            idx += 1  # same numbering as ingest's prompt_idx
            if groups and not answered:
                groups[-1]["text"] += "\n\n" + text
                groups[-1]["orig"].append(idx)
            else:
                groups.append({"text": text, "orig": [idx]})
            answered = False
    return groups, cwd, first_ts


def commit_at(repo, ts, ref="github/main"):
    out = subprocess.run(["git", "-C", repo, "rev-list", "-1", f"--before={ts}", ref], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def make_worktree(repo, sha, dest):
    subprocess.run(["git", "-C", repo, "worktree", "add", "--detach", str(dest), sha], capture_output=True, check=True)
    # today's harness: link what git does not carry (local-only skills, agents, settings, plans)
    for rel in ("CLAUDE.local.md", "specs"):
        if (Path(repo) / rel).exists() and not (dest / rel).exists():
            (dest / rel).symlink_to(Path(repo) / rel)
    for sub in (".claude", ".claude/skills", ".claude/agents"):
        src_dir = Path(repo) / sub
        if not src_dir.is_dir():
            continue
        (dest / sub).mkdir(parents=True, exist_ok=True)
        for entry in src_dir.iterdir():
            if not (dest / sub / entry.name).exists() and not (dest / sub / entry.name).is_symlink():
                (dest / sub / entry.name).symlink_to(entry)


def remove_worktree(repo, dest):
    subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", str(dest)], capture_output=True)


def build_cmd(claude, prompt, session_id, first, model=None, budget=3.0):
    cmd = [claude, "-p", prompt, "--output-format", "json", "--permission-mode", "default", "--max-budget-usd", str(budget),
           "--allowedTools", *ALLOWED_TOOLS, "--disallowedTools", *DISALLOWED_TOOLS]
    cmd += ["--session-id", session_id] if first else ["--resume", session_id]
    if model:
        cmd += ["--model", model]
    return cmd


def _claude_bin():
    local = Path.home() / ".local" / "bin" / "claude"
    return str(local) if local.exists() else "claude"


def run(root, db_path, phases_path, source_session, runs=2, budget_total=6.0, model=None, skill=None, versions=None,
        log=print):
    """Replay the session `runs` times; with skill and versions, run i pins versions[i % len(versions)]."""
    from ..core.skills import check_load, check_pinnable, pin, resolve_version

    if skill:
        check_pinnable(skill)
    versions = [resolve_version(skill, v) for v in versions] if skill else []
    path = find_transcript(source_session)
    groups, cwd, first_ts = extract_prompts(path)
    prompts = [g["text"] for g in groups]
    repo = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip()
    sha = commit_at(repo, first_ts)
    log(f"replaying {len(prompts)} prompts of {source_session[:8]} at {sha[:10]}, {runs} runs, budget ${budget_total}")
    conn = connect(db_path)
    _schema(conn)
    spent = 0.0
    for run_idx in range(runs):
        run_id, session_id = uuid.uuid4().hex[:12], str(uuid.uuid4())
        # under bench/ so the report keeps replay sessions out of real usage
        dest = Path(root) / "bench" / "replay" / f"wt-{run_id}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        make_worktree(repo, sha, dest)
        variant = versions[run_idx % len(versions)] if versions else None
        if variant:
            pin(skill, variant, dest)
            log(f"  run {run_idx}: {skill} pinned at {variant}")
        started, errors, denials, cost, status = time.time(), 0, 0, None, "done"
        env = dict(os.environ, OTEL_RESOURCE_ATTRIBUTES=f"replay.source={source_session},replay.run={run_id}")
        try:
            for turn, prompt in enumerate(prompts, start=1):
                t0 = time.time()
                proc = subprocess.run(build_cmd(_claude_bin(), prompt, session_id, turn == 1, model), cwd=dest, env=env,
                                      capture_output=True, text=True, timeout=1800)
                try:
                    out = json.loads(proc.stdout)
                except json.JSONDecodeError:
                    out = {"is_error": True, "result": (proc.stdout or proc.stderr)[-2000:]}
                n_denied = len(out.get("permission_denials") or [])
                errors += int(bool(out.get("is_error")) or proc.returncode != 0)
                denials += n_denied
                cost = out.get("total_cost_usd", cost)
                conn.execute("INSERT INTO replay_turns VALUES (?,?,?,?,?,?,?,?,?)",
                             (run_id, turn, prompt, proc.returncode, int(bool(out.get("is_error"))), n_denied,
                              round(time.time() - t0, 1), (out.get("result") or "")[:20000],
                              ",".join(map(str, groups[turn - 1]["orig"]))))
                conn.commit()
                log(f"  run {run_idx} turn {turn}/{len(prompts)}: exit={proc.returncode} denied={n_denied} "
                    f"{time.time() - t0:.0f}s cumulative=${cost or 0:.2f}")
                if spent + (cost or 0) > budget_total:
                    status = "stopped: budget"
                    log(f"  stopping: ${spent + (cost or 0):.2f} would pass the ${budget_total} budget")
                    break
        finally:
            remove_worktree(repo, dest)
        spent += cost or 0
        ingest_session(db_path, phases_path, session_id)
        check = check_load(conn, session_id, skill, variant) if variant else None
        conn.execute("INSERT INTO replay_runs (run_id, source_session, run_idx, session_id, commit_sha, started_at, duration_s, "
                     "turns, errors, denials, reported_cost, status, variant, skill_check) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (run_id, source_session, run_idx, session_id, sha,
                      datetime.fromtimestamp(started, timezone.utc).isoformat(), round(time.time() - started, 1),
                      len(prompts), errors, denials, cost, status, variant, check))
        conn.commit()
        if status != "done":
            break
    conn.close()
    return spent


def turn_tokens(conn, session_id):
    """{prompt_idx: (tokens, output, subagent runs)} for one session."""
    return {i: (t or 0, o or 0, n) for i, t, o, n in conn.execute(
        f"SELECT prompt_idx, sum({TOKENS}), sum(output), count(DISTINCT agent_id) FROM requests "
        f"WHERE session_id = ? AND prompt_idx IS NOT NULL GROUP BY prompt_idx", (session_id,))}


def _fmt(v):
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if v >= div:
            return f"{v / div:.1f}{unit}"
    return str(int(v))


def diff(db_path, source_session, projects_dir=None):
    """Tokens per turn as the model saw it, original vs each replay; a run that replayed merged prompts one by
    one (before merging existed) is summed over the same group."""
    conn = connect(db_path)
    _schema(conn)
    runs = conn.execute("SELECT run_id, run_idx, session_id, errors, denials, duration_s, status, variant, skill_check "
                        "FROM replay_runs WHERE source_session = ? ORDER BY started_at", (source_session,)).fetchall()
    if not runs:
        return f"no replays of {source_session} yet"
    groups, _, _ = extract_prompts(find_transcript(source_session, projects_dir))
    original = turn_tokens(conn, source_session)
    lines = [f"replay of {source_session[:8]}: tokens per turn (output tokens, subagent runs)",
             f"{'turn':<9} {'original':>22} " + " ".join(f"{'run ' + str(r[1]) + (' ' + r[7][:6] if r[7] else ''):>22}" for r in runs)
             + "  prompt"]
    per_run = []
    for run_id, *_ in runs:
        # replay turn -> the original prompt indexes it stood for (old rows: one prompt per turn)
        rows = conn.execute("SELECT turn, orig_idx FROM replay_turns WHERE run_id = ?", (run_id,)).fetchall()
        mapping = {turn: [int(x) for x in (orig or str(turn)).split(",")] for turn, orig in rows}
        tokens = turn_tokens(conn, conn.execute("SELECT session_id FROM replay_runs WHERE run_id = ?", (run_id,)).fetchone()[0])
        per_run.append((mapping, tokens))
    totals = [0] * (len(runs) + 1)
    for g in groups:
        orig = set(g["orig"])
        cells = [[original.get(i) for i in orig]]
        cells += [[tok.get(t) for t, idxs in mapping.items() if set(idxs) <= orig] for mapping, tok in per_run]
        shown = []
        for k, cell in enumerate(cells):
            cell = [c for c in cell if c]
            if not cell:
                shown.append("–")
                continue
            tk, out, n = (sum(c[i] for c in cell) for i in range(3))
            totals[k] += tk
            shown.append(f"{_fmt(tk)} ({_fmt(out)}, {n})")
        label = ",".join(map(str, g["orig"]))
        lines.append(f"{label:<9} " + " ".join(f"{s:>22}" for s in shown) + "  " + g["text"].replace("\n", " ")[:60])
    lines.append(f"{'total':<9} " + " ".join(f"{_fmt(t):>22}" for t in totals))
    if len(totals) > 1 and totals[0]:
        rep = totals[1:]
        lines.append(f"replay median {_fmt(median(rep))} = {median(rep) / totals[0] - 1:+.0%} vs original; "
                     f"spread {_fmt(min(rep))}–{_fmt(max(rep))}")
    pinned = sorted({r[7] for r in runs if r[7]})
    if len(pinned) > 1:
        # one line per pinned version: the median total of its runs that read that version
        for v in pinned:
            vt = [totals[k + 1] for k, r in enumerate(runs) if r[7] == v and r[8] == "ok"]
            checks = ", ".join(sorted({r[8] or "–" for r in runs if r[7] == v}))
            lines.append(f"version {v}: " + (f"median {_fmt(median(vt))} over {len(vt)} checked runs" if vt else "no run read it")
                         + f" (skill check: {checks})")
    lines.append("tool calls: failed / total, repeats, interrupts")
    for label, sid in (("original", source_session), *((f"run {r[1]}", r[2]) for r in runs)):
        e = errors.session(conn, sid)
        lines.append(f"{label:<9} {e['errors']}/{e['calls']} failed ({errors.pct(e['errors'], e['calls'])}), "
                     f"{e['repeats']} repeats, {e['interrupts']} interrupts, {e['api_errors']} API errors")
    for _, idx, _, turn_errors, denials, dur, status, *_ in runs:
        lines.append(f"run {idx}: {status}, {turn_errors} turn errors, {denials} permission denials, {dur:.0f}s")
    return "\n".join(lines)
