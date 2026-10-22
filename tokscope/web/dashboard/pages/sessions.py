"""The Sessions page: the session list with its day groups, sort and compare tray."""

import html
import json

from ...report import _sessions_json
from ...report import SORT_SEG


def page_sessions(conn, f, qs):
    cond, params = f.cond()
    data = json.dumps(_sessions_json(conn, cond, params), separators=(",", ":")).replace("</", "<\\/")
    prefill = html.escape((qs.get("q") or [""])[0])
    return (f'<section class="card" id="sessions"><p class="note"><span class="key"><i></i>main thread</span><span class="key">'
            f'<i class="a"></i>subagents</span> Sessions with activity in {f.label()}. Open a row for each prompt; tick 2 to 4 to compare.</p>'
            f'<div class="tools"><input type="search" id="s-q" value="{prefill}" placeholder="Filter by title, skill or session id  ( / )">'
            + SORT_SEG + '<span class="note" id="s-count"></span></div><section class="card" id="compare"><h3>Compare</h3>'
            '<p class="note">Bold = fewest. Tokens per prompt evens out sessions of different length.</p><table></table></section>'
            '<div id="session-list"></div><div class="pickbar" id="pickbar" role="region" aria-label="Compare sessions" hidden><span id="pick-hint"></span><span class="acts">'
            '<button class="btn" id="clear-pick">Clear</button><button class="primary" id="do-compare" disabled>Compare</button></span></div>'
            '<p><button class="btn" id="s-more">Show more</button></p></section>'
            f'<script type="application/json" id="sessions-data">{data}</script>')
