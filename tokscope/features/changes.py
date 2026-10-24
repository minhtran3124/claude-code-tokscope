"""Config-change markers (e.g. "reviewer: fable -> opus") and their before/after impact on real sessions."""

import sqlite3
from datetime import datetime, timedelta, timezone
from statistics import median

from ..core import errors

CHANGES_SCHEMA = """
CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, note TEXT NOT NULL,
    agent_type TEXT, skill TEXT
);
"""
# benchmark and replay sessions run under <repo>/bench/; they are experiments, not real work. Matches the
# repo at …/tokscope (…-tokscope-bench-…) and at the old …/cc-tokscope-mod (…-tokscope-mod-bench-…).
BENCH_PROJECT = "%tokscope%-bench-%"
TOKENS = "(input + cache_read + cache_write_5m + cache_write_1h + output)"


def add_change(conn, note, agent_type=None, skill=None, at=None):
    if not (agent_type or skill):
        raise ValueError("a change needs --agent or --skill to measure")
    conn.executescript(CHANGES_SCHEMA)
    at = at or datetime.now(timezone.utc).isoformat()
    cur = conn.execute("INSERT INTO changes (at, note, agent_type, skill) VALUES (?,?,?,?)", (at, note, agent_type, skill))
    conn.commit()
    return cur.lastrowid


def list_changes(conn):
    conn.executescript(CHANGES_SCHEMA)
    return conn.execute("SELECT id, at, note, agent_type, skill FROM changes ORDER BY at").fetchall()


def _units(conn, change, start, end):
    """Per-unit (one subagent run, or one skill load's requests) totals in [start, end)."""
    _, at, _, agent_type, skill = change
    if agent_type:
        sql = f"""SELECT sum({TOKENS}), sum(output), sum(cost_usd), group_concat(DISTINCT model)
                  FROM requests r JOIN sessions s USING (session_id)
                  WHERE r.agent_type = ? AND r.agent_id IS NOT NULL AND s.project NOT LIKE ?
                    AND r.ts >= ? AND r.ts < ?
                  GROUP BY r.session_id, r.agent_id"""
        key = agent_type
    else:
        sql = f"""SELECT sum({TOKENS}), sum(output), sum(cost_usd), group_concat(DISTINCT model)
                  FROM requests r JOIN sessions s USING (session_id)
                  WHERE r.skill = ? AND s.project NOT LIKE ? AND r.ts >= ? AND r.ts < ?
                  GROUP BY r.session_id, r.prompt_idx"""
        key = skill
    return conn.execute(sql, (key, BENCH_PROJECT, start, end)).fetchall()


def _summary(units):
    if not units:
        return {"n": 0}
    tokens = [u[0] or 0 for u in units]
    return {
        "n": len(units),
        "tokens_median": median(tokens),
        "tokens_mean": sum(tokens) / len(tokens),
        "output_median": median(u[1] or 0 for u in units),
        "usd_median": median(u[2] or 0 for u in units),
        "models": sorted({m for u in units for m in (u[3] or "").split(",") if m}),
    }


def impact(conn, change, days=14):
    """Before/after per-unit medians in equal windows around the change (after-window clipped to now)."""
    at = datetime.fromisoformat(change[1].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    after_end = min(at + timedelta(days=days), now)
    span = after_end - at
    # the before-window matches the elapsed after-window, so a 2-day-old change compares 2 days to 2 days
    before_start = at - (span if span > timedelta(0) else timedelta(days=days))
    iso = lambda d: d.isoformat()  # noqa: E731
    who, value = ("agent", change[3]) if change[3] else ("skill", change[4])

    def side(start, end):
        return {**_summary(_units(conn, change, iso(start), iso(end))),
                "errors": errors.window(conn, who, value, iso(start), iso(end), BENCH_PROJECT)}
    return {
        "before": side(before_start, at),
        "after": side(at, after_end),
        "window_days": round(max(span.total_seconds(), 0) / 86400, 1),
    }


def errors_text(e):
    """`errors 3/40 calls (7.5%), 2 repeats, 1 interrupt` for the totals errors.window gives."""
    return (f"errors {e['errors']}/{e['calls']} calls ({errors.pct(e['errors'], e['calls'])}), {e['repeats']} repeats, "
            f"{e['interrupts']} interrupts, {e['api_errors']} API errors")


def impact_text(conn, change, days=14):
    cid, at, note, agent_type, skill = change
    r = impact(conn, change, days)
    unit = "subagent run" if agent_type else "skill load"
    lines = [f"#{cid} {at[:16]}  {note}  ({agent_type or skill}, per {unit}, ±{r['window_days']}d)"]
    for side in ("before", "after"):
        s = r[side]
        if not s["n"]:
            lines.append(f"  {side:<6}  no {unit}s in window")
            continue
        lines.append(f"  {side:<6}  n={s['n']:<4} tokens median {s['tokens_median']:>12,.0f}  output {s['output_median']:>8,.0f}  "
                     f"(${s['usd_median']:.3f} API-eq)  {','.join(s['models'])}")
        lines.append(f"  {'':<6}  {errors_text(s['errors'])}")
    b, a = r["before"], r["after"]
    if b["n"] and a["n"] and b["tokens_median"]:
        lines.append(f"  change  tokens/{unit} {a['tokens_median'] / b['tokens_median'] - 1:+.0%}"
                     + (f"  error rate {errors.pct(b['errors']['errors'], b['errors']['calls'])} -> "
                        f"{errors.pct(a['errors']['errors'], a['errors']['calls'])}" if b["errors"]["calls"] and a["errors"]["calls"] else ""))
    return "\n".join(lines)
