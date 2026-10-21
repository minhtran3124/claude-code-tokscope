"""Redacted copies of the database, for a report that will leave the machine.

The report is built from a copy that never held the private text, so nothing the report code does can leak it.
Every column of every table is classified below; a column that is not (a new one) is emptied, and a table that
is not is cleared. tests/test_privacy.py fails when a table gains a column this file does not know.

  full      everything (the default, for looking at your own data)
  redacted  numbers and names; prompts, titles, descriptions, answers, notes, paths and projects are removed
  numbers   numbers only; skill, agent, tool, MCP, task and project names become stable aliases"""

import hashlib
import hmac
import json
import os
import re
import sqlite3

from . import paths
from .calls import mcp_server

LEVELS = ("full", "redacted", "numbers")

KEEP, DROP = "keep", "drop"
# content: replaced by "[label · N chars]" at both levels below full
PROMPT, DESC, ANSWER, NOTE, RESULT = "text:prompt", "text:description", "text:answer", "text:note", "text:result"
# names: kept at redacted, aliased at numbers
SKILL, AGENT, TOOL, PHASE, TASK, VARIANT = "name:skill", "name:agent", "name:tool", "name:phase", "name:task", "name:variant"
# special shapes
TITLE, PROJECT, CWD = "title", "project", "cwd"

COLUMNS = {
    "sessions": {"session_id": KEEP, "project": PROJECT, "cwd": CWD, "title": TITLE, "version": KEEP,
                 "first_ts": KEEP, "last_ts": KEEP, "prompts": KEEP, "signature": DROP, "entrypoint": KEEP,
                 "parent_session_id": KEEP},
    "requests": {"session_id": KEEP, "request_key": KEEP, "ts": KEEP, "model": KEEP, "agent_id": KEEP, "agent_type": AGENT,
                 "prompt_idx": KEEP, "skill": SKILL, "phase": PHASE, "input": KEEP, "output": KEEP, "thinking": KEEP,
                 "cache_read": KEEP, "cache_write_5m": KEEP, "cache_write_1h": KEEP, "cost_usd": KEEP},
    "subagents": {"session_id": KEEP, "agent_id": KEEP, "agent_type": AGENT, "description": DESC, "tool_use_id": KEEP,
                  "spawn_depth": KEEP, "parent_agent_id": KEEP, "prompt_idx": KEEP, "skill": SKILL, "phase": PHASE},
    "skill_calls": {"session_id": KEEP, "ts": KEEP, "skill": SKILL, "phase": PHASE, "source": KEEP, "agent_id": KEEP,
                    "prompt_idx": KEEP, "tool_use_id": KEEP, "text_hash": KEEP},
    "skill_versions": {"skill": SKILL, "version": KEEP, "path": CWD, "label": KEEP, "first_seen": KEEP, "last_seen": KEEP,
                       "source": KEEP, "body_hash": KEEP},
    "skill_load_versions": {"session_id": KEEP, "tool_use_id": KEEP, "skill": SKILL, "version": KEEP, "ts": KEEP},
    "prompts": {"session_id": KEEP, "prompt_idx": KEEP, "ts": KEEP, "text": PROMPT},
    "headless_calls": {"session_id": KEEP, "tool_use_id": KEEP, "cwds": DROP, "start_ts": KEEP, "end_ts": KEEP,
                       "child_ids": KEEP},
    "tool_calls": {"session_id": KEEP, "tool_use_id": KEEP, "prompt_idx": KEEP, "agent_id": KEEP, "name": TOOL,
                   "result_chars": KEEP},
    "bench_runs": {"run_id": KEEP, "task": TASK, "variant": VARIANT, "run_idx": KEEP, "session_id": KEEP,
                   "started_at": KEEP, "duration_s": KEEP, "exit_code": KEEP, "is_error": KEEP, "reported_cost": KEEP,
                   "passed": KEEP, "result": ANSWER, "commit_sha": DROP, "cc_version": KEEP,
                   "skill_check": KEEP},
    "replay_runs": {"run_id": KEEP, "source_session": KEEP, "run_idx": KEEP, "session_id": KEEP, "commit_sha": DROP,
                    "started_at": KEEP, "duration_s": KEEP, "turns": KEEP, "errors": KEEP, "denials": KEEP,
                    "reported_cost": KEEP, "status": KEEP, "variant": VARIANT, "skill_check": KEEP},
    "replay_turns": {"run_id": KEEP, "turn": KEEP, "prompt": PROMPT, "exit_code": KEEP, "is_error": KEEP, "denials": KEEP,
                     "duration_s": KEEP, "result": RESULT, "orig_idx": KEEP},
    "changes": {"id": KEEP, "at": KEEP, "note": NOTE, "agent_type": AGENT, "skill": SKILL},
    "sqlite_sequence": {"name": KEEP, "seq": KEEP},
}

