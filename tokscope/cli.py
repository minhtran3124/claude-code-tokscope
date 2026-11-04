import argparse
from contextlib import closing
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, paths
from .core.calls import turn_calls
from .core.ingest import connect, ingest, ingest_otel, ingest_session
from .core import tz
from .core.pricing import API_EQ_NOTE, unpriced, unpriced_text
from .core import errors
from .core.summary import SUMMARY_SQL, rows as summary_rows, to_csv as summary_csv, to_json as summary_json
from .core.privacy import LEVELS

ROOT = paths.home()
DB = paths.db()
PHASES = paths.phases()
REPORT = paths.report()

def summary_errors(conn, args, where, params, fmt):
    """`summary --errors`: failed and repeated tool calls, interrupts, API errors and retries per skill, agent or phase."""
    if args.by not in errors.KEYS:
        sys.exit(f"tokscope: --errors groups by {', '.join(errors.KEYS)}, not {args.by}")
    found = errors.rows(conn, args.by, where, params, args.limit)
    if fmt == "json":
        print(summary_json(found))
    elif fmt == "csv":
        print(summary_csv(found, errors.FIELDS), end="")
    else:
        print(f"{args.by:<40} {'calls':>8} {'errors':>7} {'err %':>6} {'repeats':>8} {'interrupts':>10} {'api errors':>10} {'retries':>8} {'failed loads':>12}")
        for r in found:
            print(f"{r['key'][:40]:<40} {r['calls']:>8,} {r['errors']:>7,} {errors.pct(r['errors'], r['calls']):>6} "
                  f"{r['repeats']:>8,} {r['interrupts']:>10,} {r['api_errors']:>10,} {r['retries']:>8,} {r['failed_loads']:>12,}")
    kinds = errors.classes(conn, where, params)
    if kinds:
        print("error classes: " + ", ".join(f"{k} {n}" for k, n in kinds), file=sys.stdout if fmt == "table" else sys.stderr)


def summary(args):
    with closing(connect(DB)) as conn:
        return _summary(args, conn)


def _summary(args, conn):
    where, params = _filters(args)
    fmt = getattr(args, "format", "table")
    if getattr(args, "errors", False):
        return summary_errors(conn, args, where, params, fmt)
    found = summary_rows(conn, args.by, where, params, args.limit)
    if fmt == "json":
        print(summary_json(found))
    elif fmt == "csv":
        print(summary_csv(found), end="")
    else:
        total = sum(r["cost_usd"] for r in found) or 1
        # a phase's carried part comes from later prompts with no skill (see ingest.CARRIED)
        carried = args.by == "phase"
        split = "typed_loads" in (found[0] if found else {})  # by skill with loads: typed /command vs Skill tool
        med = lambda n, m: f"{n}/{m:,.0f}" if n else "-"  # noqa: E731
        print(f"{args.by:<40} {'requests':>9} {'prompt tok':>13} {'output tok':>11} {'API-eq $':>10} {'share':>6}"
              + (f" {'carried':>8}" if carried else "") + (f" {'typed n/med':>14} {'tool n/med':>14}" if split else ""))
        for r in found:
            cost = r["cost_usd"]
            print(f"{r['key'][:40]:<40} {r['requests']:>9,} {r['prompt_tokens']:>13,} {r['output_tokens']:>11,} {cost:>10.2f} {cost / total:>6.1%}"
                  + (f" {r['carried_cost_usd'] / (cost or 1):>8.0%}" if carried else "")
                  + (f" {med(r['typed_loads'], r['typed_median_tokens']):>14} {med(r['tool_loads'], r['tool_median_tokens']):>14}" if split else ""))
    # the notes are not data: with json or csv, stdout holds only the rows
    note_out = sys.stdout if fmt == "table" else sys.stderr
    print(API_EQ_NOTE, file=note_out)
    if note := unpriced_text(unpriced(conn, where, params)):
        print(note, file=note_out)


def patterns_cmd(args):
    """`tokscope patterns`: read-only. It ingests no transcripts and never creates the database file; an existing one is
    opened with connect(), which brings its tables up to date."""
    from .features import patterns

    text = args.since or patterns.default_since()
    try:
        bound = tz.utc_bound(text)
    except ValueError:
        sys.exit(f"tokscope: bad date {text!r}, use YYYY-MM-DD")
    if Path(DB).exists():
        connect(DB).close()
        result = patterns.run(DB, bound, args.privacy)
    else:  # no database yet: nothing to read, and a read must not create one
        result = {"since": bound, "privacy": args.privacy, "groups": [], "unpriced": ""}
    # the notes are not data: with json, stdout holds only the JSON
    note_out = sys.stdout if args.format == "table" else sys.stderr
    print(patterns.to_json(result) if args.format == "json" else patterns.to_table(result))
    for line in patterns.notes(result):
        print(line, file=note_out)


