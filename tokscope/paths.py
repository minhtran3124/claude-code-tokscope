"""Where tokscope keeps its data: the SQLite db, hook marks, reports and benchmark files.

A source checkout keeps them in the repo (data/, reports/, bench/), so a clone works as before. An installed
package (pipx, uv tool) has no repo around it and uses $TOKSCOPE_HOME, else $XDG_DATA_HOME/tokscope."""

import os
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent
PACKAGE = Path(__file__).resolve().parent


def home():
    if env := os.environ.get("TOKSCOPE_HOME"):
        return Path(env).expanduser()
    if (SRC / "pyproject.toml").exists() and (SRC / "bin" / "tokscope").exists():
        return SRC  # running from the repo, or an editable install of it
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "tokscope"


def db():
    path = home() / "data" / "tokscope.db"
    path.parent.mkdir(parents=True, exist_ok=True)  # a fresh install has no data folder yet
    return path


def marks():
    return home() / "data" / "marks"


def report():
    return home() / "reports" / "report.html"


def tasks():
    return home() / "bench" / "tasks"


def phases():
    """A phases.json in the data home overrides the one shipped with the package."""
    own = home() / "phases.json"
    return own if own.exists() else PACKAGE / "phases.json"
