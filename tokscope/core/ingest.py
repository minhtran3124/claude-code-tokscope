"""Parse Claude Code transcripts into SQLite, attributing each API request to a skill, subagent and phase.

Attribution rules:
- A request is counted once per requestId (streamed responses repeat the same usage on several lines).
- skill: the last skill loaded in the current human prompt (Skill tool call or typed /command); reset on the
  next human prompt. Matches how OTel stamps skill.name.
- phase: derived from the last skill loaded in the session (phases.json); carries across prompts. A request
  whose prompt loaded no skill (skill NULL) holds a carried phase: see CARRIED.
- A subagent inherits prompt/skill/phase from the request whose tool call spawned it.
- A headless session (`claude -p`) started from another session's Bash call gets that session as its parent: see
  link_sessions.
"""

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

from .. import paths
from . import tz
from .pricing import cost_usd, refresh_costs
from .skills import canonical_name, loaded_text_hash

# a phase inherited from an earlier prompt: no skill ran in this request's prompt (follow-ups like "ok, continue")
CARRIED = "(r.skill IS NULL AND r.phase IS NOT NULL)"
COMMAND_RE = re.compile(r"<command-name>/?([^<\s]+)</command-name>")
COMMAND_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)
# a failed tool result's class, first match wins (an MCP tool's failure is "mcp" whatever its text says)
ERROR_CLASSES = (
    ("edit_mismatch", re.compile(r"string to replace not found|old_string|did not match|not unique|found \d+ matches", re.I)),
    ("permission", re.compile(r"permission|access denied|was denied|doesn't want to proceed|not allowed|rejected", re.I)),
    ("timeout", re.compile(r"timed? ?out", re.I)),
    ("not_found", re.compile(r"does not exist|no such file|not found|enoent", re.I)),
    ("exit_code", re.compile(r"^\s*exit code \d+", re.I)),
)


def error_class(name, text):
    """Class of a failed tool result: mcp, edit_mismatch, permission, timeout, not_found, exit_code or other."""
    if (name or "").startswith("mcp__"):
        return "mcp"
    return next((c for c, rx in ERROR_CLASSES if rx.search(text)), "other")


def _input_hash(inp):
    return hashlib.sha1(json.dumps(inp, sort_keys=True, default=str).encode()).hexdigest()[:12]


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
    first_ts TEXT, last_ts TEXT, prompts INTEGER, signature TEXT, entrypoint TEXT, parent_session_id TEXT,
    first_req_ts TEXT
);
CREATE TABLE IF NOT EXISTS requests (
    session_id TEXT, request_key TEXT, ts TEXT, model TEXT, agent_id TEXT, agent_type TEXT,
    prompt_idx INTEGER, skill TEXT, phase TEXT,
    input INTEGER, output INTEGER, thinking INTEGER, cache_read INTEGER,
    cache_write_5m INTEGER, cache_write_1h INTEGER, cost_usd REAL,
    web_search_requests INTEGER, web_fetch_requests INTEGER, speed TEXT, inference_geo TEXT,
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
    session_id TEXT, tool_use_id TEXT, prompt_idx INTEGER, agent_id TEXT, name TEXT, result_chars INTEGER,
    is_error INTEGER, err_class TEXT, repeat INTEGER, skill TEXT, phase TEXT, ts TEXT, model TEXT,
    PRIMARY KEY (session_id, tool_use_id)
);
CREATE TABLE IF NOT EXISTS turn_events (
    session_id TEXT, ts TEXT, prompt_idx INTEGER, agent_id TEXT, skill TEXT, phase TEXT, kind TEXT
);
CREATE TABLE IF NOT EXISTS headless_calls (
    session_id TEXT, tool_use_id TEXT, cwds TEXT, start_ts TEXT, end_ts TEXT, child_ids TEXT,
    PRIMARY KEY (session_id, tool_use_id)
);
CREATE TABLE IF NOT EXISTS mcp_defs (
    session_id TEXT, server TEXT, tools INTEGER, chars INTEGER, PRIMARY KEY (session_id, server)
);
CREATE TABLE IF NOT EXISTS ingest_state (session_id TEXT PRIMARY KEY, state TEXT);
CREATE INDEX IF NOT EXISTS idx_requests_ts ON requests (ts);
"""
TABLES = ("requests", "subagents", "skill_calls", "prompts", "tool_calls", "turn_events", "headless_calls", "mcp_defs", "ingest_state", "sessions")
# bump when the parser records something new, so unchanged transcripts are parsed again once
PARSER_VERSION = 19
TAIL_BYTES = 4096  # the bytes before a stored offset that must be unchanged for a file to count as appended to
# what a resumed parse restores: the parser's state after the last complete line of every file
STATE_KEYS = ("requests", "subagents", "skill_calls", "prompts", "tool_ctx", "tool_calls", "result_chars",
              "skill_texts", "skill_args", "headless", "mcp_defs", "meta", "files", "tool_err", "seen_calls", "events")
ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
PROMPT_CHARS = 160
# a Bash command that starts a headless Claude Code session
HEADLESS_RE = re.compile(r"(?:^|[\s;&|(/])claude(?:\s[^;&|\n]*)?\s(?:-p|--print)(?=\s|$)")
# text a command only passes along (a commit message, a PR body): quoted strings and heredoc bodies
QUOTED_RE = re.compile(r"""'[^']*'|"(?:[^"\\]|\\.)*"|`[^`]*`""")
# group 1: the file a heredoc is written to (`cat > run.sh <<'EOF'`), group 4: its body
HEREDOC_RE = re.compile(r"""(?:>\s*(\S+)\s*)?<<-?\s*(['"]?)(\w+)\2[^\n]*\n(.*?)^\s*\3\s*$""", re.S | re.M)
# a background call's end: the task notification that names its tool call
TASK_DONE_RE = re.compile(r"<tool-use-id>([^<]+)</tool-use-id>(?:(?!</task-notification>).)*?<status>(?!running)[^<]*</status>",
                          re.S)


