"""Parse Claude Code transcripts into SQLite, attributing each API request to a skill, subagent and phase.

Attribution rules:
- A request is counted once per requestId (streamed responses repeat the same usage on several lines).
- skill: the last skill loaded in the current human prompt (Skill tool call or typed /command); reset on the
  next human prompt. Matches how OTel stamps skill.name.
- phase: derived from the last skill loaded in the session (phases.json); carries across prompts. A request
  whose prompt loaded no skill (skill NULL) holds a carried phase: see CARRIED.
- A subagent inherits prompt/skill/phase from the request whose tool call spawned it.
"""

import json
import re
import sqlite3
from pathlib import Path

from .pricing import cost_usd
from .skills import canonical_name, loaded_text_hash

PROJECTS_DIR = Path.home() / ".claude" / "projects"
# a phase inherited from an earlier prompt: no skill ran in this request's prompt (follow-ups like "ok, continue")
CARRIED = "(r.skill IS NULL AND r.phase IS NOT NULL)"
COMMAND_RE = re.compile(r"<command-name>/?([^<\s]+)</command-name>")
COMMAND_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)
SKILL_TEXT = "Base directory for this skill:"
# built-in CLI commands, not skills; they do not start a new prompt either
BUILTIN_COMMANDS = {
    "add-dir", "agents", "artifacts", "bug", "clear", "compact", "config", "context", "cost", "doctor", "effort",
    "exit", "export", "fast", "help", "hooks", "ide", "init", "login", "logout", "mcp", "memory", "model",
    "output-style", "permissions", "plugin", "pr-comments", "release-notes", "reload-plugins", "reload-skills",
    "remote-control", "resume", "rewind",
    "status", "statusline", "terminal-setup", "usage", "vim", "workflows",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY, project TEXT, cwd TEXT, title TEXT, version TEXT,
    first_ts TEXT, last_ts TEXT, prompts INTEGER, signature TEXT
);
CREATE TABLE IF NOT EXISTS requests (
    session_id TEXT, request_key TEXT, ts TEXT, model TEXT, agent_id TEXT, agent_type TEXT,
    prompt_idx INTEGER, skill TEXT, phase TEXT,
    input INTEGER, output INTEGER, thinking INTEGER, cache_read INTEGER,
    cache_write_5m INTEGER, cache_write_1h INTEGER, cost_usd REAL,
    PRIMARY KEY (session_id, request_key)
);
CREATE TABLE IF NOT EXISTS subagents (
    session_id TEXT, agent_id TEXT, agent_type TEXT, description TEXT, tool_use_id TEXT,
    spawn_depth INTEGER, parent_agent_id TEXT, prompt_idx INTEGER, skill TEXT, phase TEXT,
    PRIMARY KEY (session_id, agent_id)
);
CREATE TABLE IF NOT EXISTS skill_calls (
    session_id TEXT, ts TEXT, skill TEXT, phase TEXT, source TEXT, agent_id TEXT, prompt_idx INTEGER, tool_use_id TEXT,
    text_hash TEXT
);
CREATE TABLE IF NOT EXISTS prompts (
    session_id TEXT, prompt_idx INTEGER, ts TEXT, text TEXT, PRIMARY KEY (session_id, prompt_idx)
);
CREATE TABLE IF NOT EXISTS tool_calls (
    session_id TEXT, tool_use_id TEXT, prompt_idx INTEGER, agent_id TEXT, name TEXT, result_chars INTEGER, PRIMARY KEY (session_id, tool_use_id)
);
CREATE INDEX IF NOT EXISTS idx_requests_ts ON requests (ts);
"""
TABLES = ("requests", "subagents", "skill_calls", "prompts", "tool_calls", "sessions")
# bump when the parser records something new, so unchanged transcripts are parsed again once
PARSER_VERSION = 9
ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
PROMPT_CHARS = 160


def load_phases(path):
    raw = json.loads(Path(path).read_text())
    return {skill: phase for phase, skills in raw.items() if not phase.startswith("_") for skill in skills}


def phase_of(skill, phases):
    name = skill.split(":")[-1]
    return phases.get(name, f"other:{name}")


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def _is_human_prompt(rec):
    if rec.get("isMeta") or "toolUseResult" in rec:
        return False
    content = rec.get("message", {}).get("content")
    if isinstance(content, list) and content and isinstance(content[0], dict) and content[0].get("type") == "tool_result":
        return False
    # Claude Code writes this line itself when the person presses Esc; it is not something they typed
    if _text(content).lstrip().startswith("[Request interrupted"):
        return False
    origin = rec.get("turnOrigin")
    if origin is not None:
        return origin in ("human", "sdk")
    # older transcripts have no turnOrigin
    return not _text(content).lstrip().startswith(("<task-notification", "<local-command"))


def _prompt_text(rec, command):
    """The start of what the person typed; a slash command shows as /name args."""
    text = _text(rec.get("message", {}).get("content"))
    if command:
        args = ARGS_RE.search(text)
        text = f"/{command} {args.group(1).strip() if args else ''}"
    return " ".join(text.split())[:PROMPT_CHARS]


def _usage_fields(usage):
    cc = usage.get("cache_creation") or {}
    cw5 = cc.get("ephemeral_5m_input_tokens")
    cw1 = cc.get("ephemeral_1h_input_tokens")
    if cw5 is None and cw1 is None:
        cw5, cw1 = usage.get("cache_creation_input_tokens") or 0, 0
    return {
        "input": usage.get("input_tokens") or 0,
        "output": usage.get("output_tokens") or 0,
        "thinking": (usage.get("output_tokens_details") or {}).get("thinking_tokens") or 0,
        "cache_read": usage.get("cache_read_input_tokens") or 0,
        "cache_write_5m": cw5 or 0,
        "cache_write_1h": cw1 or 0,
    }


class SessionParser:
    def __init__(self, main_path, phases):
        self.main_path = Path(main_path)
        self.session_id = self.main_path.stem
        self.phases = phases
        self.requests = {}
        self.subagents = []
        self.skill_calls = []
        self.prompts = []
        self.tool_ctx = {}  # tool_use_id -> (prompt_idx, skill, phase, agent_id)
        self.tool_calls = {}  # tool_use_id -> (prompt_idx, agent_id, name)
        self.result_chars = {}  # tool_use_id -> text size of the result that went into the context
        self.skill_texts = {}  # Skill tool_use_id -> the SKILL.md text it loaded, where a request blob kept it
        self.skill_args = {}  # Skill tool_use_id -> the args the call passed
        self.meta = {"title": None, "version": None, "cwd": None, "first_ts": None, "last_ts": None, "prompts": 0}

    def parse(self):
        self._walk(self.main_path, agent_id=None, agent_type=None, state={"prompt_idx": 0, "skill": None, "phase": None})
        sub_dir = self.main_path.with_suffix("") / "subagents"
        agents = []
        for path in sub_dir.glob("agent-*.jsonl") if sub_dir.is_dir() else []:
            meta_path = path.with_suffix(".meta.json")
            meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
            agents.append((meta.get("spawnDepth") or 1, path, meta))
        # parents before children so a nested agent finds its spawning tool call
        for depth, path, meta in sorted(agents, key=lambda a: (a[0], a[1].name)):
            agent_id = path.stem.removeprefix("agent-")
            prompt_idx, skill, phase, parent = self.tool_ctx.get(meta.get("toolUseId"), (None, None, None, None))
            agent_type = meta.get("agentType") or "unknown"
            self.subagents.append({
                "agent_id": agent_id, "agent_type": agent_type, "description": meta.get("description"),
                "tool_use_id": meta.get("toolUseId"), "spawn_depth": depth, "parent_agent_id": parent,
                "prompt_idx": prompt_idx, "skill": skill, "phase": phase,
            })
            self._walk(path, agent_id, agent_type, {"prompt_idx": prompt_idx, "skill": skill, "phase": phase})
        return self

    def _walk(self, path, agent_id, agent_type, state):
        is_main = agent_id is None
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                # request blobs and shapes are large and carry no usage; a blob can hold the skill text a load put in
                if '"api-request-blob"' in line[:40] and SKILL_TEXT in line:
                    self._on_skill_blob(line)
                    continue
                if line.startswith('{"type":"api-request') or line.startswith('{"type":"attachment"'):
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                kind = rec.get("type")
                if is_main:
                    self._track_meta(rec)
                if kind == "assistant":
                    self._on_assistant(rec, agent_id, agent_type, state)
                elif kind == "user":
                    self._on_tool_results(rec)
                    self._on_command_skill_text(rec)
                    if is_main:
                        self._on_user(rec, state)

    def _track_meta(self, rec):
        if rec.get("type") == "ai-title" and rec.get("aiTitle"):
            self.meta["title"] = rec["aiTitle"]
        ts = rec.get("timestamp")
        if ts:
            self.meta["first_ts"] = min(ts, self.meta["first_ts"] or ts)
            self.meta["last_ts"] = max(ts, self.meta["last_ts"] or ts)
        self.meta["version"] = rec.get("version") or self.meta["version"]
        self.meta["cwd"] = self.meta["cwd"] or rec.get("cwd")

    def _on_user(self, rec, state):
        if not _is_human_prompt(rec):
            return
        match = COMMAND_RE.search(_text(rec.get("message", {}).get("content")))
        command = match.group(1) if match else None
        if command in BUILTIN_COMMANDS:
            return
        state["prompt_idx"] += 1
        self.meta["prompts"] += 1
        self.prompts.append((state["prompt_idx"], rec.get("timestamp"), _prompt_text(rec, command)))
        state["skill"] = None
        if command:
            self._load_skill(command, "command", rec, None, state)
            args = COMMAND_ARGS_RE.search(_text(rec.get("message", {}).get("content")))
            self.skill_calls[-1]["args"] = args.group(1) if args else None

    def _on_command_skill_text(self, rec):
        """A typed /skill puts its SKILL.md in the next meta message; it belongs to the last command load."""
        if not rec.get("isMeta"):
            return
        text = _text((rec.get("message") or {}).get("content"))
        if not text.startswith(SKILL_TEXT):
            return
        load = next((c for c in reversed(self.skill_calls) if c["source"] == "command"), None)
        if load is not None and "text" not in load:
            load["text"] = text

    def _on_tool_results(self, rec):
        content = (rec.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id"):
                self.result_chars[block["tool_use_id"]] = len(_text(block.get("content")))

    def _on_skill_blob(self, line):
        try:
            content = (json.loads(line).get("message") or {}).get("content")
        except json.JSONDecodeError:
            return
        content = content if isinstance(content, list) else []
        # the skill text follows the Skill call's tool_result in the same message
        for prev, block in zip(content, content[1:]):
            if (isinstance(block, dict) and block.get("type") == "text" and isinstance(prev, dict)
                    and prev.get("type") == "tool_result" and block.get("text", "").startswith(SKILL_TEXT)):
                self.skill_texts[prev.get("tool_use_id")] = block["text"]

    def _load_skill(self, skill, source, rec, agent_id, state, tool_use_id=None):
        skill = canonical_name(skill, self.meta["cwd"] or rec.get("cwd"))
        state["skill"] = skill
        state["phase"] = phase_of(skill, self.phases)
        self.skill_calls.append({
            "ts": rec.get("timestamp"), "skill": skill, "phase": state["phase"], "source": source,
            "agent_id": agent_id, "prompt_idx": state["prompt_idx"], "tool_use_id": tool_use_id,
        })

    def _on_assistant(self, rec, agent_id, agent_type, state):
        msg = rec.get("message") or {}
        usage = msg.get("usage")
        model = msg.get("model") or ""
        key = rec.get("requestId") or msg.get("id") or rec.get("uuid")
        if usage and model != "<synthetic>" and key:
            fields = _usage_fields(usage)
            row = self.requests.get(key)
            if row is None:
                # attribution is fixed at the request's first line, before any Skill call it makes loads
                self.requests[key] = {
                    "request_key": key, "ts": rec.get("timestamp"), "model": model, "agent_id": agent_id,
                    "agent_type": agent_type, "prompt_idx": state["prompt_idx"], "skill": state["skill"],
                    "phase": state["phase"], **fields,
                }
            else:
                for name, value in fields.items():
                    row[name] = max(row[name], value)
        for block in msg.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            self.tool_ctx[block.get("id")] = (state["prompt_idx"], state["skill"], state["phase"], agent_id)
            self.tool_calls[block.get("id")] = (state["prompt_idx"], agent_id, block.get("name"))
            if block.get("name") == "Skill":
                skill = (block.get("input") or {}).get("skill")
                self.skill_args[block.get("id")] = (block.get("input") or {}).get("args")
                if skill:
                    self._load_skill(skill, "tool", rec, agent_id, state, block.get("id"))


def session_signature(main_path):
    parts = [main_path.stat()]
    sub_dir = main_path.with_suffix("") / "subagents"
    if sub_dir.is_dir():
        parts += [p.stat() for p in sub_dir.iterdir()]
    return f"v{PARSER_VERSION}:{len(parts)}:{sum(s.st_size for s in parts)}:{max(s.st_mtime_ns for s in parts)}"


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    if "result_chars" not in {c[1] for c in conn.execute("PRAGMA table_info(tool_calls)")}:
        conn.execute("ALTER TABLE tool_calls ADD COLUMN result_chars INTEGER")  # refilled by the PARSER_VERSION bump
    if "tool_use_id" not in {c[1] for c in conn.execute("PRAGMA table_info(skill_calls)")}:
        conn.execute("ALTER TABLE skill_calls ADD COLUMN tool_use_id TEXT")  # joins a load to its version mark
    if "text_hash" not in {c[1] for c in conn.execute("PRAGMA table_info(skill_calls)")}:
        conn.execute("ALTER TABLE skill_calls ADD COLUMN text_hash TEXT")  # the SKILL.md text that load put in the context
    return conn


def _load_text_hash(parser, call):
    """The kept SKILL.md of one load: a typed command's meta message, or the request blob after a Skill call."""
    if call.get("text"):
        return loaded_text_hash(call["text"], call.get("args"))
    tid = call["tool_use_id"]
    return loaded_text_hash(parser.skill_texts[tid], parser.skill_args.get(tid)) if tid in parser.skill_texts else None


