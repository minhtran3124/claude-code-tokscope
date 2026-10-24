"""Prompt-cache analytics: hit ratio and cache-write $ per session, skill, subagent type and model, likely misses found
from the transcripts, and the official miss causes when statusline snapshots exist.

A miss is a request whose cache_read fell below half of the previous request's in the same thread (the main thread, or one
subagent) while it wrote at least MIN_WRITE tokens, with no /compact prompt in between. Its cause is the idle gap:
over 1 h = ttl_expired_1h, over 5 min = ttl_expired_5m, shorter = prefix_changed (the tool list or system prompt changed;
the transcript cannot say which). Rows are read as `r` and sessions as `s`, so the filters of cli._filters apply."""

import json
from datetime import datetime

from . import errors, pricing

MIN_WRITE = 2000
DROP = 0.5
GAPS = ((3600, "ttl_expired_1h"), (300, "ttl_expired_5m"))
OFFICIAL = "official: Claude Code statusline prompt_cache"
FIELDS = ("key", "requests", "reads", "writes", "inputs", "hit_ratio", "write_usd", "recache_usd", "misses")
BY = ("session", "skill", "agent", "model")


def _time(ts):
    return datetime.fromisoformat((ts or "").replace("Z", "+00:00"))


def ratio(reads, writes, inputs):
    """Share of the prompt tokens served from the cache, or None with no prompt tokens."""
    total = reads + writes + inputs
    return reads / total if total else None


def pct(r):
    return "–" if r is None else f"{r:.0%}"


def _write_usd(model, cw5, cw1, speed, geo):
    return pricing.cost_usd(model, 0, 0, 0, cw5, cw1, speed, geo) or 0.0


def compacted(conn, session_id, start, end):
    """True when a /compact prompt of the session sits between two requests."""
    return conn.execute("SELECT 1 FROM prompts WHERE session_id = ? AND ts > ? AND ts <= ? AND text LIKE '%/compact%' LIMIT 1",
                        (session_id, start, end)).fetchone() is not None


def scan(conn, where="", params=()):
    """(requests, misses): every request as a dict, and the likely misses among them as dicts with cause, gap (s),
    recache (tokens) and recache_usd."""
    rows = conn.execute(
        "SELECT r.session_id, COALESCE(r.agent_id, ''), r.ts, r.model, COALESCE(r.skill, '(none)'), "
        "COALESCE(a.agent_type, 'main'), COALESCE(r.input, 0), COALESCE(r.cache_read, 0), COALESCE(r.cache_write_5m, 0), "
        "COALESCE(r.cache_write_1h, 0), r.speed, r.inference_geo FROM requests r JOIN sessions s USING (session_id) "
        "LEFT JOIN subagents a ON a.session_id = r.session_id AND a.agent_id = r.agent_id "
        f"{where} ORDER BY r.session_id, COALESCE(r.agent_id, ''), r.ts", params).fetchall()
    reqs, misses, prev = [], [], None
    for sid, aid, ts, model, skill, agent, inp, cr, cw5, cw1, speed, geo in rows:
        d = {"session": sid, "ts": ts, "model": model or "?", "skill": skill, "agent": agent, "input": inp, "reads": cr,
             "writes": cw5 + cw1, "write_usd": _write_usd(model, cw5, cw1, speed, geo), "miss": None}
        if (prev and prev["thread"] == (sid, aid) and prev["reads"] > 0 and cr < prev["reads"] * DROP
                and cw5 + cw1 >= MIN_WRITE and not compacted(conn, sid, prev["ts"], ts)):
            try:
                gap = (_time(ts) - _time(prev["ts"])).total_seconds()
            except ValueError:
                gap = 0
            cause = next((c for g, c in GAPS if gap > g), "prefix_changed")
            d["miss"] = {"cause": cause, "gap": gap, "recache": cw5 + cw1, "recache_usd": d["write_usd"]}
            misses.append({**d["miss"], **{k: d[k] for k in ("session", "skill", "agent", "model", "ts")}})
        reqs.append(d)
        prev = {"thread": (sid, aid), "ts": ts, "reads": cr}
    return reqs, misses


def rows(reqs, by, limit=15):
    """One dict (FIELDS) per session, skill, agent type or model, most cache-write $ first."""
    out = {}
    for r in reqs:
        d = out.setdefault(r[by], dict(zip(FIELDS, (r[by], 0, 0, 0, 0, None, 0.0, 0.0, 0))))
        d["requests"] += 1
        d["reads"] += r["reads"]
        d["writes"] += r["writes"]
        d["inputs"] += r["input"]
        d["write_usd"] += r["write_usd"]
        if r["miss"]:
            d["misses"] += 1
            d["recache_usd"] += r["miss"]["recache_usd"]
    for d in out.values():
        d["hit_ratio"] = ratio(d["reads"], d["writes"], d["inputs"])
    return sorted(out.values(), key=lambda d: (-d["write_usd"], d["key"]))[:limit]


def causes(misses):
    """[(cause, misses, re-cached tokens, re-cache $)], most dollars first."""
    out = {}
    for m in misses:
        c = out.setdefault(m["cause"], [0, 0, 0.0])
        c[0] += 1
        c[1] += m["recache"]
        c[2] += m["recache_usd"]
    return sorted(((k, *v) for k, v in out.items()), key=lambda t: (-t[3], t[0]))


def totals(reqs, misses):
    """{requests, hit_ratio, write_usd, recache_usd, recache_tokens, misses, top_cause} over the requests."""
    reads, writes, inputs = (sum(r[k] for r in reqs) for k in ("reads", "writes", "input"))
    top = causes(misses)
    return {"requests": len(reqs), "hit_ratio": ratio(reads, writes, inputs), "write_usd": sum(r["write_usd"] for r in reqs),
            "recache_usd": sum(m["recache_usd"] for m in misses), "recache_tokens": sum(m["recache"] for m in misses),
            "misses": len(misses), "top_cause": top[0][0] if top else None}


def official(conn, where="", params=()):
    """Official miss causes from the statusline snapshots, or None without any: the latest snapshot of each session,
    summed. Returns {causes: {cause: count}, misses, recache_tokens, sessions}. The table statusline_snapshots
    (session_id, ts, prompt_cache JSON) is written by the statusline feature; absent, there is nothing official to show."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'statusline_snapshots'").fetchone():
        return None
    where, params = errors.for_calls(where, params)
    latest = conn.execute(
        "SELECT r.session_id, r.prompt_cache, max(r.ts) FROM statusline_snapshots r JOIN sessions s USING (session_id) "
        f"{where} GROUP BY r.session_id", params).fetchall()
    out = {"causes": {}, "misses": 0, "recache_tokens": 0, "sessions": 0}
    for _, blob, _ in latest:
        try:
            pc = json.loads(blob or "{}")
        except ValueError:
            continue
        if not isinstance(pc, dict) or not pc.get("misses"):
            continue
        out["sessions"] += 1
        out["misses"] += int(pc.get("misses") or 0)
        out["recache_tokens"] += int(pc.get("miss_recache_tokens") or 0)
        mc = pc.get("miss_causes")
        for k, n in (mc.items() if isinstance(mc, dict) else ()):
            out["causes"][k] = out["causes"].get(k, 0) + int(n or 0)
    return out if out["sessions"] else None