def is_headless(command):
    """True when a Bash command runs `claude -p` itself, not when it only quotes the words. A heredoc body counts
    when the command writes it to a file and names that file again (`cat > run.sh <<'EOF' ... EOF; bash run.sh`)."""
    scripts = []

    def drop(m):
        if m.group(1) and is_headless(m.group(4)):
            scripts.append(m.group(1))
        return ""
    rest = HEREDOC_RE.sub(drop, command)
    return bool(HEADLESS_RE.search(QUOTED_RE.sub("''", rest))) or any(path in rest for path in scripts)


SESSION_ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
ASSIGN_RE = re.compile(r"""(?:^|[\s;&|(])(\w+)=["']?([^\s"';&|)]+)""")
PATH_RE = re.compile(r"""(?:^|[\s=;&|("'])((?:~|/)[^\s"';&|)]*)""")


def _shell_word(m):
    """A quoted string as `command_dirs` reads it: a backtick command keeps its words, a path keeps its text (spaces
    held as NUL so it stays one word), other text with spaces is prompt text and goes, a bare word loses its quotes."""
    body = m.group(0)[1:-1]
    if m.group(0)[0] == "`":
        return " " + body + " "
    if re.match(r"[/~$]", body):
        return body.replace(" ", "\0")
    return "''" if re.search(r"\s", body) else body


def command_dirs(command, cwd):
    """The folders a Bash command may start `claude -p` in: its own cwd and every absolute path it names as a shell
    word (`cd /x && claude -p`, `cd "/a b"`, `cd $'/x'`, `` cd `pwd` ``), with simple `X=/path` variables filled in. A
    path inside prompt text (a quoted string that does not start with a path, a heredoc body) is not a folder the
    command runs in; a heredoc script written to a file, run later, that runs `claude -p` is, as in `is_headless`."""
    rest = HEREDOC_RE.sub("", command)
    command = HEREDOC_RE.sub(lambda m: "\n" + m.group(4) if m.group(1) and m.group(1) in rest
                             and is_headless(m.group(4)) else "", command)
    command = QUOTED_RE.sub(_shell_word, command)
    command = re.sub(r"\$(?=[/~])", "", command)  # what is left of $'/x'
    for name, value in ASSIGN_RE.findall(command):
        command = command.replace("${" + name + "}", value).replace("$" + name, value)
    dirs = {os.path.expanduser(p.replace("\0", " ")).rstrip("/") or "/" for p in PATH_RE.findall(command)}
    return "\n".join(sorted(dirs | ({cwd} if cwd else set())))


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


