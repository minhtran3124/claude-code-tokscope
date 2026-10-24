"""The Breakdowns page."""

import html

from ....features.changes import list_changes
from ...report.sections.breakdowns import _breakdowns
from ...report.sections.rows import summary_view
from ...report.sections.skills import _change_cards
from ...report.widgets import _section


def page_breakdowns(conn, f, qs):
    cond, params = f.cond()
    changes = list_changes(conn)
    by = (qs.get("by") or ["phase"])[0]
    return (summary_view(conn, cond, params, by, f.query(), lambda b: f.link("breakdowns", by=b) + "#summary")
            + f'<div id="breakdowns">{_breakdowns(conn, cond, params)}</div>'
            + _section("Config changes",
                       (f"{len(changes)} recorded; latest: {html.escape(changes[-1][2])}" if changes else "None recorded yet"),
                       "before/after medians per run", _change_cards(conn, changes), "changes"))
