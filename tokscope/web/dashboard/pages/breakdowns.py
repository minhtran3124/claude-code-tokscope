"""The Breakdowns page."""

import html

from ....features.changes import list_changes
from ...report.sections.breakdowns import _breakdowns, token_split
from ...report.sections.rows import summary_view
from ...report.sections.skills import _change_cards
from ...report.widgets import _section
from .overview import _attention, _window


def page_breakdowns(conn, f, qs):
    cond, params = f.cond()
    changes = list_changes(conn)
    by = (qs.get("by") or ["phase"])[0]
    rail = (f'<div data-region="attention">{_attention(conn, f, _window(conn, f))}</div>' + token_split(conn, cond, params))
    sections = (_breakdowns(conn, cond, params)
                + _section("Config changes",
                           (f"{len(changes)} recorded; latest: {html.escape(changes[-1][2])}" if changes else "None recorded yet"),
                           "before/after medians per run", _change_cards(conn, changes), "changes"))
    return ('<div class="bdgrid"><div class="bd-main">'
            + summary_view(conn, cond, params, by, f.query(), lambda b: f.link("breakdowns", by=b) + "#summary")
            + f'<section class="card bd-secs"><h2>Sections, most important first</h2><div id="breakdowns" class="bd-flat">{sections}</div></section></div>'
            + f'<aside class="bd-rail" aria-label="What needs attention">{rail}</aside></div>')