def _is_interrupt(rec):
    """The line Claude Code writes when the person presses Esc."""
    return _text(rec.get("message", {}).get("content")).lstrip().startswith("[Request interrupted")


def _is_human_prompt(rec):
    if rec.get("isMeta") or "toolUseResult" in rec:
        return False
    content = rec.get("message", {}).get("content")
    if isinstance(content, list) and content and isinstance(content[0], dict) and content[0].get("type") == "tool_result":
        return False
    # Claude Code writes this line itself when the person presses Esc; it is not something they typed
    if _is_interrupt(rec):
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
        "web_search_requests": (usage.get("server_tool_use") or {}).get("web_search_requests") or 0,
        "web_fetch_requests": (usage.get("server_tool_use") or {}).get("web_fetch_requests") or 0,
        "speed": usage.get("speed"),
        "inference_geo": usage.get("inference_geo"),
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
        self.tool_err = {}  # tool_use_id -> error class, for the results that failed
        self.seen_calls = {}  # "prompt|agent|name|input hash" -> 1: the calls a later identical one repeats
        self.events = []  # [ts, prompt_idx, agent_id, skill, phase, kind]: interrupt, api_error, retry or compact
        self.result_chars = {}  # tool_use_id -> text size of the result that went into the context
        self.skill_texts = {}  # Skill tool_use_id -> the SKILL.md text it loaded, where a request blob kept it
        self.skill_args = {}  # Skill tool_use_id -> the args the call passed
        self.headless = {}  # Bash tool_use_id that ran `claude -p` -> {cwd, start_ts, end_ts, child_ids}
        self.mcp_defs = None  # server -> [tools, chars] of the MCP tool definitions in the first main-thread shape; None: no shape yet
        self.meta = {"title": None, "version": None, "cwd": None, "first_ts": None, "last_ts": None, "prompts": 0,
                     "entrypoint": None}
        self.files = {}  # file name ("" = main) -> {ino, off, tail, state, unresolved}: where the next parse resumes
        self.lines_read = 0
        self._f = [0, ""]  # sort key of the file being read: a resumed parse keeps full-parse row order

    def dump(self):
        return json.dumps({"v": PARSER_VERSION, **{k: getattr(self, k) for k in STATE_KEYS}})

    def _valid(self, prev):
        """True when every file only grew since `prev`: same inode, not shorter, the bytes before the offset the same."""
        if prev.get("v") != PARSER_VERSION:
            return False
        sub_dir = self.main_path.with_suffix("") / "subagents"
        for rel, info in prev["files"].items():
            if info.get("unresolved"):
                return False  # its spawning call was not seen yet; a full parse may find it
            path = sub_dir / rel if rel else self.main_path
            st = path.stat()
            if st.st_ino != info["ino"] or st.st_size < info["off"]:
                return False
            if _tail_hash(path, info["off"]) != info["tail"]:
                return False
        return True

    def parse(self, prev=None):
        """Read the session. With `prev` (the dump of an earlier parse) read only the lines appended since, when the
        files only grew; else read everything."""
        try:
            ok = bool(prev) and self._valid(prev)
        except (KeyError, TypeError, ValueError, OSError):
            ok = False
        if ok:
            for k in STATE_KEYS:
                setattr(self, k, prev[k])
        self._f = [0, ""]
        main = self.files.get("")
        self._walk(self.main_path, "", None, None, main["state"] if main else {"prompt_idx": 0, "skill": None, "phase": None})
        sub_dir = self.main_path.with_suffix("") / "subagents"
        agents = []
        for path in sub_dir.glob("agent-*.jsonl") if sub_dir.is_dir() else []:
            meta_path = path.with_suffix(".meta.json")
            meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
            agents.append((meta.get("spawnDepth") or 1, path, meta))
        # parents before children so a nested agent finds its spawning tool call
        for depth, path, meta in sorted(agents, key=lambda a: (a[0], a[1].name)):
            agent_id = path.stem.removeprefix("agent-")
            agent_type = meta.get("agentType") or "unknown"
            self._f = [depth, path.name]
            known = self.files.get(path.name)
            if known:
                state = known["state"]
            else:
                prompt_idx, skill, phase, parent = self.tool_ctx.get(meta.get("toolUseId"), (None, None, None, None))
                self.subagents.append({
                    "agent_id": agent_id, "agent_type": agent_type, "description": meta.get("description"),
                    "tool_use_id": meta.get("toolUseId"), "spawn_depth": depth, "parent_agent_id": parent,
                    "prompt_idx": prompt_idx, "skill": skill, "phase": phase,
                })
                state = {"prompt_idx": prompt_idx, "skill": skill, "phase": phase}
            self._walk(path, path.name, agent_id, agent_type, state, unresolved=not known and prompt_idx is None)
        self.subagents.sort(key=lambda a: (a["spawn_depth"], a["agent_id"]))
        self.skill_calls.sort(key=lambda c: tuple(c["_f"]))
        return self

    def _walk(self, path, rel, agent_id, agent_type, state, unresolved=False):
        is_main = agent_id is None
        info = self.files.get(rel) or {"off": 0}
        with open(path, "rb") as f:
            f.seek(info["off"])
            data = f.read()
            ino = os.fstat(f.fileno()).st_ino
            end = data.rfind(b"\n") + 1
            try:  # a last line without its newline counts when it is complete
                if data[end:].strip():
                    json.loads(data[end:])
                    end = len(data)
            except ValueError:
                pass
            off = info["off"] + end
            self.files[rel] = {"ino": ino, "off": off, "tail": _tail_hash(f, off), "state": state,
                               "unresolved": unresolved or info.get("unresolved", False)}
            for raw in data[:end].split(b"\n"):
                if not raw.strip():
                    continue
                self.lines_read += 1
                line = raw.decode("utf-8", errors="replace")
                # request blobs and shapes are large and carry no usage; a blob can hold the skill text a load put in
                if '"api-request-blob"' in line[:40] and SKILL_TEXT in line:
                    self._on_skill_blob(line)
                    continue
                if is_main and self.mcp_defs is None and line.startswith('{"type":"api-request-shape"'):
                    self._on_shape(line)
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
                self._on_events(rec, agent_id, state)
                if kind == "assistant":
                    self._on_assistant(rec, agent_id, agent_type, state)
                elif kind == "user":
                    self._on_tool_results(rec)
                    self._on_task_done(rec)
                    self._on_command_skill_text(rec, agent_id)
                    if is_main:
                        self._on_user(rec, state)

    def _on_shape(self, line):
        """The MCP tools the session sent in its first request, by server. A tool with defer_loading is not in the prefix
        (only its name is), so it adds nothing. Size is the JSON of the definition, a rough stand-in for its tokens."""
        try:
            tools = json.loads(line)["shape"]["tools"]
        except (ValueError, KeyError, TypeError):
            return
        defs = {}
        for tool in tools if isinstance(tools, list) else []:
            name = tool.get("name") if isinstance(tool, dict) else None
            if not isinstance(name, str) or not name.startswith("mcp__") or name.count("__") < 2 or tool.get("defer_loading"):
                continue
            d = defs.setdefault(name.split("__")[1], [0, 0])
            d[0] += 1
            d[1] += len(json.dumps(tool, ensure_ascii=False))
        self.mcp_defs = defs

    def _track_meta(self, rec):
        if rec.get("type") == "ai-title" and rec.get("aiTitle"):
            self.meta["title"] = rec["aiTitle"]
        ts = rec.get("timestamp")
        if ts:
            self.meta["first_ts"] = min(ts, self.meta["first_ts"] or ts)
            self.meta["last_ts"] = max(ts, self.meta["last_ts"] or ts)
        self.meta["version"] = rec.get("version") or self.meta["version"]
        self.meta["cwd"] = self.meta["cwd"] or rec.get("cwd")
        self.meta["entrypoint"] = self.meta["entrypoint"] or rec.get("entrypoint")

    def _event(self, rec, agent_id, state, kind):
        self.events.append([rec.get("timestamp"), state["prompt_idx"], agent_id, state["skill"], state["phase"], kind])

    def _on_events(self, rec, agent_id, state):
        """What went wrong outside a tool call: the person's Esc, an API error message, an API retry."""
        kind = rec.get("type")
        if kind == "system" and rec.get("subtype") == "api_error":
            self._event(rec, agent_id, state, "retry")
        elif kind == "system" and rec.get("subtype") == "compact_boundary":  # /compact or auto-compact
            self._event(rec, agent_id, state, "compact")
        elif kind == "assistant" and (rec.get("isApiErrorMessage") or rec.get("apiError")):
            self._event(rec, agent_id, state, "api_error")
        elif kind == "user" and _is_interrupt(rec):
            self._event(rec, agent_id, state, "interrupt")

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

    def _on_command_skill_text(self, rec, agent_id=None):
        """A typed /skill puts its SKILL.md in the next meta message; it belongs to the last command load. A message
        with a sourceToolUseID belongs to that Skill tool call, and one in a subagent file to no main-thread command."""
        if not rec.get("isMeta"):
            return
        text = _text((rec.get("message") or {}).get("content"))
        if not text.startswith(SKILL_TEXT):
            return
        tid = rec.get("sourceToolUseID")
        if tid:
            self.skill_texts.setdefault(tid, text)
            return
        if agent_id is not None:
            return
        load = next((c for c in reversed(self.skill_calls) if c["source"] == "command"), None)
        if load is not None and "text" not in load:
            load["text"] = text

    def _on_tool_results(self, rec):
        content = (rec.get("message") or {}).get("content")
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("tool_use_id"):
                self.result_chars[block["tool_use_id"]] = len(_text(block.get("content")))
                if block.get("is_error"):
                    call = self.tool_calls.get(block["tool_use_id"])
                    self.tool_err[block["tool_use_id"]] = error_class(call[2] if call else None, _text(block.get("content")))
                call = self.headless.get(block["tool_use_id"])
                if call is not None:
                    # a background run returns at once; its end is the task notification (_on_task_done)
                    call["end_ts"] = None if call["background"] else rec.get("timestamp")
                    call["child_ids"] = " ".join(dict.fromkeys(SESSION_ID_RE.findall(_text(block.get("content")))))

    def _on_task_done(self, rec):
        content = (rec.get("message") or {}).get("content")
        text = _text(content) if "<task-notification>" in str(content) else ""
        for tid in TASK_DONE_RE.findall(text):
            call = self.headless.get(tid)
            if call is not None and call["background"] and call["end_ts"] is None:
                call["end_ts"] = rec.get("timestamp")

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
            "agent_id": agent_id, "prompt_idx": state["prompt_idx"], "tool_use_id": tool_use_id, "_f": self._f,
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
                    row[name] = max(row[name], value) if isinstance(value, int) else value or row[name]
        for block in msg.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            self.tool_ctx[block.get("id")] = (state["prompt_idx"], state["skill"], state["phase"], agent_id)
            if block.get("id") not in self.tool_calls:  # a line repeated by a resumed or forked file is not a repeat call
                key = f'{state["prompt_idx"]}|{agent_id}|{block.get("name")}|{_input_hash(block.get("input"))}'
                self.tool_calls[block.get("id")] = (state["prompt_idx"], agent_id, block.get("name"), state["skill"],
                                                    state["phase"], rec.get("timestamp"), int(key in self.seen_calls), msg.get("model"))
                self.seen_calls[key] = 1
            command = (block.get("input") or {}).get("command")
            if block.get("name") == "Bash" and isinstance(command, str) and is_headless(command):
                self.headless[block.get("id")] = {"cwds": command_dirs(command, rec.get("cwd") or self.meta["cwd"]),
                                                  "start_ts": rec.get("timestamp"),
                                                  "end_ts": None, "child_ids": "",
                                                  "background": bool((block.get("input") or {}).get("run_in_background"))}
            if block.get("name") == "Skill":
                skill = (block.get("input") or {}).get("skill")
                self.skill_args[block.get("id")] = (block.get("input") or {}).get("args")
                if skill:
                    self._load_skill(skill, "tool", rec, agent_id, state, block.get("id"))


