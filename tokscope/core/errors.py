"""Where Claude Code goes wrong: failed tool calls, repeated calls, interrupts, API errors and retries, per skill,
subagent type and phase. One source for `tokscope summary --errors`, Breakdowns, the Versions card and `tokscope change`.

Rows come from tool_calls and turn_events (see ingest.SCHEMA). Both are read as `r`, so the filters of
cli._filters and the dashboard (r.ts, s.project) apply to them as they do to requests."""

KEYS = {
    "phase": ("COALESCE(r.phase, 'unscoped')", ""),
    "skill": ("COALESCE(r.skill, '(none)')", ""),
    "agent": ("COALESCE(a.agent_type, 'main')", "LEFT JOIN subagents a ON a.session_id = r.session_id AND a.agent_id = r.agent_id"),
}
FIELDS = ("key", "calls", "errors", "repeats", "interrupts", "api_errors", "retries", "failed_loads")
EVENT_FIELDS = {"interrupt": "interrupts", "api_error": "api_errors", "retry": "retries"}


def for_calls(where, params):
    """`where` without the clauses on request columns a tool call lacks (the model filter)."""
    if "r.model" not in where:
        return where, params
    clauses, kept, left = where.removeprefix("WHERE ").split(" AND "), [], list(params)
    for c in clauses:
        n = c.count("?")
        taken, left = left[:n], left[n:]
        if "r.model" not in c:
            kept += [(c, taken)]
    return ("WHERE " + " AND ".join(c for c, _ in kept) if kept else ""), tuple(x for _, t in kept for x in t)


def rate(errors, calls):
    """Share of tool calls that failed, or None with no calls."""
    return errors / calls if calls else None


def pct(errors, calls):
    r = rate(errors, calls)
    return "–" if r is None else f"{r:.1%}"


def _empty(k):
    return dict(zip(FIELDS, (k, 0, 0, 0, 0, 0, 0, 0)))


def rows(conn, by, where="", params=(), limit=25):
    """One dict (FIELDS) per skill, agent type or phase, most failed calls first. `where` filters tool calls and
    events as r and sessions as s."""
    key, join = KEYS[by]
    where, params = for_calls(where, params)
    out = {}
    for k, calls, errors, repeats in conn.execute(
            f"SELECT {key}, count(*), sum(COALESCE(r.is_error, 0)), sum(COALESCE(r.repeat, 0)) FROM tool_calls r "
            f"JOIN sessions s USING (session_id) {join} {where} GROUP BY 1", params):
        out[k] = dict(zip(FIELDS, (k, calls, errors or 0, repeats or 0, 0, 0, 0, 0)))
    for k, kind, n in conn.execute(
            f"SELECT {key}, r.kind, count(*) FROM turn_events r JOIN sessions s USING (session_id) {join} {where} "
            f"GROUP BY 1, 2", params):
        if kind in EVENT_FIELDS:  # a compaction is context, not an error
            out.setdefault(k, _empty(k))[EVENT_FIELDS[kind]] = n
    for k, n in conn.execute(  # Skill loads that failed (unknown skill, error result), by the skill they named
            f"SELECT {key}, count(*) FROM skill_calls r JOIN sessions s USING (session_id) {join} {where} "
            f"{'AND' if where else 'WHERE'} r.failed = 1 GROUP BY 1", params):
        out.setdefault(k, _empty(k))["failed_loads"] = n
    found = sorted(out.values(), key=lambda d: (-d["errors"], -d["interrupts"], -d["calls"], d["key"]))[:limit]
    for d in found:
        d["error_rate"] = rate(d["errors"], d["calls"])
    return found


def classes(conn, where="", params=()):
    """[(error class, count)], most common first."""
    where, params = for_calls(where, params)
    return conn.execute(
        f"SELECT COALESCE(r.err_class, 'other'), count(*) FROM tool_calls r JOIN sessions s USING (session_id) {where} "
        f"{'AND' if where else 'WHERE'} r.is_error = 1 GROUP BY 1 ORDER BY 2 DESC, 1", params).fetchall()


def totals(conn, where="", params=(), join=""):
    """{calls, errors, repeats, interrupts, api_errors, retries, error_rate} over what `where` keeps."""
    calls, errors, repeats = conn.execute(
        f"SELECT count(*), sum(COALESCE(r.is_error, 0)), sum(COALESCE(r.repeat, 0)) FROM tool_calls r "
        f"LEFT JOIN sessions s USING (session_id) {join} {where}", params).fetchone()
    out = {"calls": calls, "errors": errors or 0, "repeats": repeats or 0, "interrupts": 0, "api_errors": 0, "retries": 0}
    for kind, n in conn.execute(f"SELECT r.kind, count(*) FROM turn_events r LEFT JOIN sessions s USING (session_id) {join} "
                                f"{where} GROUP BY 1", params):
        if kind in EVENT_FIELDS:
            out[EVENT_FIELDS[kind]] = n
    out["error_rate"] = rate(out["errors"], out["calls"])
    return out


def window(conn, who, value, start, end, bench):
    """totals() for one agent type (who="agent") or skill (who="skill") between two ISO times, bench sessions left out."""
    key, join = KEYS[who]
    cond = f"WHERE s.project NOT LIKE ? AND r.ts >= ? AND r.ts < ? AND {key} = ?"
    return totals(conn, cond, (bench, start, end, value), join)


def session(conn, session_id):
    """totals() for one session (a benchmark or replay run)."""
    return totals(conn, "WHERE r.session_id = ?", (session_id,))
