"""The Sessions page: the session list with its day groups, sort and compare tray."""

import html
import json
from datetime import timedelta
from statistics import median

from ....core import otel
from ...report.sections.sessions import _sessions_json
from ...report.scripts import SORT_SEG
from ...report.widgets import _tok
from ..common import _iso


def _rail(rows):
    """The right rail from the rows the list already holds: range totals and the biggest session's main/subagent split."""
    if not rows:
        return ""
    real = [r for r in rows if not r.get("only")]
    with_agents = sum(1 for r in real if r["agents"])

    def row(label, value):
        return f'<div><span class="m">{label}</span><b class="mono">{value}</b></div>'
    stats = row("Sessions", f"{len(rows):,}") + row("Median tokens", _tok(median(r["tokens"] for r in rows)))
    if real:
        stats += (row("Median prompts", f"{median(r['prompts'] for r in real):g}")
                  + row("With subagents", f"{round(100 * with_agents / len(real))}%"))
    card = f'<section class="card"><h2>This range</h2><div class="rows">{stats}</div></section>'
    big = max(rows, key=lambda r: r["tokens"])
    title = big["title"] or f"session {big['id'][:8]}"
    day = (big["start"] or "")[:10]
    body = f'<p class="note">{html.escape(title)}{", " + day if day else ""}</p><div class="big">{_tok(big["tokens"])}</div>'
    if big["tokens"] and not big.get("only"):
        share = round(100 * big["agents"] / big["tokens"])
        names = {k: v for k, v in big["owners"].items() if k != "main thread"}
        top = f", mostly {html.escape(max(names, key=names.get))}" if names else ""
        body += (f'<div class="split"><u style="width:{100 - share}%"></u>'
                 f'<u class="a" style="width:{share}%"></u></div>'
                 f'<p class="note">{100 - share}% in the main thread, {share}% in subagents{top}.</p>')
    return card + f'<section class="card"><h2>Biggest session</h2>{body}</section>'


def page_sessions(conn, f, qs):
    cond, params = f.cond()
    # a project, model or skill filter names what a transcript knows: telemetry-only sessions have none of it
    only = [] if (f.project or f.model or f.skill) else otel.only_sessions(conn, _iso(f.now - timedelta(days=f.days)) if f.days else None)
    rows = _sessions_json(conn, cond, params, only)
    data = json.dumps(rows, separators=(",", ":")).replace("</", "<\\/")
    prefill = html.escape((qs.get("q") or [""])[0])
    return (f'<div class="sgrid"><div class="smain"><section class="card" id="sessions"><p class="note"><span class="key"><i></i>main thread</span><span class="key">'
            f'<i class="a"></i>subagents</span> Sessions with activity in {f.label()}. Open a row for each prompt; tick 2 to 4 to compare.</p>'
            f'<div class="tools"><input type="search" id="s-q" value="{prefill}" placeholder="Filter by title, skill, folder or session id  ( / )">'
            + SORT_SEG + '<span class="note" id="s-count"></span></div><section class="card" id="compare"><h3>Compare</h3>'
            '<p class="note">Bold = fewest. Tokens per prompt evens out sessions of different length.</p><table></table></section>'
            '<div id="session-list"></div><div class="pickbar" id="pickbar" role="region" aria-label="Compare sessions" hidden><span id="pick-hint"></span><span class="acts">'
            '<button class="btn" id="clear-pick">Clear</button><button class="primary" id="do-compare" disabled>Compare</button></span></div>'
            '<p><button class="btn" id="s-more">Show more</button></p></section></div>'
            f'<aside class="srail" aria-label="Session summary">{_rail(rows)}</aside></div>'
            f'<script type="application/json" id="sessions-data">{data}</script>')