def _budgets(args):
    """The loaded budgets (None when there is no file); a bad file ends the command with its message, exit 2."""
    from .core import budgets

    try:
        return budgets.load()
    except budgets.BudgetError as e:
        print(f"tokscope: budgets.json: {e}", file=sys.stderr)
        sys.exit(2)


def check(args):
    """`tokscope check --once`: print the budget state, exit 0 ok / 10 near / 11 over / 30 no data."""
    from .core import budgets

    with closing(connect(DB)) as conn:
        result = budgets.check(conn, _budgets(args))
    print(json.dumps(result, indent=2) if args.json else budgets.text(result))
    return result["exit"]


def statusline(args):
    """One line for Claude Code's statusLine: green when budgets.json is met, yellow near, red over. Also stores the
    payload's prompt_cache counters (core/cache.py). Never fails."""
    from .core import budgets, cache

    snapshot = None
    if not sys.stdin.isatty():
        try:
            snapshot = json.loads(sys.stdin.read() or "null")  # Claude Code pipes its session JSON
        except ValueError:
            pass
    colour = {"near": "33", "over": "31", "ok": "32"}
    try:
        with closing(connect(DB)) as conn:
            cache.record_snapshot(conn, snapshot)  # the official prompt_cache counters, for Breakdowns
    except Exception:
        pass
    try:
        with closing(connect(DB)) as conn:
            result = budgets.check(conn, budgets.load())
    except budgets.BudgetError:
        return "\033[31mtokscope: budgets.json is invalid (run tokscope check --once)\033[0m"
    warn = budgets.warnings(result)
    if warn:
        return f"\033[{colour[warn[0]['state']]}m{'OVER' if warn[0]['state'] == 'over' else 'near'}: {warn[0]['text']}\033[0m"
    if result["state"] == "ok":
        return "\033[32mtokscope: budgets ok\033[0m"
    return "tokscope"


def _budget_line(session_id):
    """After a session ingest: one line when this session pushed a budget to near or over. Silent otherwise, and on a bad
    or missing budgets.json, so the SessionEnd hook never fails on it."""
    from .core import budgets

    try:
        found = budgets.load()
        with closing(connect(DB)) as conn:
            hit = budgets.crossed(conn, found, session_id) if found else []
    except budgets.BudgetError:
        return
    if hit:
        print("tokscope budget: " + "; ".join(f"{i['state'].upper()} {i['text']}" for i in hit))


def record_skill_versions(lines):
    """A Skill mark from the mod: hash the folder that call loaded, so the load has its exact version."""
    from .core.skills import record_load

    marks = [json.loads(line) for line in lines if line.strip()]
    marks = [m for m in marks if m.get("tool") == "Skill" and m.get("skill") and not m.get("is_error")]
    if not marks:
        return
    with closing(connect(DB)) as conn:
        now = datetime.now(timezone.utc).isoformat()
        for m in marks:
            record_load(conn, m.get("session_id"), m.get("tool_use_id"), m["skill"], m.get("cwd"), now)
        conn.commit()


def skills_text(skill=None, fmt="table"):
    from .core import skills as sk

    with closing(connect(DB)) as conn:
        rows = sk.versions(conn, skill)
    if fmt == "json":
        return json.dumps(sk.export_rows(rows), indent=2)
    if fmt == "csv":
        return sk.to_csv(rows).rstrip("\n")
    if not rows:
        return "tokscope: no skill versions yet; run `tokscope ingest` (and load a skill) first."
    # one block per skill, its versions indented under it, oldest first
    out = [f"{'skill / version':<40} {'first seen':<17} {'loads':>5} {'exact':>5} {'median tokens/load':>19}"]
    last = None
    for r in rows:
        if r["skill"] != last:
            out.append(r["skill"])
            last = r["skill"]
        name = r["version"] or "before tracking"
        if r["label"]:
            name += f" v{r['label']}"
        med = f"{r['tokens_median']:,.0f}" if r["tokens_median"] is not None else "–"
        out.append(f"  {name:<38} {(r['first_seen'] or '')[:16].replace('T', ' '):<17} {r['loads']:>5} {r['exact']:>5} {med:>19}")
    out.append("before tracking = loads from before tokscope knew the skill's content. exact = the mod hashed the folder at "
               "the Skill call; other loads take the version in use at their time.")
    return "\n".join(out)


