import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, paths
from .core.calls import turn_calls
from .core.ingest import CARRIED, connect, ingest, ingest_session
from .core import tz
from .core.pricing import API_EQ_NOTE, unpriced, unpriced_text
from .core.privacy import LEVELS

ROOT = paths.home()
DB = paths.db()
PHASES = paths.phases()
REPORT = paths.report()

SUMMARY_SQL = {
    "phase": "COALESCE(phase, 'unscoped')",
    "skill": "COALESCE(skill, '(none)')",
    "agent": "COALESCE(agent_type, 'main')",
    "model": "model",
}


def summary(args):
    key = SUMMARY_SQL[args.by]
    where, params = _filters(args)
    conn = connect(DB)  # creates the tables on a fresh install
    rows = conn.execute(
        f"""SELECT {key} AS k, count(*), sum(input + cache_read + cache_write_5m + cache_write_1h), sum(output),
                   sum(cost_usd), sum(CASE WHEN {CARRIED} THEN cost_usd ELSE 0 END)
            FROM requests r JOIN sessions s USING (session_id) {where}
            GROUP BY k ORDER BY sum(cost_usd) DESC LIMIT ?""",
        (*params, args.limit),
    ).fetchall()
    total = sum(r[4] or 0 for r in rows) or 1
    # a phase's carried part comes from later prompts with no skill (see ingest.CARRIED)
    carried = args.by == "phase"
    print(f"{args.by:<40} {'requests':>9} {'prompt tok':>13} {'output tok':>11} {'API-eq $':>10} {'share':>6}"
          + (f" {'carried':>8}" if carried else ""))
    for k, n, prompt, out, cost, cr in rows:
        print(f"{str(k)[:40]:<40} {n:>9,} {prompt or 0:>13,} {out or 0:>11,} {cost or 0:>10.2f} {(cost or 0) / total:>6.1%}"
              + (f" {(cr or 0) / (cost or 1):>8.0%}" if carried else ""))
    print(API_EQ_NOTE)
    if note := unpriced_text(unpriced(conn, where, params)):
        print(note)


def record_skill_versions(lines):
    """A Skill mark from the mod: hash the folder that call loaded, so the load has its exact version."""
    from .core.skills import record_load

    marks = [json.loads(line) for line in lines if line.strip()]
    marks = [m for m in marks if m.get("tool") == "Skill" and m.get("skill") and not m.get("is_error")]
    if not marks:
        return
    conn = connect(DB)
    now = datetime.now(timezone.utc).isoformat()
    for m in marks:
        record_load(conn, m.get("session_id"), m.get("tool_use_id"), m["skill"], m.get("cwd"), now)
    conn.commit()


def skills_text(skill=None):
    from .core.skills import versions

    rows = versions(connect(DB), skill)
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
        return {"id": session_id, "empty": True}
    title, prompts, tokens, out, usd, main, agents, runs = row
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
        "id": session_id, "empty": False, "title": title or "", "prompts": prompts or 0, "tokens": tokens, "output": out or 0,
        "usd": usd, "main": main or 0, "agents": agents or 0, "runs": runs,
        "owners": top("COALESCE(agent_type, 'main thread')"), "skills": [[f"{k} {versions[k][:6]}" if k in versions else k, t] for k, t in top("skill") if k],
        "last": {"i": last[0], "text": last[1] or "", "tokens": last[2] or 0, "agents": last[3] or 0} if last else None,
        "turns": session_turns(conn, session_id),
    }


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
    tz_help = "IANA zone for days (default: local, or TOKSCOPE_TZ), e.g. UTC"
    pv = sub.add_parser("serve", help="live dashboard on 127.0.0.1 that ingests new transcripts as they land")
    pv.add_argument("--port", type=int, default=8765)
    pv.add_argument("--interval", type=float, default=10.0, help="seconds between background ingests")
    pv.add_argument("--no-open", action="store_true", help="do not open the browser")
    pv.add_argument("--privacy", choices=LEVELS, default="full")
    pk = sub.add_parser("skills", help="each skill's versions (content hash), loads and median tokens per load")
    pk.add_argument("skill", nargs="?", help="only this skill; `import [skill]` keeps older versions transcripts still show")
    pk.add_argument("name", nargs="?", help=argparse.SUPPRESS)
    ps = sub.add_parser("summary", help="print a cost table")
    ps.add_argument("--by", choices=SUMMARY_SQL, default="phase")
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

    DB.parent.mkdir(parents=True, exist_ok=True)
    if args.cmd == "ingest" and args.session:
        if not ingest_session(DB, PHASES, args.session, args.projects_dir):
            sys.exit(f"tokscope: no transcript for session {args.session}")
    elif args.cmd == "ingest":
        start = time.time()
        ingest(DB, PHASES, args.projects_dir, args.project)
        print(f"took {time.time() - start:.1f}s -> {DB}")
    elif args.cmd == "session":
        ingest_session(DB, PHASES, args.session_id)
        conn = connect(DB)  # creates the tables on a fresh install
        print(json.dumps(session_json(conn, args.session_id)) if args.json else session_text(conn, args.session_id))
    elif args.cmd == "mark":
        lines = sys.stdin.readlines()
        append_marks(lines, paths.marks())
        record_skill_versions(lines)
    elif args.cmd == "serve":
        from .web.dashboard import serve

        try:
            serve(DB, PHASES, args.port, args.interval, not args.no_open, args.privacy)
        except OSError as e:  # the port is taken: say so instead of a traceback
            sys.exit(f"tokscope: cannot listen on 127.0.0.1:{args.port} ({e.strerror}); try --port {args.port + 1}")
    elif args.cmd == "skills":
        if args.skill == "import":
            from .core.skills import import_from_transcripts

            done = import_from_transcripts(connect(DB), None, args.name)
            for sk, version, first, n in done:
                print(f"kept {sk} {version}: SKILL.md from {n} load(s), first {first[:16].replace('T', ' ')}")
            print(f"{len(done)} older version(s) kept" if done else "no older version found in the transcripts")
        else:
            print(skills_text(args.skill))
    elif args.cmd == "change":
        from .features.changes import add_change, impact_text, list_changes

        conn = connect(DB)  # creates the tables on a fresh install
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