# shipped with Claude Code, so naming them says nothing about the user's work
BUILTIN_AGENTS = {"general-purpose", "Explore", "Plan", "statusline-setup", "claude-code-guide", "output-style-setup"}
BUILTIN_TOOLS = {"Agent", "Task", "Bash", "BashOutput", "KillShell", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit",
                 "Glob", "Grep", "LS", "WebFetch", "WebSearch", "TodoWrite", "Skill", "ToolSearch", "AskUserQuestion",
                 "EnterPlanMode", "ExitPlanMode", "EnterWorktree", "ExitWorktree", "Monitor", "SendMessage", "LSP",
                 "ScheduleWakeup", "CronCreate", "CronDelete", "CronList", "Artifact", "ListMcpResourcesTool",
                 "ReadMcpResourceTool", "TaskStop", "Workflow"}
# a benchmark or replay project must stay recognisable, or the report would count it as real work (changes.BENCH_PROJECT)
BENCH = re.compile(r"tokscope.*-bench-")


def _key():
    """A per-machine secret, so an alias cannot be reversed by hashing a list of likely skill names."""
    path = paths.home() / "privacy.key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(os.urandom(32))
    return path.read_bytes()


class Redactor:
    def __init__(self, level, key=None, phase_names=None):
        if level not in LEVELS[1:]:
            raise ValueError(f"privacy level must be one of {', '.join(LEVELS[1:])}")
        self.level, self.key = level, key or _key()
        self.phase_names = phase_names if phase_names is not None else set(json.loads(paths.phases().read_text())) - {"_comment"}

    def alias(self, kind, value):
        digest = hmac.new(self.key, f"{kind}\0{value}".encode(), hashlib.sha256).hexdigest()
        return f"{kind}-{digest[:6]}"

    def name(self, kind, value):
        if value is None or self.level == "redacted":
            return value
        if kind == "agent" and value in BUILTIN_AGENTS or kind == "tool" and value in BUILTIN_TOOLS:
            return value
        if kind == "tool" and value.startswith("mcp__"):
            tool = value.split("__", 2)[-1] if value.count("__") >= 2 else ""
            return f"mcp__{self.alias('mcp', mcp_server(value))}__{self.alias('tool', tool)}"
        if kind == "phase":
            if value.startswith("other:"):
                return "other:" + self.name("skill", value.removeprefix("other:"))
            return value if value in self.phase_names or value == "unscoped" else self.alias("phase", value)
        return self.alias(kind, value)

    def text(self, label, value):
        return f"[{label} · {len(value)} chars]" if value else value

    def project(self, value):
        if not value:
            return value
        return ("tokscope-bench-" if BENCH.search(value) else "project-") + self.alias("p", value).split("-", 1)[1]

    def cwd(self, value):
        return "/" + self.project(value) if value else value

    def apply(self, conn):
        conn.create_function("tk_name", 2, self.name, deterministic=True)
        conn.create_function("tk_text", 2, self.text, deterministic=True)
        conn.create_function("tk_project", 1, self.project, deterministic=True)
        conn.create_function("tk_cwd", 1, self.cwd, deterministic=True)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            known = COLUMNS.get(table)
            if known is None:
                conn.execute(f'DELETE FROM "{table}"')
                continue
            sets = []
            for col in (r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')):
                kind = known.get(col, DROP)
                q = f'"{col}"'
                if kind == KEEP:
                    continue
                if kind == DROP:
                    sets.append(f"{q} = NULL")
                elif kind.startswith("text:"):
                    sets.append(f"{q} = tk_text('{kind[5:]}', {q})")
                elif kind.startswith("name:"):
                    sets.append(f"{q} = tk_name('{kind[5:]}', {q})")
                elif kind == TITLE:
                    # every session gets one, or the report would title an untitled one with its first prompt
                    sets.append(f"{q} = 'session ' || substr(session_id, 1, 8)")
                elif kind == PROJECT:
                    sets.append(f"{q} = tk_project({q})")
                elif kind == CWD:
                    sets.append(f"{q} = tk_cwd({q})")
            if sets:
                conn.execute(f'UPDATE "{table}" SET {", ".join(sets)}')
        conn.commit()


def redacted_copy(db_path, level, where="", params=(), redactor=None):
    """An in-memory copy of the database, filtered by the report's WHERE clause on the real values, then redacted."""
    src = sqlite3.connect(db_path)
    conn = sqlite3.connect(":memory:")
    src.backup(conn)
    src.close()
    if where:
        # the filter names real projects, so it runs before the names are replaced
        conn.execute(f"DELETE FROM requests WHERE rowid NOT IN (SELECT r.rowid FROM requests r JOIN sessions s USING (session_id) {where})",
                     tuple(params))
    (redactor or Redactor(level)).apply(conn)
    return conn