def _tail_hash(src, off):
    """Hash of the TAIL_BYTES before `off` in a path or an open binary file."""
    def read(f):
        f.seek(max(0, off - TAIL_BYTES))
        return hashlib.sha1(f.read(min(off, TAIL_BYTES))).hexdigest()
    if hasattr(src, "seek"):
        return read(src)
    with open(src, "rb") as f:
        return read(f)


def parse_session(conn, main_path, phases):
    """Parse a session, resuming from the state stored by its last ingest when its files only grew."""
    parser = SessionParser(main_path, phases)
    row = conn.execute("SELECT state FROM ingest_state WHERE session_id = ?", (parser.session_id,)).fetchone()
    try:
        prev = json.loads(row[0]) if row else None
    except ValueError:
        prev = None
    return parser.parse(prev)


def session_signature(main_path):
    parts = [main_path.stat()]
    sub_dir = main_path.with_suffix("") / "subagents"
    if sub_dir.is_dir():
        parts += [p.stat() for p in sub_dir.iterdir()]
    return f"v{PARSER_VERSION}:{len(parts)}:{sum(s.st_size for s in parts)}:{max(s.st_mtime_ns for s in parts)}"


def open_db(db_path):
    """The one way to open the database file: several processes write it, so WAL and a 10 s wait on a lock."""
    conn = tz.register(sqlite3.connect(db_path, timeout=10))
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def connect(db_path):
    conn = open_db(db_path)
    conn.executescript(SCHEMA)
    have = {c[1] for c in conn.execute("PRAGMA table_info(tool_calls)")}
    for name, typ in (("result_chars", "INTEGER"), ("is_error", "INTEGER"), ("err_class", "TEXT"), ("repeat", "INTEGER"),
                      ("skill", "TEXT"), ("phase", "TEXT"), ("ts", "TEXT"), ("model", "TEXT")):  # refilled by the PARSER_VERSION bump
        if name not in have:
            conn.execute(f"ALTER TABLE tool_calls ADD COLUMN {name} {typ}")
    if "tool_use_id" not in {c[1] for c in conn.execute("PRAGMA table_info(skill_calls)")}:
        conn.execute("ALTER TABLE skill_calls ADD COLUMN tool_use_id TEXT")  # joins a load to its version mark
    if "text_hash" not in {c[1] for c in conn.execute("PRAGMA table_info(skill_calls)")}:
        conn.execute("ALTER TABLE skill_calls ADD COLUMN text_hash TEXT")  # the SKILL.md text that load put in the context
    have = {c[1] for c in conn.execute("PRAGMA table_info(requests)")}
    for name, typ in (("web_search_requests", "INTEGER"), ("web_fetch_requests", "INTEGER"), ("speed", "TEXT"),
                      ("inference_geo", "TEXT")):  # refilled by the PARSER_VERSION bump
        if name not in have:
            conn.execute(f"ALTER TABLE requests ADD COLUMN {name} {typ}")
    refresh_costs(conn)
    columns = {c[1] for c in conn.execute("PRAGMA table_info(sessions)")}
    for name in ("entrypoint", "parent_session_id", "first_req_ts"):  # refilled by the PARSER_VERSION bump (not parent_session_id)
        if name not in columns:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} TEXT")
    return conn


