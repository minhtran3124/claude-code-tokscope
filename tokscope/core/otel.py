"""Claude Code's OpenTelemetry api_request events (saved by the receiver in data/otel/logs-*.jsonl) as the otel_requests table.

Attribute names follow https://code.claude.com/docs/en/monitoring-usage: model, input_tokens (cache excluded),
output_tokens, cache_read_tokens, cache_creation_tokens, cost_usd, duration_ms, speed, prompt.id, session.id, event.timestamp.
The files are read incrementally: a byte offset per file, so a re-run adds nothing; a shrunk or replaced file is read again."""

import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone

from .. import paths

HEAD_BYTES = 4096  # the start of a file that must be unchanged for it to count as appended to
BENCH_LIKE = "%tokscope%-bench-%"  # features.changes.BENCH_PROJECT (core cannot import it; tests/test_otel.py checks they agree)
MATCH_SECONDS = 120  # an event and its transcript request must be this close in time
INT64 = 2**63 - 1
BAD_LINE = (ValueError, TypeError, AttributeError, OverflowError, RecursionError,
            sqlite3.InterfaceError, sqlite3.ProgrammingError)  # input-caused; OperationalError (locked, disk full) propagates
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


def _read(conn, path):
    """New events of one logs file; returns how many were added."""
    src = path.name
    row = conn.execute("SELECT off, head FROM otel_files WHERE src = ?", (src,)).fetchone()
    off, head = row or (0, None)
    if off and (path.stat().st_size < off or _head(path, off) != head):  # shrunk or replaced: its old events go
        conn.execute("DELETE FROM otel_requests WHERE src = ?", (src,))
        off = 0
    with open(path, "rb") as f:
        f.seek(off)
        data = f.read()
    data = data[:data.rfind(b"\n") + 1]  # a line still being written waits for the next run
    added, pos = 0, off
    for line in data.splitlines(True):
        conn.execute("SAVEPOINT otel_line")
        try:  # a malformed or hostile line is skipped, and pos still moves past it
            rec = json.loads(line)
            body = rec.get("body") if isinstance(rec, dict) and rec.get("signal") == "logs" else None
            evs = list(events(body)) if isinstance(body, dict) else ()
            n = 0
            for j, ev in enumerate(evs):
                n += conn.execute("INSERT OR IGNORE INTO otel_requests (src, pos, idx, session_id, prompt_id, ts, model, input, "
                                      "output, cache_read, cache_write, cost_usd, duration_ms, speed) "
                                      "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (src, pos, j, *ev)).rowcount
            conn.execute("RELEASE otel_line")
            added += n
        except BAD_LINE:
            conn.execute("ROLLBACK TO otel_line")
            conn.execute("RELEASE otel_line")
        pos += len(line)
    conn.execute("INSERT OR REPLACE INTO otel_files VALUES (?, ?, ?)", (src, pos, _head(path, pos) if pos else None))
    return added


def ingest(conn, directory=None):
    """Read every new api_request event under the OTel folder, then match them to requests. A missing folder is a no-op."""
    directory = directory or paths.otel_dir()
    if not directory.is_dir():
        return 0
    added = sum(_read(conn, path) for path in sorted(directory.glob("logs-*.jsonl")))
    match(conn)
    conn.commit()
    return added


def _secs(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


def match(conn):
    """Pair each unmatched event with the request of its session that has the same tokens and the closest time."""
    todo = conn.execute("SELECT rowid, session_id, ts, input, output, cache_read, cache_write FROM otel_requests "
                        "WHERE request_key IS NULL AND session_id IS NOT NULL ORDER BY ts").fetchall()
    by_session = {}
    for r in todo:
        by_session.setdefault(r[1], []).append(r)
    for sid, evs in by_session.items():
        taken = {k for (k,) in conn.execute("SELECT request_key FROM otel_requests WHERE session_id = ? AND request_key IS NOT NULL", (sid,))}
        reqs = [(k, _secs(ts), tokens) for k, ts, *tokens in conn.execute(
            "SELECT request_key, ts, input, output, cache_read, cache_write_5m + cache_write_1h FROM requests WHERE session_id = ?", (sid,))
            if k not in taken]
        for rowid, _, ts, *tokens in evs:
            t = _secs(ts)
            best = min(((abs(rt - t), k) for k, rt, tk in reqs if t is not None and rt is not None and tk == tokens
                        and abs(rt - t) <= MATCH_SECONDS), default=None)
            if best:
                conn.execute("UPDATE otel_requests SET request_key = ? WHERE rowid = ?", (best[1], rowid))
                reqs = [r for r in reqs if r[0] != best[1]]


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