def session_text(conn, session_id):
    """Plain-text cost breakdown of one session, sized for a transcript line."""
    head = conn.execute(
        "SELECT s.title, count(*), count(DISTINCT agent_id), sum(cost_usd), sum(output) "
        "FROM requests r JOIN sessions s USING (session_id) WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if not head or not head[1]:
        return f"tokscope: no API requests recorded for session {session_id} yet."
    title, n_req, n_agents, total, out = head
    total = total or 0
    note = unpriced_text(unpriced(conn, "WHERE r.session_id = ?", (session_id,)))
    lines = [
        f"tokscope · {title or session_id[:8]} · ${total:,.2f} API-eq · {n_req} requests · "
        f"{n_agents} subagent runs · {out or 0:,} output tokens"
    ]
    groups = (
        ("owner", "CASE WHEN agent_id IS NULL THEN 'main thread' ELSE agent_type END"),
        ("skill", "COALESCE(skill, '(no skill)')"),
        ("phase", "COALESCE(phase, 'unscoped')"),
    )
    from .core.skills import session_skill_versions

    versions = session_skill_versions(conn, session_id)
    for label, key in groups:
        rows = conn.execute(
            f"SELECT {key}, count(*), sum(cost_usd) FROM requests WHERE session_id = ? "
            f"GROUP BY 1 ORDER BY 3 DESC LIMIT 8",
            (session_id,),
        ).fetchall()
        lines.append(f"\nby {label}:")
        # a skill row names the version this session loaded (see `tokscope skills <name>`)
        name = lambda k: f"{k} {versions[k][:6]}" if label == "skill" and k in versions else str(k)  # noqa: E731
        lines += [f"  {name(k)[:38]:<38} {n:>5} req  ${c or 0:>8,.2f}  {(c or 0) / (total or 1):>4.0%}" for k, n, c in rows]
    return "\n".join(lines + [f"\n{note}"] * bool(note))


def session_json(conn, session_id):
    """Compact per-session numbers for the live pane."""
    tok = "(input + cache_read + cache_write_5m + cache_write_1h + output)"
    row = conn.execute(
        f"SELECT s.title, s.prompts, sum({tok}), sum(output), sum(cost_usd), "
        f"sum(CASE WHEN agent_id IS NULL THEN {tok} END), sum(CASE WHEN agent_id IS NOT NULL THEN {tok} END), "
        f"count(DISTINCT agent_id) FROM requests r JOIN sessions s USING (session_id) WHERE session_id = ?",
        (session_id,)).fetchone()
    if not row or row[2] is None:
        return {"id": session_id, "empty": True, "context": 0}
    title, prompts, tokens, out, usd, main, agents, runs = row
    # the context the last main-thread request was sent with (what the mod's 300K nudge reads); output is not part of it
    ctx = conn.execute(
        "SELECT COALESCE(input, 0) + COALESCE(cache_read, 0) + COALESCE(cache_write_5m, 0) + COALESCE(cache_write_1h, 0) "
        "FROM requests WHERE session_id = ? AND agent_id IS NULL ORDER BY ts DESC, rowid DESC LIMIT 1", (session_id,)).fetchone()
    from .core.skills import session_skill_versions

    versions = session_skill_versions(conn, session_id)

    def top(key):
        return conn.execute(f"SELECT {key}, sum({tok}) FROM requests WHERE session_id = ? GROUP BY 1 ORDER BY 2 DESC LIMIT 5",
                            (session_id,)).fetchall()
    last = conn.execute(
        f"SELECT r.prompt_idx, p.text, sum({tok}), sum(CASE WHEN agent_id IS NOT NULL THEN {tok} END) FROM requests r "
        f"LEFT JOIN prompts p ON p.session_id = r.session_id AND p.prompt_idx = r.prompt_idx "
        f"WHERE r.session_id = ? AND r.prompt_idx IS NOT NULL GROUP BY r.prompt_idx ORDER BY r.prompt_idx DESC LIMIT 1",
        (session_id,)).fetchone()
    return {
        "budget": _budget_view(conn),
        "id": session_id, "empty": False, "title": title or "", "prompts": prompts or 0, "tokens": tokens, "output": out or 0,
        "usd": usd, "main": main or 0, "agents": agents or 0, "runs": runs,
        "context": ctx[0] if ctx else 0,
        "owners": top("COALESCE(agent_type, 'main thread')"), "skills": [[f"{k} {versions[k][:6]}" if k in versions else k, t] for k, t in top("skill") if k],
        "last": {"i": last[0], "text": last[1] or "", "tokens": last[2] or 0, "agents": last[3] or 0} if last else None,
        "turns": session_turns(conn, session_id),
    }


def _budget_view(conn):
    """For the live pane: None without a budgets.json, else {"error"} or {"warn": [{text, pct, state}]} for budgets >= 80%."""
    from .core import budgets

    try:
        found = budgets.load()
    except budgets.BudgetError as e:
        return {"error": str(e)}
    if found is None:
        return None
    return {"warn": [{"text": i["text"], "pct": i["pct"], "state": i["state"]} for i in budgets.warnings(budgets.check(conn, found))]}


def session_turns(conn, session_id, limit=20):
    """Newest prompts first: tokens in/out, list price, model requests, and what each one called (see calls.py)."""
    calls = turn_calls(conn, session_id)
    turns = []
    for i, text, tin, out, usd, priced in conn.execute(
            "SELECT r.prompt_idx, p.text, sum(input + cache_read + cache_write_5m + cache_write_1h), sum(output), "
            "sum(cost_usd), count(cost_usd) = count(*) FROM requests r LEFT JOIN prompts p "
            "ON p.session_id = r.session_id AND p.prompt_idx = r.prompt_idx WHERE r.session_id = ? "
            "AND r.prompt_idx IS NOT NULL GROUP BY r.prompt_idx ORDER BY r.prompt_idx DESC LIMIT ?", (session_id, limit)):
        # a price is shown only when every request of the turn has a known model rate
        turns.append({"i": i, "text": text or ("(session start)" if i == 0 else ""), "in": tin or 0, "out": out or 0,
                      "usd": usd if priced else None, **calls.get((session_id, i), {"requests": 0, "agents": [], "runs": [],
                                                                                    "mcp": [], "tools": []})})
    return turns


def open_in_browser(url):
    """First browser found wins: $BROWSER, Chrome, Firefox, then the desktop handler, which may have none for local HTML."""
    import os
    import shutil
    import subprocess

    for cmd in (os.environ.get("BROWSER"), "google-chrome", "firefox", "xdg-open", "open"):
        path = cmd and shutil.which(cmd)
        if path:
            subprocess.Popen([path, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            print(f"opened in {Path(path).name}")
            return
    print(f"no browser found; open {url}")


def append_marks(lines, marks_dir):
    """Append hook marks (one JSON object per stdin line) to a daily JSONL file."""
    marks_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    kept = [json.dumps({"received_at": now.isoformat(), **json.loads(line)}) for line in lines if line.strip()]
    with open(marks_dir / f"marks-{now:%Y-%m-%d}.jsonl", "a") as f:
        f.writelines(line + "\n" for line in kept)
    return len(kept)


def _skill_versions(args):
    """(skill, [versions]) from --skill/--skill-versions, or (None, None); one without the other is an error."""
    if bool(args.skill) != bool(args.skill_versions):
        sys.exit("tokscope: --skill and --skill-versions go together, e.g. --skill xia2 --skill-versions 25e2fd,9ee5a7")
    return (args.skill, args.skill_versions.split(",")) if args.skill else (None, None)


def _filters(args):
    clauses, params = [], []
    for text, op, end in ((args.since, ">=", False), (args.until, "<", True)):
        if text:
            try:
                bound = tz.utc_bound(text, end)
            except ValueError:
                sys.exit(f"tokscope: bad date {text!r}, use YYYY-MM-DD")
            clauses.append(f"r.ts {op} ?")
            params.append(bound)
    if args.project:
        clauses.append("s.project LIKE ?")
        params.append(f"%{args.project}%")
    return ("WHERE " + " AND ".join(clauses) if clauses else ""), params


def main():
    p = argparse.ArgumentParser(prog="tokscope", description="Token usage per skill, subagent and phase.")
    p.add_argument("--version", action="version", version=f"tokscope {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("ingest", help="parse transcripts into SQLite (incremental)")
    pi.add_argument("--project", help="only project dirs containing this text")
    pi.add_argument("--projects-dir", metavar="PATH", help="read this transcripts folder instead of the default ones")
    pi.add_argument("--session", help="re-parse this one session id only")
    pi.add_argument("--otel", nargs="?", const="", metavar="DIR",
                    help="read only the OTel api_request events (data/otel, or DIR), not the transcripts")
    pss = sub.add_parser("session", help="print one session's breakdown (ingests it first)")
    pss.add_argument("session_id")
    pss.add_argument("--json", action="store_true", help="machine-readable, for the live pane")
    sub.add_parser("mark", help="append JSON marks from stdin to data/marks/")
    pc = sub.add_parser("change", help="record a config change, or list changes with their before/after impact")
    pc.add_argument("note", nargs="?", help='e.g. "reviewer: fable -> opus"; omit to list')
    pc.add_argument("--agent", help="subagent type the change affects")
    pc.add_argument("--skill", help="skill the change affects")
    pc.add_argument("--at", help="ISO time of the change (default now)")
    pc.add_argument("--days", type=int, default=14, help="before/after window")
    prp = sub.add_parser("replay", help="replay a real session's prompts headless and compare tokens per turn")
    prp.add_argument("action", choices=["plan", "run", "diff"])
    prp.add_argument("session_id")
    prp.add_argument("--runs", type=int, default=2)
    prp.add_argument("--budget", type=float, default=6.0, help="stop when replays pass this API-eq USD total")
    prp.add_argument("--model", help="main-loop model for the replay (default: your configured one)")
    pb = sub.add_parser("bench", help="before/after benchmark of a fixed task")
    for q in (prp, pb):
        q.add_argument("--skill", help="pin this project skill per run (see `tokscope skills` for its versions)")
        q.add_argument("--skill-versions", help="comma-separated kept versions (hash prefixes) of --skill, one variant each")
    pb.add_argument("action", choices=["prepare", "run", "diff", "regrade"])
    pb.add_argument("task", help="task name under bench/tasks/ or a path to its JSON")
    pb.add_argument("--runs", type=int, default=3)
    pb.add_argument("--variants", help="comma-separated subset of the task's variants")
    po_ = sub.add_parser("optimize", help="evaluate a skill: run one eval case in an isolated session and grade it by machine")
    po_sub = po_.add_subparsers(dest="optimize_cmd", required=True)
    pcase = po_sub.add_parser("case", help="run one case of <skill>/evals/evals.json (paid claude -p run); exit 0 all checks passed, 1 failed or INVALID, 2 load error")
    pcase.add_argument("skill")
    pcase.add_argument("case_id")
    pcase.add_argument("--version", help="kept version (hash prefix) of the skill to pin; default: the skill folder as it is")
    psuite = po_sub.add_parser("suite", help="check <skill>/evals/evals.json and print its dev/holdout split; --draft writes evals.draft.json from real calls, --approve copies a passing draft to evals.json; exit 0 ok, 1 problems, 2 load error")
    psuite.add_argument("skill")
    pmode = psuite.add_mutually_exclusive_group()
    pmode.add_argument("--draft", action="store_true", help="write evals/evals.draft.json (no paid run, no LLM)")
    pmode.add_argument("--approve", action="store_true", help="copy evals.draft.json to evals.json when its checks pass")
    psuite.add_argument("--force", action="store_true", help="with --approve: overwrite an existing evals.json")
    psuite.add_argument("--n", type=int, default=5, help="most cases in a draft (default 5)")
    pcase.add_argument("--max-budget-usd", type=float, default=None, help="cost cap of this run in USD (default 2.0)")
    prun = po_sub.add_parser("run", help="optimize a skill: lock a plan, then preflight, baseline, up to 3 edit rounds, confirm and a verdict (paid claude -p runs); exit 0 Apply, 1 Not enough evidence or Reject, 2 load, plan-lock or run-lock error")
    prun.add_argument("skill")
    prun.add_argument("--budget", type=float, required=True, help="most to spend in USD; the run stops before passing it")
    prun.add_argument("--runs", type=int, default=3, help="runs per case and arm (default 3)")
    prun.add_argument("--model", default="sonnet", help="model of every run and of the editor (default sonnet)")
    pres = po_sub.add_parser("resume", help="continue a stopped optimize run; refuses when plan.json or the frozen suite changed; same exit codes as run")
    pres.add_argument("run_id")
    preg = po_sub.add_parser("regrade", help="grade the stored results of an optimize run again and recompute its verdict (no claude call, no cost)")
    preg.add_argument("run_id")
    pap = po_sub.add_parser("approve", help="install the measured draft of an optimize run (the installed fingerprint becomes the measured one) and commit only the skill's files when it is in git; exit 0 done, 2 refused")
    pap.add_argument("run_id")
    pap.add_argument("--reason", help="why; required to approve a Not enough evidence verdict")
    prj = po_sub.add_parser("reject", help="record that you rejected an optimize run's draft (the skill is not touched)")
    prj.add_argument("run_id")
    prj.add_argument("--reason")
    prv = po_sub.add_parser("revert", help="put back the version an approve replaced (from its kept snapshot); exit 0 done, 2 refused")
    prv.add_argument("run_id")
    tz_help = "IANA zone for days (default: local, or TOKSCOPE_TZ), e.g. UTC"
    pv = sub.add_parser("serve", help="live dashboard on 127.0.0.1 that ingests new transcripts as they land")
    pv.add_argument("--port", type=int, default=8765)
    pv.add_argument("--interval", type=float, default=10.0, help="seconds between background ingests")
    pv.add_argument("--no-open", action="store_true", help="do not open the browser")
    pv.add_argument("--privacy", choices=LEVELS, default="full")
    pv.add_argument("--projects-dir", metavar="PATH", help="read this transcripts folder instead of the default ones "
                    "(a small sample keeps a test server from ingesting every transcript)")
    psv = sub.add_parser("service", help="keep the dashboard server running from login (launchd on macOS, systemd on Linux); opt-in")
    psv.add_argument("action", choices=["install", "uninstall", "status"])
    psv.add_argument("--port", type=int, default=8770)
    psv.add_argument("--python", help="macOS: the Python the agent runs (default: this one)")
    psv.add_argument("--root", help="macOS: folder that holds the tokscope package (default: this checkout)")
    psv.add_argument("--home", help="macOS: the data folder the agent reads (TOKSCOPE_HOME); also isolates the user site")
    psv.add_argument("--exe", help="Linux: the tokscope launcher in ExecStart (default: bin/tokscope of this checkout)")
    psv.add_argument("--quote-exe", action="store_true", help="Linux: wrap --exe in double quotes")
    psv.add_argument("--unit-file", help="Linux: write the unit here instead of the user folder (only writes, no enable)")
    psv.add_argument("--no-enable", action="store_true", help="Linux: only write the unit")
    pot = sub.add_parser("otel-receiver", help="optional OTLP/HTTP-JSON receiver: saves Claude Code's OTel export to data/otel (no view reads it yet)")
    pot.add_argument("--host", default=os.environ.get("TOKSCOPE_HOST", "127.0.0.1"), help="default 127.0.0.1 (TOKSCOPE_HOST)")
    pot.add_argument("--port", type=int, default=None, help="default 4318 (TOKSCOPE_PORT)")
    pot.add_argument("--allow-remote", action="store_true", help="allow a non-loopback --host (the receiver has no authentication)")
    pot.add_argument("--max-body", type=int, default=8 * 1024 * 1024, metavar="BYTES", help="refuse bodies over this size, also after gzip (default 8 MiB)")
    pch = sub.add_parser("check", help="compare today's spend with budgets.json; exit 0 ok, 10 near, 11 over, 30 no data")
    pch.add_argument("--once", action="store_true", required=True, help="print the state once and exit")
    pch.add_argument("--json", action="store_true")
    sub.add_parser("statusline", help="a one-line budget warning for Claude Code's statusLine")
    pk = sub.add_parser("skills", help="each skill's versions (content hash), loads and median tokens per load")
    pk.add_argument("skill", nargs="?", help="only this skill; `import [skill]` keeps older versions transcripts still show")
    pk.add_argument("name", nargs="?", help=argparse.SUPPRESS)
    pk.add_argument("--format", choices=("table", "json", "csv"), default="table", help="json or csv print only the rows")
    ps = sub.add_parser("summary", help="print a cost table")
    ps.add_argument("--by", choices=SUMMARY_SQL, default="phase")
    ps.add_argument("--errors", action="store_true", help="count failed and repeated tool calls, interrupts, API errors "
                    "and retries instead of cost (--by skill, agent or phase)")
    ps.add_argument("--format", choices=("table", "json", "csv"), default="table", help="json or csv print only the rows")
    ppt = sub.add_parser("patterns", help="which kinds of prompts cost the most, what they ran and how they ended (read-only)")
    ppt.add_argument("--since", metavar="YYYY-MM-DD", help="first day to read (default: the last 14 days)")
    ppt.add_argument("--format", choices=("table", "json"), default="table", help="json prints only the groups")
    ppt.add_argument("--privacy", choices=LEVELS, default="full",
                     help="redacted or numbers: workflow groups only, no prompt text (default full)")
    pr = sub.add_parser("report", help="write the HTML report")
    po = sub.add_parser("open", help="ingest new transcripts, rebuild the HTML report and open it in the browser")
    for q in (pr, po):
        q.add_argument("--out", type=Path, help="default: reports/report.html, or reports/report-<level>.html")
        q.add_argument("--privacy", choices=LEVELS, default="full",
                       help="redacted: no prompts, titles, descriptions, answers or paths; numbers: also alias every name")
    pv.add_argument("--timezone", help=tz_help)
    for q in (ps, pr, po):
        q.add_argument("--timezone", help=tz_help)
        q.add_argument("--since", help="first day, e.g. 2026-10-01, in the time zone")
        q.add_argument("--until", help="last day, in the time zone")
        q.add_argument("--project", help="project dir name contains this text")
    ps.add_argument("--limit", type=int, default=25)
    args = p.parse_args()
    try:
        tz.set_zone(getattr(args, "timezone", None))
    except ValueError as e:
        sys.exit(f"tokscope: {e}")

    if args.cmd == "service":  # before the data folder is made: the .deb's postinst runs this as root
        from .features import service

        try:
            if args.action == "install":
                print(service.install(args.python, args.root, args.exe, args.port, unit_file=args.unit_file,
                                      enable=not (args.no_enable or args.unit_file), quote=args.quote_exe, data_home=args.home))
            elif args.action == "uninstall":
                print(service.uninstall())
            else:
                _, running, text = service.status()
                print(text)
                sys.exit(0 if running else 1)
        except (RuntimeError, OSError) as e:
            sys.exit(f"tokscope: {e}")
        return
    if args.cmd == "otel-receiver":
        from .integrations import otel_receiver

        try:
            port = args.port if args.port is not None else int(os.environ.get("TOKSCOPE_PORT") or "4318")
            otel_receiver.serve(args.host, port, otel_receiver.default_dir(), args.max_body, args.allow_remote)
        except (ValueError, OSError, OverflowError) as e:
            sys.exit(f"tokscope: {e}")
        return
    DB.parent.mkdir(parents=True, exist_ok=True)
    if args.cmd == "ingest" and args.session:
        if not ingest_session(DB, PHASES, args.session, args.projects_dir):
            sys.exit(f"tokscope: no transcript for session {args.session}")
        _budget_line(args.session)
    elif args.cmd == "ingest" and args.otel is not None:
        ingest_otel(DB, Path(args.otel).expanduser() if args.otel else None)
    elif args.cmd == "ingest":
        start = time.time()
        ingest(DB, PHASES, args.projects_dir, args.project)
        print(f"took {time.time() - start:.1f}s -> {DB}")
    elif args.cmd == "check":
        sys.exit(check(args))
    elif args.cmd == "statusline":
        print(statusline(args))
    elif args.cmd == "session":
        ingest_session(DB, PHASES, args.session_id)
        with closing(connect(DB)) as conn:  # creates the tables on a fresh install
            print(json.dumps(session_json(conn, args.session_id)) if args.json else session_text(conn, args.session_id))
    elif args.cmd == "mark":
        lines = sys.stdin.readlines()
        append_marks(lines, paths.marks())
        record_skill_versions(lines)
    elif args.cmd == "serve":
        from .web.dashboard import serve

        if args.projects_dir is not None and not (args.projects_dir and Path(args.projects_dir).expanduser().is_dir()):  # a typo would give an empty dashboard
            sys.exit(f"tokscope: --projects-dir {args.projects_dir!r} is not a folder")
        try:
            serve(DB, PHASES, args.port, args.interval, not args.no_open, args.privacy, projects_dir=args.projects_dir)
        except OSError as e:  # the port is taken: say so instead of a traceback
            sys.exit(f"tokscope: cannot listen on 127.0.0.1:{args.port} ({e.strerror}); try --port {args.port + 1}")
    elif args.cmd == "skills":
        if args.skill == "import":
            from .core.skills import import_from_transcripts

            with closing(connect(DB)) as conn:
                done = import_from_transcripts(conn, None, args.name)
            for sk, version, first, n in done:
                print(f"kept {sk} {version}: SKILL.md from {n} load(s), first {first[:16].replace('T', ' ')}")
            print(f"{len(done)} older version(s) kept" if done else "no older version found in the transcripts")
        else:
            print(skills_text(args.skill, args.format))
    elif args.cmd == "change":
        from .features.changes import add_change, impact_text, list_changes

        with closing(connect(DB)) as conn:  # creates the tables on a fresh install
            if args.note:
                try:
                    cid = add_change(conn, args.note, args.agent, args.skill, args.at)
                except ValueError as e:
                    sys.exit(f"tokscope: {e}")
                print(f"recorded change #{cid}")
            for change in list_changes(conn):
                print(impact_text(conn, change, args.days))
    elif args.cmd == "replay":
        from .experiments import replay

        if args.action == "plan":
            path = replay.find_transcript(args.session_id)
            groups, cwd, first_ts = replay.extract_prompts(path)
            print(f"{len(groups)} turns from {path}\ncwd {cwd}, started {first_ts}")
            for i, g in enumerate(groups, 1):
                merged = f" (prompts {','.join(map(str, g['orig']))} merged: sent before any answer)" if len(g["orig"]) > 1 else ""
                print(f"  {i}.{merged} {g['text'][:200]!r}")
        elif args.action == "run":
            try:
                spent = replay.run(ROOT, DB, PHASES, args.session_id, args.runs, args.budget, args.model,
                                   *_skill_versions(args))
            except ValueError as e:
                sys.exit(f"tokscope: {e}")
            print(f"spent ${spent:.2f} API-eq")
            print(replay.diff(DB, args.session_id))
        else:
            print(replay.diff(DB, args.session_id))
    elif args.cmd == "optimize" and args.optimize_cmd == "suite":
        from .experiments.skillopt import suite

        try:
            if args.draft:
                res = suite.draft(args.skill, args.n)
                print(f"{res['note']}\ndraft {res['path']}\nadd machine checks, then: tokscope optimize suite {args.skill} --approve")
            elif args.approve:
                print(f"approved: {suite.approve(args.skill, force=args.force)}")
            else:
                loaded = suite.load(args.skill)
                for problem in loaded.problems:
                    print(problem)
                if loaded.problems:
                    sys.exit(1)
                dev, hold = suite.split(loaded)
                print(f"{len(dev)} dev, {len(hold)} holdout\nholdout: {', '.join(hold)}")
        except suite.Refused as e:
            print(f"tokscope: {e}", file=sys.stderr)
            sys.exit(1)
        except ValueError as e:
            print(f"tokscope: {e}", file=sys.stderr)
            sys.exit(2)
    elif args.cmd == "optimize" and args.optimize_cmd in ("run", "resume", "regrade"):
        from .experiments.skillopt import loop

        try:
            if args.optimize_cmd == "run":
                run = loop.start(args.skill, args.budget, args.runs, args.model)
            elif args.optimize_cmd == "resume":
                run = loop.resume(args.run_id)
            else:
                run = loop.regrade(args.run_id)
        except ValueError as e:  # a load, plan-lock or run-lock error, before any paid run
            print(f"tokscope: {e}", file=sys.stderr)
            sys.exit(2)
        print("\n".join(loop.report(run)[1:] if args.optimize_cmd == "run" else loop.report(run)))
        sys.exit(loop.exit_code(run))
    elif args.cmd == "optimize" and args.optimize_cmd in ("approve", "reject", "revert"):
        from .experiments.skillopt import apply

        try:
            if args.optimize_cmd == "approve":
                d = apply.approve(args.run_id, args.reason)
            elif args.optimize_cmd == "reject":
                d = apply.reject(args.run_id, args.reason)
            else:
                d = apply.revert(args.run_id)
        except ValueError as e:  # a refusal: the skill is at its old fingerprint
            print(f"tokscope: {e}", file=sys.stderr)
            sys.exit(2)
        if d["decision"] == "reject":
            print(f"rejected {d['run_id']} ({d['skill']} unchanged)")
        else:
            verb = "approved" if d["decision"] == "approve" else "reverted"
            print(f"{verb} {d['skill']}: {d['old_fingerprint']} → {d['new_fingerprint']}, commit {(d['commit_sha'] or 'none')[:10]}")
    elif args.cmd == "optimize":
        from .experiments.skillopt import sandbox

        try:
            run = sandbox.run_case(args.skill, args.case_id, args.version, budget=args.max_budget_usd)
        except ValueError as e:  # a load error, before any paid run
            print(f"tokscope: {e}", file=sys.stderr)
            sys.exit(2)
        g = json.loads((run / "grading.json").read_text())
        print(f"run {run}")
        if g["status"] == "INVALID":
            print(f"INVALID: {g['reason']}")
            sys.exit(1)
        print(f"passed {g['passed']}/{g['total']}" + (f" · safety failed {g['safety_failed']}" if g["safety_failed"] else ""))
        sys.exit(0 if g["passed"] == g["total"] else 1)
    elif args.cmd == "bench":
        from .experiments import bench

        task_path = Path(args.task) if args.task.endswith(".json") else paths.tasks() / f"{args.task}.json"
        task = bench.load_task(task_path)
        if args.action == "prepare":
            print("snapshot %s @ %s" % bench.prepare(ROOT, task))
        elif args.action == "run":
            variants = args.variants.split(",") if args.variants else None
            try:
                bench.run(ROOT, DB, PHASES, task, args.runs, variants, *_skill_versions(args))
            except ValueError as e:  # a version or skill that cannot be pinned: nothing has run
                sys.exit(f"tokscope: {e}")
            print(bench.diff(DB, task["name"]))
        elif args.action == "regrade":
            print("regraded %d runs, %d verdicts changed" % bench.regrade(DB, task, args.skill))
            print(bench.diff(DB, task["name"]))
        else:
            print(bench.diff(DB, task["name"]))
    elif args.cmd == "summary":
        summary(args)
    elif args.cmd == "patterns":
        patterns_cmd(args)
    elif args.cmd in ("report", "open"):
        from .web.report import write_report

        if args.cmd == "open":
            ingest(DB, PHASES, None, log=lambda *_: None)  # only changed transcripts; well under a second
        where, params = _filters(args)
        args.out = args.out or (REPORT if args.privacy == "full" else REPORT.with_name(f"report-{args.privacy}.html"))
        write_report(DB, args.out, where, params, level=args.privacy)
        print(f"wrote {args.out}")
        if args.cmd == "open":
            open_in_browser(args.out.resolve().as_uri())


if __name__ == "__main__":
    main()