def link_sessions(conn):
    """Set each headless session's parent: the session whose Bash call ran the `claude -p` that started it.

    The child's transcript does not name its parent, so the link comes from the parent's side. First choice: the
    call's result names the child's session id (`--output-format json` prints it). Else: the child started while the
    call ran (a background call until its task notification; with none, it has no window), in a folder the call names (its cwd or a path in the
    command) or in the calling session's own folder (a scratchpad path holds its session id). A call whose result
    named a session that started while it ran (its JSON child) gets no window: another run in that folder at that
    time is not its child. An id it only lists (`ls`, an older session) does not count. The call must start before
    the child; of several, the latest wins. A session that no call matches keeps no parent.

    Limit: two sessions that run `claude -p` at the same time in the same folder can swap children when the output is
    not JSON, because the latest call wins. `--output-format json` names the child's id and avoids it."""
    calls = conn.execute(
        "SELECT session_id, cwds, start_ts, end_ts, child_ids FROM headless_calls WHERE start_ts IS NOT NULL").fetchall()
    headless = conn.execute(
        "SELECT session_id, cwd, first_ts FROM sessions WHERE entrypoint LIKE 'sdk%' AND first_ts IS NOT NULL").fetchall()
    started = {h[0]: h[2] for h in headless}

    def named_a_child(c):
        return any(c[2] <= started[i] <= (c[3] or started[i]) for i in (c[4] or "").split() if i in started)
    links = []
    for sid, cwd, first_ts in headless:
        before = [c for c in calls if c[0] != sid and c[2] <= first_ts]
        found = ([c for c in before if sid in (c[4] or "").split()]
                 or [c for c in before if c[3] and first_ts <= c[3] and not named_a_child(c)
                     and (cwd in (c[1] or "").split("\n") or c[0] in (cwd or ""))])
        if found:
            links.append((max(found, key=lambda c: c[2])[0], sid))
    want = {sid: parent for parent, sid in links}
    have = dict(conn.execute("SELECT session_id, parent_session_id FROM sessions WHERE parent_session_id IS NOT NULL"))
    # write only the rows whose parent changed
    conn.executemany("UPDATE sessions SET parent_session_id = ? WHERE session_id = ?",
                     [(want.get(sid), sid) for sid in have.keys() | want.keys() if have.get(sid) != want.get(sid)])
    return len(links)


