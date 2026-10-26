"""Claude Code's OpenTelemetry api_request events (saved by the receiver in data/otel/logs-*.jsonl) as the otel_requests table.

Attribute names follow https://code.claude.com/docs/en/monitoring-usage: model, input_tokens (cache excluded),
output_tokens, cache_read_tokens, cache_creation_tokens, cost_usd, duration_ms, speed, prompt.id, session.id, event.timestamp.
The files are read incrementally: a byte offset per file, so a re-run adds nothing; a shrunk or replaced file is read again."""

import bisect
import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone

from .. import paths
from . import pricing

HEAD_BYTES = 4096  # the start of a file that must be unchanged for it to count as appended to
BENCH_LIKE = "%tokscope%-bench-%"  # features.changes.BENCH_PROJECT (core cannot import it; tests/test_otel.py checks they agree)
MATCH_SECONDS = 120  # an event and its transcript request must be this close in time
INT64 = 2**63 - 1
BAD_LINE = (ValueError, TypeError, AttributeError, OverflowError, RecursionError,
            sqlite3.InterfaceError, sqlite3.ProgrammingError)  # input-caused; OperationalError (locked, disk full) propagates
ONLY_TIP = "No transcript, so no prompts, skills or subagents. The cost is Claude Code's own cost_usd"
ONLY_NOTE = " Includes telemetry-only sessions (no transcript): their figure is Claude Code's own cost_usd."
VALUE_KEYS = ("stringValue", "intValue", "doubleValue", "boolValue")


def _attrs(items):
    out = {}
    for a in items or ():
        v = a.get("value") or {}
        for k in VALUE_KEYS:
            if k in v:
                out[a.get("key")] = v[k]
                break
    return out


