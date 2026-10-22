"""What each prompt called: subagents (exact tokens, from their own requests) and MCP servers / tools (estimated tokens,
from the size of the result they put into the context; the API reports usage per model request, not per tool call)."""

CHARS_PER_TOKEN = 4
TOKENS = "(input + cache_read + cache_write_5m + cache_write_1h + output)"


def mcp_server(name):
    """mcp__plugin_datadog_mcp__search_logs -> datadog; mcp__claude_ai_Linear__get_issue -> Linear."""
    server = name.split("__")[1] if name.count("__") >= 2 else name
    if server.startswith("plugin_"):
        return server.removeprefix("plugin_").split("_")[0]  # plugin_<plugin>_<server>
    return server.removeprefix("claude_ai_")


def est_tokens(chars):
    return round((chars or 0) / CHARS_PER_TOKEN)


def turn_calls(conn, session_id=None):
    """(session_id, prompt_idx) -> {"requests": n, "agents": [[type, runs, tokens]], "runs": [one dict per subagent run],
    "mcp": [[server, calls, ~tokens]], "tools": [[name, calls, ~tokens]]}, each list largest first. Agent tool calls are listed as subagents only."""
    where, params = ("WHERE session_id = ?", (session_id,)) if session_id else ("", ())
    out = {}

    def turn(sid, i):
        return out.setdefault((sid, i), {"requests": 0, "agents": [], "runs": [], "mcp": [], "tools": []})

    for sid, i, n in conn.execute(f"SELECT session_id, prompt_idx, count(*) FROM requests {where} GROUP BY 1, 2", params):
        turn(sid, i)["requests"] = n
    agent_where = f"{where} AND" if where else "WHERE"
    for sid, i, atype, runs, tk in conn.execute(
            f"SELECT session_id, prompt_idx, agent_type, count(DISTINCT agent_id), sum({TOKENS}) FROM requests "
            f"{agent_where} agent_id IS NOT NULL GROUP BY 1, 2, 3 ORDER BY 5 DESC", params):
        turn(sid, i)["agents"].append([atype or "unknown", runs, tk or 0])
    # one row per subagent run, in start order; nested runs carry their depth
    run_where = "WHERE s.session_id = ?" if session_id else ""
    for sid, i, atype, desc, depth, tk, out_tok, usd, priced, models in conn.execute(
            f"SELECT s.session_id, s.prompt_idx, s.agent_type, s.description, s.spawn_depth, sum({TOKENS}), sum(r.output), "
            f"sum(r.cost_usd), count(r.cost_usd) = count(*), group_concat(DISTINCT r.model) FROM subagents s "
            f"JOIN requests r ON r.session_id = s.session_id AND r.agent_id = s.agent_id {run_where} "
            f"GROUP BY s.session_id, s.agent_id ORDER BY min(r.ts)", params):
        turn(sid, i)["runs"].append({
            "type": atype or "unknown", "desc": desc or "", "depth": depth or 1, "tokens": tk or 0, "out": out_tok or 0,
            "usd": usd if priced else None, "model": ", ".join(m.removeprefix("claude-") for m in (models or "").split(",") if m)})
    grouped = {}
    for sid, i, name, n, chars in conn.execute(
            f"SELECT session_id, prompt_idx, name, count(*), sum(result_chars) FROM tool_calls {where} GROUP BY 1, 2, 3",
            params):
        if name == "Agent":
            continue
        kind, key = ("mcp", mcp_server(name)) if name.startswith("mcp__") else ("tools", name)
        g = grouped.setdefault((sid, i, kind, key), [0, 0])
        g[0] += n
        g[1] += chars or 0
    for (sid, i, kind, key), (n, chars) in grouped.items():
        turn(sid, i)[kind].append([key, n, est_tokens(chars)])
    for t in out.values():
        for kind in ("mcp", "tools"):
            t[kind].sort(key=lambda c: (-c[2], -c[1]))
    return out