def _load_text_hash(parser, call):
    """The kept SKILL.md of one load: a typed command's meta message, or the request blob after a Skill call."""
    if call.get("text"):
        return loaded_text_hash(call["text"], call.get("args"))
    tid = call["tool_use_id"]
    return loaded_text_hash(parser.skill_texts[tid], parser.skill_args.get(tid)) if tid in parser.skill_texts else None


def _share_requests(conn, parser):
    """A fork copies earlier requests into a new transcript (issue #46); keep each with one session, the one that
    sorts first by (first_ts, id): both are fixed once written, so a later resume cannot move the owner."""
    sid, m = parser.session_id, parser.meta
    mine = (m["first_ts"] or "", sid)
    keys = list(parser.requests)
    for i in range(0, len(keys), 500):
        chunk = keys[i:i + 500]
        marks = ",".join("?" * len(chunk))
        for key, other, first in conn.execute(
                f"SELECT r.request_key, r.session_id, s.first_ts FROM requests r "
                f"JOIN sessions s USING (session_id) WHERE r.session_id != ? AND r.request_key IN ({marks})",
                (sid, *chunk)).fetchall():
            if (first or "", other) <= mine:
                parser.requests.pop(key, None)
            else:
                conn.execute("DELETE FROM requests WHERE session_id = ? AND request_key = ?", (other, key))


