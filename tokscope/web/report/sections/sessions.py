"""The sessions list data that the page script renders."""

from pathlib import Path

from ....core import skills
from ....core.calls import turn_calls
from ..common import TOKENS


def _sessions_json(conn, cond, params):
    base = f"FROM requests r JOIN sessions s USING (session_id) {cond}"
    sessions = {}
    for sid, proj, title, start, end, prompts, cwd, tokens, out, usd, main, agents, runs in conn.execute(
            f"""SELECT session_id, s.project, s.title, s.first_ts, s.last_ts, s.prompts, s.cwd, sum({TOKENS}), sum(output), sum(cost_usd),
                       sum(CASE WHEN agent_id IS NULL THEN {TOKENS} END), sum(CASE WHEN agent_id IS NOT NULL THEN {TOKENS} END),
                       count(DISTINCT agent_id) {base} GROUP BY session_id""", params):
        sessions[sid] = {"id": sid, "title": title or "", "start": start or "", "end": end or "", "prompts": prompts or 0,
                         "project": Path(cwd or "").name, "path": f"~/.claude/projects/{proj}/{sid}.jsonl", "tokens": tokens or 0, "output": out or 0, "usd": usd,
                         "main": main or 0, "agents": agents or 0, "runs": runs, "owners": {}, "skills": {}, "turns": []}
    for sid, owner, tk in conn.execute(
            f"SELECT session_id, COALESCE(agent_type, 'main thread'), sum({TOKENS}) {base} GROUP BY 1, 2", params):
        sessions[sid]["owners"][owner] = tk or 0
    for sid, skill, tk in conn.execute(
            f"SELECT session_id, skill, sum({TOKENS}) {base} AND skill IS NOT NULL GROUP BY 1, 2", params):
        sessions[sid]["skills"][skill] = tk or 0
    texts = {(sid, i): text for sid, i, text in conn.execute("SELECT session_id, prompt_idx, text FROM prompts")}
    agents = {}
    for sid, i, atype, models in conn.execute(
            f"SELECT session_id, prompt_idx, agent_type, group_concat(DISTINCT model) {base} AND agent_id IS NOT NULL "
            f"GROUP BY session_id, prompt_idx, agent_id", params):
        per = agents.setdefault((sid, i), {})
        a = per.setdefault(atype, {"type": atype, "n": 0, "models": set()})
        a["n"] += 1
        a["models"].update(m.removeprefix("claude-") for m in (models or "").split(",") if m)
    calls = turn_calls(conn)
    versions = skills.turn_versions(conn)
    for sid, i, skill, tk, out, usd, ag in conn.execute(
            f"SELECT session_id, prompt_idx, max(skill), sum({TOKENS}), sum(output), sum(cost_usd), "
            f"sum(CASE WHEN agent_id IS NOT NULL THEN {TOKENS} END) {base} "
            f"GROUP BY session_id, prompt_idx ORDER BY session_id, prompt_idx IS NULL, prompt_idx", params):
        sessions[sid]["turns"].append({
            "i": i, "text": texts.get((sid, i), ""), "skill": skill, "tokens": tk or 0, "output": out or 0, "usd": usd,
            "version": versions.get((sid, i, skill)),
            "agents_tokens": ag or 0, **calls.get((sid, i), {"requests": 0, "runs": [], "mcp": [], "tools": []}),
            "agents": [{"type": a["type"], "n": a["n"], "models": ", ".join(sorted(a["models"]))}
                       for a in sorted(agents.get((sid, i), {}).values(), key=lambda a: -a["n"])]})
    for s in sessions.values():
        if not s["title"]:
            first = next((t["text"] for t in s["turns"] if t["text"]), "")
            s["title"] = f"“{first[:80]}”" if first else ""
        s["top_skill"] = max(s["skills"], key=s["skills"].get) if s["skills"] else ""
    # a headless session (claude -p) names the session that started it; the list shows it under that one
    # (a parent outside the report's filter keeps its id but not its title: that is another project's text)
    for sid, parent in conn.execute("SELECT session_id, parent_session_id FROM sessions WHERE parent_session_id IS NOT NULL"):
        if sid in sessions:
            sessions[sid]["parent"] = parent
            sessions[sid]["parent_title"] = sessions[parent]["title"] if parent in sessions else f"session {parent[:8]}"
    return list(sessions.values())
