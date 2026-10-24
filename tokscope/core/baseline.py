"""The always-on baseline: what a session already carries in its first main-thread request (system prompt, tool
definitions, MCP servers, skills list, CLAUDE.md) before the owner types anything. Read from `requests`, no new parsing."""

import math
from datetime import datetime, timedelta, timezone

from .calls import CHARS_PER_TOKEN
from .pricing import cost_usd

TREND_DAYS = 30
# the method, for the tooltip of every figure derived from it
METHOD = ("Estimate. A session's baseline is input + cache write + cache read tokens of its first main-thread request "
          "(subagent requests ignored). Cost = those tokens at the cache-write rate of the model.")
DEF_METHOD = ("Estimate. MCP tool definitions are read from the first request's tool list; their size is about "
              f"{CHARS_PER_TOKEN} characters per token. Tools loaded on demand are not in the first request and count 0.")


def starts(conn, cond="", params=()):
    """[(session_id, cwd, ts, model, tokens)] oldest first: each session's first main-thread request. `cond` is a WHERE
    clause over requests r and sessions s (empty: every session)."""
    cond = f"{cond} AND" if cond else "WHERE"
    seen, out = set(), []
    for sid, cwd, ts, model, tokens in conn.execute(
            f"SELECT s.session_id, s.cwd, r.ts, r.model, r.input + r.cache_read + r.cache_write_5m + r.cache_write_1h "
            f"FROM requests r JOIN sessions s USING (session_id) {cond} r.agent_id IS NULL AND r.ts = "
            f"(SELECT min(m.ts) FROM requests m WHERE m.session_id = r.session_id AND m.agent_id IS NULL) "
            f"ORDER BY r.ts, r.request_key", params):
        if sid not in seen and tokens:
            seen.add(sid)
            out.append((sid, cwd, ts, model, tokens))
    return out


def _pct(values, q):
    values = sorted(values)
    return values[max(0, math.ceil(q * len(values)) - 1)]


def _median(values):
    values = sorted(values)
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def per_token_usd(model):
    """USD of one baseline token at the model's cache-write rate, or None for a model without a price."""
    one = cost_usd(model, 0, 0, 0, 1_000_000, 0)
    return None if one is None else one / 1_000_000


def stats(rows, now=None, all_rows=None):
    """None without sessions; else the sessions counted, median and p90 baseline, the cost of one session start (median
    of the priced sessions), the newest session's model, and the 30-day trend: one point per day with sessions (that
    day's median) plus the median of the first and of the last half of those days. `rows` are `starts` rows; `all_rows`
    (every session of the same scope) feeds the trend when `rows` is a narrower range."""
    if not rows:
        return None
    tokens = [r[4] for r in rows]
    costs = [r[4] * p for r in rows if (p := per_token_usd(r[3])) is not None]
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=TREND_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    days = {}
    for r in rows if all_rows is None else all_rows:  # the trend ignores the range
        if (r[2] or "") >= since:
            days.setdefault(r[2][:10], []).append(r[4])
    series = [_median(v) for _, v in sorted(days.items())]
    half = len(series) // 2
    return {"n": len(rows), "median": _median(tokens), "p90": _pct(tokens, 0.9),
            "cost": _median(costs) if costs else None, "model": rows[-1][3], "trend": series,
            "first": _median(series[:half]) if half else None, "last": _median(series[half:]) if half else None}