def store(conn, project, parser, signature):
    sid = parser.session_id
    for table in TABLES:
        conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (sid,))
    # the first main-thread request as the transcript has it, before a fork's copies move to the session that owns them
    first_req = min((r["ts"] for r in parser.requests.values() if not r["agent_id"] and r["ts"]), default=None)
    _share_requests(conn, parser)
    m = parser.meta
    conn.execute(
        "INSERT INTO sessions (session_id, project, cwd, title, version, first_ts, last_ts, prompts, signature, entrypoint, "
        "first_req_ts) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (sid, project, m["cwd"], m["title"], m["version"], m["first_ts"], m["last_ts"], m["prompts"], signature,
         m["entrypoint"], first_req),
    )
    conn.execute("INSERT INTO ingest_state VALUES (?,?)", (sid, parser.dump()))
    conn.executemany("INSERT INTO headless_calls VALUES (?,?,?,?,?,?)",
                     [(sid, tid, c["cwds"], c["start_ts"], c["end_ts"], c["child_ids"])
                      for tid, c in parser.headless.items() if tid])
    conn.executemany(
        "INSERT INTO requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (sid, r["request_key"], r["ts"], r["model"], r["agent_id"], r["agent_type"], r["prompt_idx"], r["skill"],
             r["phase"], r["input"], r["output"], r["thinking"], r["cache_read"], r["cache_write_5m"],
             r["cache_write_1h"],
             cost_usd(r["model"], r["input"], r["output"], r["cache_read"], r["cache_write_5m"], r["cache_write_1h"],
                      r["speed"], r["inference_geo"], r["web_search_requests"]),
             r["web_search_requests"], r["web_fetch_requests"], r["speed"], r["inference_geo"])
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
    conn.executemany("INSERT INTO tool_calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     [(sid, tid, i, agent, name, parser.result_chars.get(tid), int(tid in parser.tool_err),
                       parser.tool_err.get(tid), dup, skill, phase, ts, model)
                      for tid, (i, agent, name, skill, phase, ts, dup, model) in parser.tool_calls.items() if tid])
    conn.executemany("INSERT INTO turn_events VALUES (?,?,?,?,?,?,?)",
                     [(sid, ts, i, agent, skill, phase, kind) for ts, i, agent, skill, phase, kind in parser.events])
    conn.executemany("INSERT INTO mcp_defs VALUES (?,?,?,?)",
                     [(sid, server, n, chars) for server, (n, chars) in (parser.mcp_defs or {}).items()])
    conn.executemany("INSERT INTO prompts VALUES (?,?,?,?)", [(sid, i, ts, text) for i, ts, text in parser.prompts])
    conn.executemany(
        "INSERT INTO skill_calls (session_id, ts, skill, phase, source, agent_id, prompt_idx, tool_use_id, text_hash) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        [(sid, c["ts"], c["skill"], c["phase"], c["source"], c["agent_id"], c["prompt_idx"], c["tool_use_id"],
          _load_text_hash(parser, c)) for c in parser.skill_calls],
    )


