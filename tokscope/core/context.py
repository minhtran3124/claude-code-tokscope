"""What fills the context window: tool and MCP results ranked by size, what each large result costs the requests
after it (the carry), and how close each session got to the window and to a compaction.

Every number here is an estimate. The API reports usage per request, not per tool call: a result's tokens come from
its characters, and its carry is those tokens times the later requests that re-read it at the cache-read rate."""

from bisect import bisect_left, bisect_right
from statistics import median

from . import pricing
from .calls import CHARS_PER_TOKEN, mcp_server
from .errors import for_calls

# Claude 4.7 and later produce about 30% more tokens for the same text (docs.claude.com/en/docs/about-claude/pricing)
NEW_TOKENIZER = (4, 7)
NEW_CHARS_PER_TOKEN = CHARS_PER_TOKEN / 1.3
WINDOW = 200_000
BIG_WINDOW = 1_000_000  # the transcript does not name the window: a request past 200K proves the larger one
BIG_RESULT = 20_000     # ~2K lines of a file; a Read this size is worth a hint
HOT = 0.8
SHORT = "~ estimate: characters / 4 (3.1 for Claude 4.7+); carry = tokens x later requests x cache-read rate"
METHOD = ("~ estimate: result tokens = characters / chars per token (4.0, or 3.1 for Claude 4.7 and later, which tokenizes "
          "about 30% denser); carry = result tokens x the later requests in the same thread until a compaction, "
          "at each request's model cache-read rate")


def version(model):
    """(major, minor) of claude-<family>-<major>-<minor>[-date], or None (claude-opus-4-1 reads as 4.1)."""
    parts = (model or "").split("-")
    nums = [p for p in parts[2:] if p.isdigit() and len(p) < 4]
    return (int(nums[0]), int(nums[1]) if len(nums) > 1 else 0) if nums and parts[:1] == ["claude"] else None


def chars_per_token(model):
    v = version(model)
    return NEW_CHARS_PER_TOKEN if v and v >= NEW_TOKENIZER else CHARS_PER_TOKEN


def window_for(peak):
    return BIG_WINDOW if peak > WINDOW else WINDOW


def _and(where):
    return f"{where} AND" if where else "WHERE"


def _pct(q, xs):
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def load(conn, where="", params=()):
    """One dict per tool call with a result (Agent calls are subagents), with its estimated tokens and carry.
    `where` filters tool calls as r and sessions as s."""
    rows = conn.execute(
        f"SELECT r.session_id, r.agent_id, r.name, r.result_chars, r.model, s.project, r.skill, r.ts FROM tool_calls r "
        f"JOIN sessions s USING (session_id) {_and(where)} r.name != 'Agent' AND r.result_chars > 0", params).fetchall()
    sids = sorted({r[0] for r in rows})
    reqs, stops = {}, {}
    for i in range(0, len(sids), 500):
        chunk = sids[i:i + 500]
        marks = ",".join("?" * len(chunk))
        for sid, agent, ts, model in conn.execute(
                f"SELECT session_id, agent_id, ts, model FROM requests WHERE session_id IN ({marks}) ORDER BY ts", chunk):
            reqs.setdefault((sid, agent), []).append((ts or "", model))
        for sid, agent, ts in conn.execute(
                f"SELECT session_id, agent_id, ts FROM turn_events WHERE kind = 'compact' AND session_id IN ({marks}) "
                f"ORDER BY ts", chunk):
            stops.setdefault((sid, agent), []).append(ts or "")
    prefix, times, rates, ov = {}, {}, {}, pricing.overrides()  # one rate per model, pricing.json read once
    for key, rs in reqs.items():  # running sum of the cache-read rate, so the requests after a call add up in O(log n)
        acc = [0.0]
        for _, model in rs:
            if model not in rates:
                rates[model] = pricing.cache_read_rate(model, ov) or 0
            acc.append(acc[-1] + rates[model])
        prefix[key], times[key] = acc, [t for t, _ in rs]
    out = []
    for sid, agent, name, chars, model, project, skill, ts in rows:
        tokens, key = chars / chars_per_token(model), (sid, agent)
        later = carry = 0
        if ts and key in times:
            lo = bisect_right(times[key], ts)
            stop = stops.get(key, [])
            cut = bisect_right(stop, ts)
            hi = max(lo, bisect_left(times[key], stop[cut]) if cut < len(stop) else len(times[key]))
            later, carry = hi - lo, tokens * (prefix[key][hi] - prefix[key][lo])
        out.append({"session": sid, "name": name, "tokens": tokens, "project": project, "skill": skill,
                    "later": later, "carry": carry})
    return out


def _label(name, by):
    if by == "server":
        return mcp_server(name)
    if by == "mcp_tool":
        return name.removeprefix("mcp__").replace("__", " · ", 1) if name.count("__") >= 2 else name
    return name


