"""Where tokscope keeps its data: the SQLite db, hook marks, reports and benchmark files.

A source checkout keeps them in the repo (data/, reports/, bench/), so a clone works as before. An installed
package (pipx, uv tool) has no repo around it and uses $TOKSCOPE_HOME, else $XDG_DATA_HOME/tokscope."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
PACKAGE = Path(__file__).resolve().parent
ASSETS = PACKAGE / "assets"  # bundled files: fonts/ and the default phases.json


def home():
    if env := os.environ.get("TOKSCOPE_HOME"):
        return Path(env).expanduser()
    if (SRC / "pyproject.toml").exists() and (SRC / "bin" / "tokscope").exists():
        return SRC  # running from the repo, or an editable install of it
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "tokscope"


def projects_dirs(extra=None):
    """Transcript folders: --projects-dir, else each $CLAUDE_CONFIG_DIR entry (comma-separated) + /projects, else
    every existing ~/.config/claude/projects and ~/.claude/projects. Duplicates dropped, order kept."""
    if extra:
        found = [Path(p).expanduser() for p in ([extra] if isinstance(extra, (str, Path)) else extra)]
    elif env := os.environ.get("CLAUDE_CONFIG_DIR"):
        found = [Path(d.strip()).expanduser() / "projects" for d in env.split(",") if d.strip()]
    else:
        found = [d for d in (Path.home() / ".config" / "claude" / "projects", Path.home() / ".claude" / "projects")
                 if d.is_dir()] or [Path.home() / ".claude" / "projects"]
    return list(dict.fromkeys(found))


def db():
    path = home() / "data" / "tokscope.db"
    path.parent.mkdir(parents=True, exist_ok=True)  # a fresh install has no data folder yet
    return path


def marks():
    return home() / "data" / "marks"


def report():
    return home() / "reports" / "report.html"


def budgets():
    return home() / "budgets.json"


def tasks():
    return home() / "bench" / "tasks"


def phases():
    """A phases.json in the data home overrides the one shipped with the package."""
    own = home() / "phases.json"
    return own if own.exists() else ASSETS / "phases.json"


# A Finder-launched app (or a systemd user service) gets PATH=/usr/bin:/bin:/usr/sbin:/sbin: look where installers put tools
TOOL_DIRS = ("/opt/homebrew/bin", "/usr/local/bin", "~/.local/bin", "~/bin")
CLAUDE_FIRST = ("~/.local/bin",)  # where claude's installer puts it


def _is_git_stub(exe, run):
    """On macOS /usr/bin/git is a stub that opens the developer-tools install dialog until `xcode-select -p` succeeds."""
    if exe != "/usr/bin/git":
        return False
    try:
        return run(["xcode-select", "-p"], capture_output=True, timeout=5).returncode != 0
    except (OSError, subprocess.TimeoutExpired):
        return True


def tool(name, platform=None, run=subprocess.run, first=()):
    """Path of an executable: on PATH, else in TOOL_DIRS; None when neither has it. On darwin git is skipped while only
    Apple's stub is present, so nothing triggers the install dialog. `first` lists folders tried before PATH (claude's own installer folder wins, as it always did).
    `platform` and `run` are injected by tests."""
    if first and (exe := shutil.which(name, path=os.pathsep.join(os.path.expanduser(d) for d in first))):
        return exe
    extra = os.pathsep.join(os.path.expanduser(d) for d in TOOL_DIRS)
    exe = shutil.which(name)
    if exe and name == "git" and (platform or sys.platform) == "darwin" and _is_git_stub(exe, run):
        exe = None
    return exe or shutil.which(name, path=extra)
