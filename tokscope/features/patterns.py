"""`tokscope patterns`: which kinds of prompts cost the most, what they ran and how they ended.

Read-only: it ingests nothing and writes no file. The rules are "Slice 1 grouping rules" in docs/research-prompt-insights.md.
Eligibility (bench, machine prompts, `--since`) is one SQL clause on real values. At `full` it filters the query; below
`full` it is the `where` of privacy.redacted_copy, so one code path groups the rows and the privacy path never reads
prompt text."""

import json
import os
import re
from datetime import timedelta
from pathlib import Path
from statistics import median

from ..core import pricing, tz
from ..core.pricing import API_EQ_NOTE
from ..core.ingest import open_db
from ..core.privacy import LEVELS, redacted_copy
from .changes import BENCH_PROJECT

MIN_CHARS = 25  # a shorter prompt that loads no skill is a follow-up
TASK_WORDS = 5
TASK_MIN_PROMPTS, TASK_MIN_SESSIONS = 3, 2
EXAMPLE_CHARS = 80
DEFAULT_DAYS = 14

# Stored prompt text is whitespace-collapsed and cut at 160 characters, so a token can be a fragment: the prefix
# patterns take any tail, including none.
_MASKS = [re.compile(p, f) for p, f in (
    (r"\bsk-[\w-]*", 0),                                # sk-ant- and sk- keys (word boundary: not task-key or risk-free)
    (r"(?<![A-Za-z0-9])(?:ghp|gho|ghs)_\w*", 0),         # GitHub tokens
    (r"(?<![A-Za-z0-9])github_pat_\w*", 0),
    (r"(?<![A-Za-z0-9])(?:AKIA|ASIA)[A-Z0-9]{0,16}", 0),  # AWS access key ids (a cut one keeps the prefix)
    (r"\bBearer\s+\S+", re.I),
    (r"(?<![A-Za-z0-9])(?:[A-Za-z0-9]+[_-])*(?:token|api[_-]?key|secret|password|passwd|pwd)\s*[=:]\s*\S*", re.I),  # also client_secret=, DB_PASSWORD=
    (r"(?<![A-Za-z0-9])(?:password|passwd|passphrase|secret)(?:\s+for\s+\S+)?(?:\s+(?:is|was)\s*:?|\s*:)\s*\S*", re.I),  # "password is hunter2", "password for bob was: x", "passphrase: x"
    (r"[A-Za-z0-9_-]{32,}", re.I),                        # any long URL-safe run
)]
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


def default_since():
    """The local date 14 days ago, as YYYY-MM-DD."""
    return (tz.now().date() - timedelta(days=DEFAULT_DAYS)).isoformat()


def _where(bound):
    """One eligibility clause over requests r and sessions s, on real values: not a bench session, and the request's prompt
    exists, is at or after the bound and is not a machine prompt (starts with <). EXISTS also drops a NULL prompt_idx and a
    prompt_idx with no prompts row. Selecting by the prompt's time keeps every request of a prompt that crosses the bound."""
    return ("WHERE COALESCE(s.project, '') NOT LIKE ? AND EXISTS (SELECT 1 FROM prompts p "
            "WHERE p.session_id = r.session_id AND p.prompt_idx = r.prompt_idx "
            "AND p.ts >= ? AND substr(COALESCE(p.text, ''), 1, 1) <> '<')", [BENCH_PROJECT, bound])


def _load(conn, where, params, with_text):
    """({(session, prompt): [request rows]}, {(session, prompt): [(skill)] main-thread loads first, then in load order}, {(session, prompt): text}).
    Prompt text is selected only when with_text is true, which is only at `full`."""
    reqs = {}
    for sid, idx, agent, model, cost, inp, cr, w5, w1 in conn.execute(
            "SELECT r.session_id, r.prompt_idx, r.agent_id, r.model, r.cost_usd, r.input, r.cache_read, r.cache_write_5m, "
            f"r.cache_write_1h FROM requests r JOIN sessions s USING (session_id) {where} ORDER BY r.ts, r.request_key",
            tuple(params)):
        reqs.setdefault((sid, idx), []).append(
            (agent, model, cost or 0.0, inp or 0, cr or 0, w5 or 0, w1 or 0))
    skills = {}
    for sid, idx, skill in conn.execute("SELECT session_id, prompt_idx, skill FROM skill_calls "
                                        "WHERE COALESCE(failed, 0) = 0 AND prompt_idx IS NOT NULL AND skill IS NOT NULL "
                                        "ORDER BY agent_id IS NOT NULL, ts, rowid"):  # main-thread loads first: the workflow is the prompt's own
        if (sid, idx) in reqs:  # the join in Python is what drops loads from machine and bench prompts at every level
            skills.setdefault((sid, idx), []).append(skill)
    texts = {}
    if with_text:
        for sid, idx, text in conn.execute("SELECT session_id, prompt_idx, text FROM prompts"):
            if (sid, idx) in reqs:
                texts[(sid, idx)] = text or ""
    return reqs, skills, texts


