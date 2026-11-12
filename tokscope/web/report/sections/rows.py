"""The Summary section: the CLI's cost table by phase, skill, agent or model, with CSV and JSON downloads and Copy."""

import html
import json

from ....core.pricing import API_EQ_NOTE, unpriced, unpriced_text
from ....core.summary import SUMMARY_SQL, rows
from ...theme.icons import icon
from ..widgets import _more, _table, _tok, _usd, skill_chip

TITLES = {"phase": "Phase", "skill": "Skill", "agent": "Agent", "model": "Model"}


def _share(x):
    """The share column: a bar (the number is its title and label), as in the design's Summary by phase."""
    return (f'<span class="shr" title="{x:.1%}" role="img" aria-label="{x:.1%}"><i style="width:{min(max(x, 0), 1) * 100:.1f}%"></i></span>', "raw")


def _pane(found, by, shown, chips=False):
    """One group-by table; chips=True (the dashboard) shows a skill as its tinted chip."""
    total = sum(r["cost_usd"] for r in found) or 1
    carried = by == "phase"  # a phase's carried part comes from later prompts with no skill
    name = lambda k: (skill_chip(k), "raw") if chips and by == "skill" and k != "(none)" else k  # noqa: E731
    table = _table([TITLES[by], "requests", "prompt tok", "share", "output tok", "API-eq $"] + (["carried"] if carried else []),
                   [(name(r["key"]), f"{r['requests']:,}", _tok(r["prompt_tokens"]), _share(r["cost_usd"] / total), _tok(r["output_tokens"]),
                     (_usd(r["cost_usd"]), "u")) + ((f"{r['carried_cost_usd'] / (r['cost_usd'] or 1):.0%}",) if carried else ())
                    for r in found], None) if found else '<p class="note">No requests in this range.</p>'
    return (f'<div class="sum-pane" data-by="{by}" data-rows="{html.escape(json.dumps(found, separators=(",", ":")))}"'
            f'{"" if shown else " hidden"}>{table}</div>')


def summary_view(conn, cond, params, by="phase", api_query=None, link=None):
    """Dashboard: api_query is the filter bar as a query string and link(by) the page URL for a group-by; the buttons use
    /api/summary. Report: both None, all four tables are in the file, and the buttons build their file in the browser."""
    if by not in SUMMARY_SQL:
        by = "phase"
    live = api_query is not None
    panes = [(b, rows(conn, b, cond, params)) for b in ([by] if live else SUMMARY_SQL)]
    chips = "".join(
        (f'<a class="chip{" on" if b == by else ""}" href="{html.escape(link(b))}"{" aria-current=page" if b == by else ""}>{TITLES[b]}</a>'
         if live else f'<button type="button" class="chip{" on" if b == by else ""}" data-pick="{b}" aria-pressed="{str(b == by).lower()}">{TITLES[b]}</button>')
        for b in SUMMARY_SQL)

    def dl(fmt):
        label = f"Download {fmt.upper()}"
        if live:
            href = html.escape(f"/api/summary?{api_query}{'&' if api_query else ''}by={by}&format={fmt}")
            return (f'<a class="btn" href="{href}" download="tokscope-summary-{by}.{fmt}" aria-label="{label}">'
                    f'{icon("download", 14)}{fmt.upper()}</a>')
        return f'<a class="btn" href="#" data-dl="{fmt}">{label}</a>'

    note = unpriced_text(unpriced(conn, cond, params))
    notes = (f'<p class="note">{html.escape(API_EQ_NOTE)}</p>'
             + (f'<p class="note unpriced" role="note">{html.escape(note)}</p>' if note else ""))
    if live:  # the dashboard: a card with the downloads on its heading row and the group-by links as tabs
        return (f'<section class="card sumcard" id="summary"><div class="sumview" data-live="1"><div class="sumhead"><h2>Summary</h2>'
                '<span class="note">the <code>tokscope summary</code> table for these filters</span>'
                f'<span class="acts">{dl("csv")}{dl("json")}<button type="button" class="btn" data-copy>{icon("copy", 14)}Copy</button></span></div>'
                f'<nav class="sumtabs" aria-label="Group by">{chips}</nav>'
                + "".join(_pane(found, b, b == by, True) for b, found in panes) + notes + "</div></section>")
    inner = (f'<div class="sumview" data-live="{int(live)}"><div class="tools"><span class="note">Group by</span>'
             f'<span class="seg" role="group" aria-label="Group by">{chips}</span>'
             f'<span class="acts">{dl("csv")}{dl("json")}<button type="button" class="btn" data-copy>Copy</button></span></div>'
             + "".join(_pane(found, b, b == by) for b, found in panes) + notes + "</div>")
    return _more("Summary", "the cost table by phase, skill, agent or model, as in <code>tokscope summary</code>; "
                 "download it as CSV or JSON", inner, "summary", is_open=True)