def rank(calls, by="tool", split=None, limit=15):
    """Rows of {key, raw, split, calls, median, p95, total, share, carry}, biggest total first. by: "tool" (not MCP),
    "server" or "mcp_tool"; split: None, "project" or "skill". Share is of all result tokens in `calls`."""
    every = sum(c["tokens"] for c in calls) or 1
    groups = {}
    for c in calls:
        if c["name"].startswith("mcp__") != (by != "tool"):
            continue
        k = (_label(c["name"], by), (c[split] or "(none)") if split else None)
        groups.setdefault(k, []).append(c)
    rows = []
    for (key, sp), cs in groups.items():
        xs = sorted(c["tokens"] for c in cs)
        total = sum(xs)
        rows.append({"key": key, "raw": cs[0]["name"], "split": sp, "calls": len(cs), "median": median(xs),
                     "p95": _pct(0.95, xs), "total": total, "share": total / every, "carry": sum(c["carry"] for c in cs)})
    return sorted(rows, key=lambda r: (-r["total"], r["key"], r["split"] or ""))[:limit]


def server_p95(conn, bench_project, group=None):
    """{(cwd, server): p95 result tokens} over every MCP call made from a project folder. `group` maps a cwd to a
    key (e.g. its project) so the percentile is taken over all the calls of that key: {(key, server): p95}."""
    seen = {}
    for cwd, name, chars, model in conn.execute(
            "SELECT s.cwd, t.name, t.result_chars, t.model FROM tool_calls t JOIN sessions s USING (session_id) "
            "WHERE t.name LIKE 'mcp__%' AND t.result_chars > 0 AND s.project NOT LIKE ?", (bench_project,)):
        if name.count("__") >= 2:
            seen.setdefault((group.get(cwd, cwd) if group else cwd, name.split("__")[1]), []).append(chars / chars_per_token(model))
    return {k: _pct(0.95, sorted(v)) for k, v in seen.items()}


def pressure(conn, where="", params=(), limit=10):
    """(rows, compactions, sessions): per session the peak request (input + cache read + cache write) against the
    window and its compactions, {session, project, title, model, peak, window, share, compacts}, fullest first."""
    best = {}
    for sid, project, title, model, peak in conn.execute(
            f"SELECT r.session_id, s.project, s.title, r.model, max(r.input + r.cache_read + r.cache_write_5m + r.cache_write_1h) "
            f"FROM requests r JOIN sessions s USING (session_id) {where} GROUP BY 1, 4", params):
        if peak and (sid not in best or peak > best[sid]["peak"]):
            best[sid] = {"session": sid, "project": project, "title": title, "model": model, "peak": peak}
    cwhere, cparams = for_calls(where, params)
    compacts = dict(conn.execute(
        f"SELECT r.session_id, count(*) FROM turn_events r JOIN sessions s USING (session_id) {_and(cwhere)} "
        f"r.kind = 'compact' GROUP BY 1", cparams))
    for row in best.values():
        row["window"] = window_for(row["peak"])
        row["share"] = row["peak"] / row["window"]
        row["compacts"] = compacts.get(row["session"], 0)
    rows = sorted(best.values(), key=lambda r: (-r["share"], -r["peak"]))
    return rows[:limit], sum(compacts.values()), rows


HINTS = (("mcp__", "add a limit or pagination parameter"), ("Read", "read with offset/limit, or Grep first"),
         ("Bash", "pipe the output through head, tail or grep"), ("Grep", "narrow the pattern or set head_limit"))


def hint(name):
    return next((h for prefix, h in HINTS if name.startswith(prefix)), "return less per call")


def findings(calls, sessions, compacts):
    """Plain sentences (no markup): fat tools, big Reads, the costliest carry, full windows. `sessions` = all pressure rows."""
    out = []
    fat = [r for r in rank(calls, "mcp_tool", None, 50) + rank(calls, "tool", None, 50)
           if r["calls"] >= 3 and (r["p95"] >= 10_000 or r["share"] >= 0.25)]
    for r in sorted(fat, key=lambda r: -r["total"])[:3]:
        out.append(f"{r['key']} p95 ~{r['p95'] / 1000:.0f}K tokens: {r['share']:.0%} of all tool tokens; "
                   f"consider: {hint(r['raw'])}")
    big = sum(1 for c in calls if c["name"] == "Read" and c["tokens"] >= BIG_RESULT)
    if big:
        out.append(f"{big} Read result{'s' * (big != 1)} over ~{BIG_RESULT // 1000}K tokens (files past ~2K lines); "
                   "read with offset/limit")
    top = max((c for c in calls if c["carry"]), key=lambda c: c["carry"], default=None)
    if top:
        out.append(f"the costliest result to carry is {top['name']} at ~${top['carry']:.2f} "
                   f"(~{top['tokens'] / 1000:.1f}K tokens re-read by {top['later']} later requests)")
    hot = sum(1 for s in sessions if s["share"] >= HOT)
    if hot or compacts:
        out.append(f"{hot} session{'s' * (hot != 1)} reached {HOT:.0%} or more of the context window; "
                   f"{compacts} compaction{'s' * (compacts != 1)}")
    return out