def find_transcripts(session_id, projects_dir=None):
    """Main transcripts of a session in the given folder(s) (None: the default ones), first folder first."""
    return [m for d in paths.projects_dirs(projects_dir) for m in sorted(d.glob(f"*/{session_id}.jsonl"))]


def ingest_session(db_path, phases_path, session_id, projects_dir=None):
    """Re-parse one session wherever its transcript lives; returns False when no transcript is found."""
    matches = find_transcripts(session_id, projects_dir)
    if not matches:
        return False
    main_path = matches[0]
    conn = connect(db_path)
    store(conn, main_path.parent.name, parse_session(conn, main_path, load_phases(phases_path)),
          session_signature(main_path))
    link_sessions(conn)
    conn.commit()
    conn.close()
    return True


def ingest(db_path, phases_path, projects_dir=None, project_filter=None, log=print):
    """projects_dir: one folder, a list, or None for the default ones. A session id found twice is read once."""
    dirs = [d for d in paths.projects_dirs(projects_dir) if d.is_dir()]
    if not dirs:
        log(f"ingest: no transcripts in {', '.join(map(str, paths.projects_dirs(projects_dir)))} yet")
        return 0, 0
    log("ingest: reading " + ", ".join(map(str, dirs)))
    phases = load_phases(phases_path)
    conn = connect(db_path)
    known = dict(conn.execute("SELECT session_id, signature FROM sessions"))
    parsed = skipped = 0
    seen = set()
    for project_dir in (p for d in dirs for p in sorted(d.iterdir())):
        if not project_dir.is_dir() or (project_filter and project_filter not in project_dir.name):
            continue
        for main_path in sorted(project_dir.glob("*.jsonl")):
            if main_path.stem in seen:
                continue
            seen.add(main_path.stem)
            signature = session_signature(main_path)
            if known.get(main_path.stem) == signature:
                skipped += 1
                continue
            parser = parse_session(conn, main_path, phases)
            store(conn, project_dir.name, parser, signature)
            conn.commit()
            parsed += 1
    # every run, so a run that stopped after storing sessions but before linking is repaired by the next; when the
    # links are already right it only reads
    link_sessions(conn)
    conn.commit()
    log(f"ingest: {parsed} sessions parsed, {skipped} unchanged")
    from .skills import scan  # a skill edited since the last ingest shows up as a new version

    scan(conn)
    conn.close()
    return parsed, skipped
