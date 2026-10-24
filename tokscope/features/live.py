"""Claude Code sessions that are open right now, read from ~/.claude/sessions/<pid>.json (one file per process).

A file stays behind when a process dies without cleaning up, so each one counts only while its pid is alive and,
where /proc says so, was started at the time the file records (a reused pid is another process)."""

import json
import os
from pathlib import Path

ENTRY = {"cli": "Terminal", "claude-vscode": "VS Code", "claude-desktop": "Desktop", "claude-jetbrains": "JetBrains"}


def sessions_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "sessions"


def entry_label(entrypoint):
    return ENTRY.get(entrypoint) or ("SDK" if str(entrypoint).startswith("sdk") else str(entrypoint or "unknown"))


def _alive(pid, proc_start):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass  # another user's process is still a process
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return True  # no /proc (macOS): the signal check is all there is
    return not proc_start or stat.rsplit(")", 1)[1].split()[19] == str(proc_start)


def running(directory=None):
    """Open sessions, busiest first: [{"id", "status" ("busy" | "idle"), "entry", "pid"}]."""
    out = []
    for f in (directory or sessions_dir()).glob("*.json"):
        try:
            d = json.loads(f.read_text())
            if not _alive(int(d["pid"]), d.get("procStart")):
                continue
            out.append({"id": d["sessionId"], "status": "busy" if d.get("status") == "busy" else "idle",
                        "entry": entry_label(d.get("entrypoint")), "pid": d["pid"]})
        except (OSError, ValueError, KeyError, TypeError):
            continue  # half-written or not ours
    return sorted(out, key=lambda s: (s["status"] != "busy", s["entry"], s["id"]))


def signature(sessions):
    """Changes when the set of open sessions or any status changes (the dashboard polls this)."""
    return ",".join(f"{s['id'][:8]}{s['status'][0]}" for s in sessions)
