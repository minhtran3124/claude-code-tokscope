"""The cost table `tokscope summary` prints, as rows: one query for the CLI, /api/summary, the dashboard and the report."""

import csv
import io
import json

from . import skills
from .ingest import CARRIED

SUMMARY_SQL = {
    "phase": "COALESCE(phase, 'unscoped')",
    "skill": "COALESCE(skill, '(none)')",
    "agent": "COALESCE(agent_type, 'main')",
    "model": "model",
}
SOURCE_FIELDS = ("typed_loads", "typed_median_tokens", "tool_loads", "tool_median_tokens")  # by skill, when any load exists
FIELDS = ("key", "requests", "prompt_tokens", "output_tokens", "cost_usd", "carried_cost_usd")
DEFAULT_LIMIT = 25


def rows(conn, by, where="", params=(), limit=DEFAULT_LIMIT):
    """One dict (FIELDS) per group, dearest first. `where` filters requests as r and sessions as s."""
    found = conn.execute(
        f"""SELECT {SUMMARY_SQL[by]} AS k, count(*), sum(input + cache_read + cache_write_5m + cache_write_1h), sum(output),
                   sum(cost_usd), sum(CASE WHEN {CARRIED} THEN cost_usd ELSE 0 END)
            FROM requests r JOIN sessions s USING (session_id) {where}
            GROUP BY k ORDER BY sum(cost_usd) DESC LIMIT ?""",
        (*params, limit),
    ).fetchall()
    out = [dict(zip(FIELDS, (str(k), n, prompt or 0, out or 0, round(cost or 0.0, 6), round(carried or 0.0, 6))))
           for k, n, prompt, out, cost, carried in found]
    split = skills.source_split(conn, where=(where or "WHERE 1=1", params)) if by == "skill" else {}
    if split:  # loads typed as /command and loads the model made with the Skill tool, each with its median tokens
        for r in out:
            both = split.get(r["key"], {})
            r.update(zip(SOURCE_FIELDS, (*both.get("command", (0, None)), *both.get("tool", (0, None)))))
    return out


def to_json(found):
    return json.dumps(found, indent=2)


def safe_cell(value):
    """A text cell a spreadsheet reads as a formula (= + - @, tab, CR first) gets a leading quote. The key is a skill or
    agent name from the transcript."""
    return "'" + value if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def to_csv(found, fields=None):
    fields = fields or FIELDS + (SOURCE_FIELDS if found and "typed_loads" in found[0] else ())
    out = io.StringIO()
    w = csv.DictWriter(out, fields, lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    w.writerows({k: safe_cell(v) for k, v in row.items()} for row in found)
    return out.getvalue()