def _measure(rows, rate):
    """One prompt's numbers. rate(model) is USD per cached token or None.

    in_prompt = cost - inherited. cost sums every request (main thread and subagents, NULL as 0). For each main-thread
    request, inherited = min(its cache_read, the first main-thread request's cache_read) * the model's cache-read rate, so
    the first request inherits all of its reads. Each request's inherited share is capped at its own stored cost: cost_usd
    was priced at ingest and the rate is the current one, so a rate change must not push in_prompt below zero."""
    main = [r for r in rows if r[0] is None]
    cost = sum(r[2] for r in rows)
    first_read = main[0][4] if main else 0
    inherited = sum(min(r[2], min(r[4], first_read) * (rate(r[1]) or 0.0)) for r in main)
    first = main[0] if main else None
    return {"in_prompt": cost - inherited, "steps": len(main), "subagent_requests": len(rows) - len(main),
            "start_context": sum(first[3:7]) if first else None}


def _summarize(kind, key, members, facet_dirs):
    """members: [(session, prompt_idx, measure, skills, text)]."""
    costs = [m[2]["in_prompt"] for m in members]
    sessions = sorted({m[0] for m in members})
    starts = [m[2]["start_context"] for m in members if m[2]["start_context"] is not None]
    outcomes = {}
    for sid in sessions:
        if facet_dirs and (o := _outcome(sid, facet_dirs)):
            outcomes[o] = outcomes.get(o, 0) + 1
    costliest = max(members, key=lambda m: m[2]["in_prompt"])  # the first of equals
    return {"kind": kind, "key": key, "prompts": len(members), "sessions": len(sessions),
            "in_prompt_usd": sum(costs), "in_prompt_low": min(costs), "in_prompt_median": median(costs),
            "in_prompt_high": max(costs), "steps_median": median(m[2]["steps"] for m in members),
            "subagent_requests": sum(m[2]["subagent_requests"] for m in members),
            "skills": sorted({s for m in members for s in m[3]}),
            "start_context_median": median(starts) if starts else None,
            "outcomes": dict(sorted(outcomes.items())),
            "example": _example(costliest[4]) if costliest[4] is not None else None}


def run(db_path, since_bound, level="full"):
    """{"since", "privacy", "groups", "unpriced"} for prompts at or after since_bound (a tz.utc_bound value)."""
    if level not in LEVELS:
        raise ValueError(f"privacy level must be one of {', '.join(LEVELS)}")
    where, params = _where(since_bound)
    if level == "full":
        conn, filt, fparams = open_db(db_path), where, params
    else:  # the copy is filtered on real values, then redacted; below it there is nothing left to filter
        conn, filt, fparams = redacted_copy(db_path, level, where, params), "", []
    try:
        reqs, skills, texts = _load(conn, filt, fparams, with_text=level == "full")
        note = pricing.unpriced_text(pricing.unpriced(conn, filt, fparams))
    finally:
        conn.close()
    ov, rates = pricing.overrides(), {}
    rate = lambda m: rates.setdefault(m, pricing.cache_read_rate(m, ov))  # noqa: E731
    dirs = _facet_dirs() if level == "full" else []  # below full the privacy path reads no file keyed by a real session id
    workflows, tasks = {}, {}
    for (sid, idx), rows in reqs.items():
        text = texts.get((sid, idx))
        member = (sid, idx, _measure(rows, rate), skills.get((sid, idx), []), text)
        if member[3]:
            workflows.setdefault(member[3][0], []).append(member)
        elif text is not None and len(text) >= MIN_CHARS and (key := _task_key(text)):
            tasks.setdefault(key, []).append(member)
    groups = [_summarize("workflow", k, v, dirs) for k, v in workflows.items()]
    groups += [_summarize("task", k, v, dirs) for k, v in tasks.items()
               if len(v) >= TASK_MIN_PROMPTS and len({m[0] for m in v}) >= TASK_MIN_SESSIONS]
    groups.sort(key=lambda g: (-g["in_prompt_usd"], g["key"]))
    return {"since": since_bound, "privacy": level, "groups": groups, "unpriced": note}


def to_json(result):
    return json.dumps(result["groups"])


def _num(v, fmt="{:,.0f}"):
    return "-" if v is None else fmt.format(v)


def to_table(result):
    """One line of numbers per group, then an indented line with skills, outcomes and the example."""
    groups = result["groups"]
    if not groups:
        return "no prompt groups in this window; patterns reads only what is stored, so run `tokscope ingest` first"
    out = [f"{'kind':<8} {'key':<36} {'prompts':>7} {'sessions':>8} {'API-eq $':>9} {'low':>7} {'median':>7} {'high':>7} "
           f"{'steps':>5} {'sub req':>7} {'start ctx':>10}"]
    for g in groups:
        out.append(f"{g['kind']:<8} {g['key'][:36]:<36} {g['prompts']:>7,} {g['sessions']:>8,} {g['in_prompt_usd']:>9.2f} "
                   f"{g['in_prompt_low']:>7.2f} {g['in_prompt_median']:>7.2f} {g['in_prompt_high']:>7.2f} "
                   f"{_num(g['steps_median'], '{:g}'):>5} {g['subagent_requests']:>7,} {_num(g['start_context_median']):>10}")
        extra = []
        if g["skills"]:
            extra.append("skills: " + ", ".join(g["skills"]))
        if g["outcomes"]:
            extra.append("outcomes: " + ", ".join(f"{k} {n}" for k, n in g["outcomes"].items()))
        if g["example"]:
            extra.append(f"e.g. {g['example']}")
        if extra:
            out.append("    " + " | ".join(extra))
    return "\n".join(out)


def notes(result):
    """The lines that are not data: the API-eq note and the unpriced note."""
    return [API_EQ_NOTE] + ([result["unpriced"]] if result["unpriced"] else [])