def store(conn, project, parser, signature):
    sid = parser.session_id
    for table in TABLES:
        conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (sid,))
    m = parser.meta
    conn.execute(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?)",
        (sid, project, m["cwd"], m["title"], m["version"], m["first_ts"], m["last_ts"], m["prompts"], signature),
    )
    conn.executemany(
        "INSERT INTO requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (sid, r["request_key"], r["ts"], r["model"], r["agent_id"], r["agent_type"], r["prompt_idx"], r["skill"],
             r["phase"], r["input"], r["output"], r["thinking"], r["cache_read"], r["cache_write_5m"],
             r["cache_write_1h"],
             cost_usd(r["model"], r["input"], r["output"], r["cache_read"], r["cache_write_5m"], r["cache_write_1h"]))
            for r in parser.requests.values()
        ],
    )
    conn.executemany(
        "INSERT INTO subagents VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            (sid, a["agent_id"], a["agent_type"], a["description"], a["tool_use_id"], a["spawn_depth"],
             a["parent_agent_id"], a["prompt_idx"], a["skill"], a["phase"])
            for a in parser.subagents
        ],
    )
    conn.executemany("INSERT INTO tool_calls VALUES (?,?,?,?,?,?)",
                     [(sid, tid, i, agent, name, parser.result_chars.get(tid))
                      for tid, (i, agent, name) in parser.tool_calls.items() if tid])
    conn.executemany("INSERT INTO prompts VALUES (?,?,?,?)", [(sid, i, ts, text) for i, ts, text in parser.prompts])
    conn.executemany(
        "INSERT INTO skill_calls (session_id, ts, skill, phase, source, agent_id, prompt_idx, tool_use_id, text_hash) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        [(sid, c["ts"], c["skill"], c["phase"], c["source"], c["agent_id"], c["prompt_idx"], c["tool_use_id"],
          _load_text_hash(parser, c)) for c in parser.skill_calls],
    )


