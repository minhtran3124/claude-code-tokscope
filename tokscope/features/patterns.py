"""`tokscope patterns`: which kinds of prompts cost the most, what they ran and how they ended.

Read-only: it ingests nothing and writes no file. The rules are "Slice 1 grouping rules" in docs/research-prompt-insights.md.
Eligibility (bench, machine prompts, `--since`) is one SQL clause on real values. At `full` it filters the query; below
`full` it is the `where` of privacy.redacted_copy, so one code path groups the rows and the privacy path never reads
prompt text."""

import json
import os
import re
from pathlib import Path
from statistics import median

from ..core import pricing, tz
from ..core.ingest import open_db
from ..core.pricing import API_EQ_NOTE
from ..core.privacy import LEVELS, redacted_copy
from .changes import BENCH_PROJECT

MIN_CHARS = 25  # a shorter prompt that loads no skill is a follow-up
TASK_WORDS = 5
TASK_MIN_PROMPTS, TASK_MIN_SESSIONS = 3, 2
EXAMPLE_CHARS = 80
DEFAULT_DAYS = 14

# Stored prompt text is whitespace-collapsed and cut at 160 characters, so a token can be a fragment: the prefix
# patterns take any tail, including none.
_MASKS = [re.compile(p, re.I if i >= 3 else 0) for i, p in enumerate((
    r"\bsk-[\w-]*",                                     # sk-ant- and sk- keys (word boundary: not task-key or risk-free)
    r"(?<![A-Za-z0-9])(?:ghp|gho|ghs)_\w*",             # GitHub tokens
    r"(?<![A-Za-z0-9])github_pat_\w*",
    r"\bBearer\s+\S+",
    r"\b(?:token|api_key|apikey|secret|password)\s*[=:]\s*\S*",
    r"[A-Za-z0-9_-]{32,}",                              # any long URL-safe run
))]
_OUTCOME = re.compile(r"[a-z_]{1,40}")
_SESSION_FILE = re.compile(r"[\w][\w.-]*")


def mask(text):
    """Replace token-like strings with [masked]."""
    for rx in _MASKS:
        text = rx.sub("[masked]", text)
    return text


def _task_key(text):
    """First five words of a prompt, lower case, with paths, ~ and . words and numbers dropped; None when none is left."""
    words = [w for w in mask(text or "").lower().split()
             if "/" not in w and not w.startswith(("~", ".")) and not w.isdigit()]
    return " ".join(words[:TASK_WORDS]) or None


def _example(text):
    """The prompt masked, then cut to 80 characters including the trailing ellipsis. Masking comes first, so a cut cannot
    hide part of a token from the patterns."""
    text = mask(" ".join((text or "").split()))
    if not text:
        return None
    return text if len(text) <= EXAMPLE_CHARS else text[:EXAMPLE_CHARS - 1] + "…"


def _facet_dirs():
    """usage-data/facets under each comma-separated $CLAUDE_CONFIG_DIR entry, else under ~/.claude."""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    roots = [Path(d.strip()).expanduser() for d in env.split(",") if d.strip()] if env else []
    return [r / "usage-data" / "facets" for r in roots or [Path.home() / ".claude"]]


def _outcome(session_id, dirs):
    """The `outcome` token of the session's facets file, or None. Only that field is read, and only a short token is
    kept, so free text (a summary) cannot reach the output. Never raises and never prints."""
    if not isinstance(session_id, str) or not _SESSION_FILE.fullmatch(session_id):
        return None
    for d in dirs:
        try:
            raw = (Path(d) / f"{session_id}.json").read_text("utf-8")
        except OSError:
            continue  # not in this folder: try the next one
        except ValueError:
            return None  # not UTF-8
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        value = data.get("outcome") if isinstance(data, dict) else None
        return value if isinstance(value, str) and _OUTCOME.fullmatch(value) else None
    return None