def _num(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None  # nan and inf are no number


def _int(v):
    n = _num(v)
    return max(-INT64, min(INT64, int(n))) if n is not None else 0  # SQLite INTEGER is 64 bit


def _ts(attrs, rec):
    if attrs.get("event.timestamp"):
        return str(attrs["event.timestamp"])
    nano = _num(rec.get("timeUnixNano"))
    if not nano:
        return None
    try:
        return datetime.fromtimestamp(nano / 1e9, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    except (OSError, OverflowError, ValueError):  # a time_t out of range raises OSError or OverflowError, a year out of range ValueError
        return None


def events(body):
    """The api_request events of one OTLP/HTTP JSON logs export, as tuples in the otel_requests column order after pos/idx."""
    for rl in (body or {}).get("resourceLogs") or ():
        res = _attrs((rl.get("resource") or {}).get("attributes"))
        for sl in rl.get("scopeLogs") or ():
            for rec in sl.get("logRecords") or ():
                a = _attrs(rec.get("attributes"))
                name = a.get("event.name") or (rec.get("body") or {}).get("stringValue") or ""
                if name.removeprefix("claude_code.") != "api_request":
                    continue
                yield (a.get("session.id") or res.get("session.id"), a.get("prompt.id"), _ts(a, rec), a.get("model"),
                       _int(a.get("input_tokens")), _int(a.get("output_tokens")), _int(a.get("cache_read_tokens")),
                       _int(a.get("cache_creation_tokens")), _num(a.get("cost_usd")), _num(a.get("duration_ms")), a.get("speed"))


def _head(path, n):
    with open(path, "rb") as f:
        return hashlib.sha1(f.read(min(n, HEAD_BYTES))).hexdigest()


def _stale(conn, path):
    """Whether a file shrank or was replaced since it was read."""
    row = conn.execute("SELECT off, head FROM otel_files WHERE src = ?", (path.name,)).fetchone()
    return bool(row and row[0] and (path.stat().st_size < row[0] or _head(path, row[0]) != row[1]))


def _read(conn, path):
    """New events of one logs file; returns how many were added."""
    src = path.name
    row = conn.execute("SELECT off FROM otel_files WHERE src = ?", (src,)).fetchone()
    off = row[0] if row else 0
    added, pos = 0, off
    with open(path, "rb") as f:  # line by line from the stored offset: memory does not grow with the unread tail
        f.seek(off)
        for line in iter(f.readline, b""):
            if not line.endswith(b"\n"):  # a line still being written waits for the next run
                break
            added += _line(conn, src, pos, line)
            pos += len(line)
    conn.execute("INSERT OR REPLACE INTO otel_files VALUES (?, ?, ?)", (src, pos, _head(path, pos) if pos else None))
    return added


def dedupe_key(ev):
    """A stable key of one event (session, prompt id, ts, model, counts, cost, duration, speed): a re-sent export repeats it."""
    return hashlib.sha1(json.dumps(ev, separators=(",", ":")).encode()).hexdigest()


def _line(conn, src, pos, line):
    """Add the events of one file line; a malformed or hostile line is skipped (the caller still moves past it)."""
    conn.execute("SAVEPOINT otel_line")
    try:
        rec = json.loads(line)
        body = rec.get("body") if isinstance(rec, dict) and rec.get("signal") == "logs" else None
        evs = list(events(body)) if isinstance(body, dict) else ()
        n = 0
        for j, ev in enumerate(evs):  # OR IGNORE: the same event again (a retried export) hits the unique dedupe index
            n += conn.execute("INSERT OR IGNORE INTO otel_requests (src, pos, idx, session_id, prompt_id, ts, model, input, "
                              "output, cache_read, cache_write, cost_usd, duration_ms, speed, dedupe) "
                              "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (src, pos, j, *ev, dedupe_key(ev))).rowcount
        conn.execute("RELEASE otel_line")
        return n
    except BAD_LINE:
        conn.execute("ROLLBACK TO otel_line")
        conn.execute("RELEASE otel_line")
        return 0


def migrate(conn):
    """Give an older otel_requests its dedupe key: fill it, drop the duplicates already stored (the first copy stays), then
    enforce uniqueness. Safe to run on every connect."""
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'idx_otel_dedupe'").fetchone():
        return  # migrated: connect() takes no write lock
    if not any(c[1] == "dedupe" for c in conn.execute("PRAGMA table_info(otel_requests)")):
        conn.execute("ALTER TABLE otel_requests ADD COLUMN dedupe TEXT")
    old = conn.execute("SELECT rowid, session_id, prompt_id, ts, model, input, output, cache_read, cache_write, cost_usd, "
                       "duration_ms, speed FROM otel_requests WHERE dedupe IS NULL").fetchall()
    conn.executemany("UPDATE otel_requests SET dedupe = ? WHERE rowid = ?", [(dedupe_key(r[1:]), r[0]) for r in old])
    conn.execute("DELETE FROM otel_requests WHERE rowid NOT IN (SELECT min(rowid) FROM otel_requests GROUP BY dedupe)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_otel_dedupe ON otel_requests (dedupe)")
    conn.commit()


def ingest(conn, directory=None):
    """Read every new api_request event under the OTel folder, then match them to requests. A missing folder is a no-op."""
    directory = directory or paths.otel_dir()
    if not directory.is_dir():
        return 0
    files = sorted(directory.glob("logs-*.jsonl"))
    stale = [p.name for p in files if _stale(conn, p)]
    if stale:  # their old events go. An event another file also held was deduped away there, so every file is read
        # again: it stays if a file still has it, and is gone only when the stale file was its sole copy
        conn.executemany("DELETE FROM otel_requests WHERE src = ?", [(s,) for s in stale])
        conn.execute("DELETE FROM otel_files")
    added = sum(_read(conn, path) for path in files)
    match(conn)
    conn.commit()
    return added


def _secs(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def match(conn):
    """Pair each unmatched event with the request of its session that has the same tokens and the closest time.

    Requests are bucketed by their tokens and sorted by time, so each event is a binary search: n log n per session."""
    todo = conn.execute("SELECT rowid, session_id, ts, input, output, cache_read, cache_write FROM otel_requests "
                        "WHERE request_key IS NULL AND session_id IS NOT NULL ORDER BY ts").fetchall()
    by_session = {}
    for r in todo:
        by_session.setdefault(r[1], []).append(r)
    for sid, evs in by_session.items():
        taken = {k for (k,) in conn.execute("SELECT request_key FROM otel_requests WHERE session_id = ? AND request_key IS NOT NULL", (sid,))}
        buckets = {}
        for k, ts, *tokens in conn.execute(
                "SELECT request_key, ts, input, output, cache_read, cache_write_5m + cache_write_1h FROM requests WHERE session_id = ?", (sid,)):
            rt = _secs(ts)
            if k not in taken and rt is not None:
                buckets.setdefault(tuple(tokens), []).append((rt, k))
        for b in buckets.values():
            b.sort()
        for rowid, _, ts, *tokens in evs:
            t, b = _secs(ts), buckets.get(tuple(tokens))
            if t is None or not b:
                continue
            i = bisect.bisect_left(b, (t,))
            best = min((c for c in (i - 1, i) if 0 <= c < len(b)), key=lambda c: (abs(b[c][0] - t), b[c][1]))
            if abs(b[best][0] - t) <= MATCH_SECONDS:
                conn.execute("UPDATE otel_requests SET request_key = ? WHERE rowid = ?", (b[best][1], rowid))
                del b[best]


def cost_check(conn, cond="", params=(), since=None, scoped=False):
    """tokscope API-eq against Claude Code's cost_usd.

    cond/params: a WHERE clause over requests r and sessions s (the range's filters) for the matched pairs. since: ISO start
    of the range for the events. scoped: a project, model or skill filter is on, so events that belong to no request are left
    out. Returns None when no event was ever ingested."""
    if not conn.execute("SELECT 1 FROM otel_requests LIMIT 1").fetchone():
        return None
    pairs = conn.execute(
        "SELECT r.model, count(*), sum(o.cost_usd), sum(r.cost_usd), count(r.cost_usd) FROM otel_requests o "
        "JOIN requests r ON r.session_id = o.session_id AND r.request_key = o.request_key "
        f"JOIN sessions s ON s.session_id = r.session_id {cond} GROUP BY r.model", tuple(params)).fetchall()
    models = []
    for model, n, cc, tk, priced in pairs:
        cc, tk = cc or 0.0, tk or 0.0  # a request with no rate costs 0 here, so its drift is 100%
        models.append({"model": model, "n": n, "cc": cc, "tk": tk, "unpriced": priced < n,
                       "drift": abs(tk - cc) / cc if cc else None})
    models.sort(key=lambda m: abs(m["tk"] - m["cc"]), reverse=True)
    out = {"models": models, "n": sum(m["n"] for m in models), "cc": sum(m["cc"] for m in models),
           "tk": sum(m["tk"] for m in models), "unmatched": None, "only": None}
    if scoped:
        return out
    # bench sessions are left out, as in the matched pairs
    since_sql, sp = ("AND o.ts >= ?", (BENCH_LIKE, since)) if since else ("", (BENCH_LIKE,))
    since_sql = "AND (o.session_id IS NULL OR o.session_id NOT IN (SELECT session_id FROM sessions WHERE project LIKE ?)) " + since_sql
    out["unmatched"] = conn.execute(
        "SELECT count(*), sum(cost_usd) FROM otel_requests o WHERE request_key IS NULL "
        f"AND (session_id IS NULL OR EXISTS (SELECT 1 FROM requests r WHERE r.session_id = o.session_id)) {since_sql}", sp).fetchone()
    out["only"] = conn.execute(
        "SELECT count(DISTINCT session_id), count(*), total(input + output + cache_read + cache_write), sum(cost_usd) "
        "FROM otel_requests o WHERE session_id IS NOT NULL "
        f"AND NOT EXISTS (SELECT 1 FROM requests r WHERE r.session_id = o.session_id) {since_sql}", sp).fetchone()
    return out


def only_sessions(conn, since=None, until=None):
    """Telemetry-only sessions: a session id in otel_requests that has no transcript request (bench sessions left out).

    One dict per session, newest first: id, first/last event ts, requests, input, output, cache_read, cache_write, usd (the
    events' own cost_usd; an event without one is priced from its tokens with pricing.py, and counts $0 when its model has no
    rate), unpriced (events left at $0), models. since/until bound the events in the range, as a transcript session
    counts only the requests in it."""
    ts_sql, tp = "", [BENCH_LIKE]
    for op, bound in ((">=", since), ("<", until)):
        if bound:
            ts_sql += f" AND o.ts {op} ?"
            tp.append(bound)
    rows = conn.execute(
        "SELECT o.session_id, o.ts, o.model, o.input, o.output, o.cache_read, o.cache_write, o.cost_usd, o.speed FROM otel_requests o "
        "WHERE o.session_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM requests r WHERE r.session_id = o.session_id) "
        f"AND o.session_id NOT IN (SELECT session_id FROM sessions WHERE project LIKE ?){ts_sql} ORDER BY o.ts", tp).fetchall()
    ov = pricing.overrides() if any(r[7] is None for r in rows) else {}
    out = {}
    for sid, ts, model, inp, outp, cr, cw, usd, speed in rows:
        s = out.setdefault(sid, {"id": sid, "first": ts, "last": ts, "requests": 0, "input": 0, "output": 0, "cache_read": 0,
                                 "cache_write": 0, "usd": 0.0, "unpriced": 0, "models": set()})
        if usd is None:  # Claude Code sent no cost: list price from the tokens, if the model has a rate
            usd = pricing.cost_usd(model or "", inp, outp, cr, cw, 0, speed, None, 0, ov)
            s["unpriced"] += usd is None
        s["requests"] += 1
        s["usd"] += usd or 0.0
        for k, v in (("input", inp), ("output", outp), ("cache_read", cr), ("cache_write", cw)):
            s[k] += v or 0
        s["first"] = min(filter(None, (s["first"], ts)), default=None)
        s["last"] = max(filter(None, (s["last"], ts)), default=None)
        if model:
            s["models"].add(model)
    return sorted(out.values(), key=lambda s: s["last"] or "", reverse=True)


def only_totals(conn, since=None, until=None):
    """Sum of only_sessions: sessions, requests, tokens (input + cache + output, as TOKENS), output, cache_read, usd."""
    found = only_sessions(conn, since, until)
    return {"sessions": len(found), "requests": sum(s["requests"] for s in found),
            "tokens": sum(s["input"] + s["output"] + s["cache_read"] + s["cache_write"] for s in found),
            "output": sum(s["output"] for s in found), "cache_read": sum(s["cache_read"] for s in found),
            "usd": sum(s["usd"] for s in found), "unpriced": sum(s["unpriced"] for s in found)}