def ingest_session(db_path, phases_path, session_id, projects_dir=PROJECTS_DIR):
    """Re-parse one session wherever its transcript lives; returns False when no transcript is found."""
    matches = sorted(Path(projects_dir).glob(f"*/{session_id}.jsonl"))
    if not matches:
        return False
    main_path = matches[0]
    conn = connect(db_path)
    store(conn, main_path.parent.name, SessionParser(main_path, load_phases(phases_path)).parse(),
          session_signature(main_path))
    conn.commit()
    conn.close()
    return True


def ingest(db_path, phases_path, projects_dir=PROJECTS_DIR, project_filter=None, log=print):
    phases = load_phases(phases_path)
    conn = connect(db_path)
    known = dict(conn.execute("SELECT session_id, signature FROM sessions"))
    parsed = skipped = 0
    for project_dir in sorted(Path(projects_dir).iterdir()):
        if not project_dir.is_dir() or (project_filter and project_filter not in project_dir.name):
            continue
        for main_path in sorted(project_dir.glob("*.jsonl")):
            signature = session_signature(main_path)
            if known.get(main_path.stem) == signature:
                skipped += 1
                continue
            parser = SessionParser(main_path, phases).parse()
            store(conn, project_dir.name, parser, signature)
            conn.commit()
            parsed += 1
    log(f"ingest: {parsed} sessions parsed, {skipped} unchanged")
    from .skills import scan  # a skill edited since the last ingest shows up as a new version

    scan(conn)
    conn.close()
    return parsed, skipped
