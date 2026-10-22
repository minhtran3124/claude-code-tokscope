"""The Breakdowns page."""

import html

from ....features.changes import list_changes
from ...report.sections.breakdowns import _breakdowns
from ...report.sections.skills import _change_cards
from ...report.widgets import _section


def page_breakdowns(conn, f):
    cond, params = f.cond()
    changes = list_changes(conn)
    return (f'<div id="breakdowns">{_breakdowns(conn, cond, params)}</div>'
            + _section("Config changes",
                       (f"{len(changes)} recorded; latest: {html.escape(changes[-1][2])}" if changes else "None recorded yet"),
                       "before/after medians per run", _change_cards(conn, changes), "changes"))
