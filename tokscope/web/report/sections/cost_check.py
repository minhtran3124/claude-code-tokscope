"""The Cost check card: tokscope's API-eq against the cost_usd Claude Code reports in its OTel api_request events."""

import html

from ....core import otel
from ..widgets import _tok, _usd


def _drift(c, tk):
    return "–" if not c else f"{abs(tk - c) / c:.0%}"


def _row(cells, cls=""):
    return f'<tr{cls}>' + "".join(f'<td data-label="{h}">{html.escape(str(v))}</td>' for h, v in cells) + "</tr>"


def cost_check(conn, cond, params, since=None, scoped=False):
    """The card, or '' when no OTel event was ingested. `scoped`: a project/model/skill filter is on (see otel.cost_check)."""
    c = otel.cost_check(conn, cond, params, since, scoped)
    if c is None:
        return ""
    head = "".join(f"<th>{h}</th>" for h in ("Model", "Matched requests", "Claude Code", "tokscope API-eq", "Drift"))
    rows = [(m["model"] or "unknown", f'{m["n"]:,}', _usd(m["cc"]), _usd(m["tk"]),
             _drift(m["cc"], m["tk"]) + (" (no rate)" if m["unpriced"] and not m["tk"] else "")) for m in c["models"]]
    if rows:
        rows.append(("All models", f'{c["n"]:,}', _usd(c["cc"]), _usd(c["tk"]), _drift(c["cc"], c["tk"])))
        labels = ("Model", "Matched requests", "Claude Code", "tokscope API-eq", "Drift")
        table = f'<table class="drift"><tr>{head}</tr>' + "".join(_row(list(zip(labels, r))) for r in rows) + "</table>"
    else:
        table = '<p class="note">No OTel event matches a transcript request in this range yet.</p>'
    notes = []
    if c["unmatched"] and c["unmatched"][0]:
        n, usd = c["unmatched"]
        notes.append(f"{n:,} unmatched event{'s' * (n != 1)} ({_usd(usd)}): no transcript request has the same session, tokens and time")
    only = c["only"] if c["only"] and c["only"][0] else None
    if only:
        notes.append(f'<span class="tag">telemetry only</span> {only[0]:,} session{"s" * (only[0] != 1)}, {only[1]:,} requests, '
                     f'{_tok(only[2])} tokens, {_usd(only[3])} by Claude Code, no transcript. Not in the API-eq totals (no transcript to price)')
    if not scoped:
        total = c["cc"] + (c["unmatched"][1] or 0 if c["unmatched"] else 0) + (only[3] or 0 if only else 0)
        notes.append(f"Claude Code reported {_usd(total)} in this range, telemetry-only sessions included")
    body = "".join(f'<p class="note">{n if "<span" in n else html.escape(n)}</p>' for n in notes)
    return (f'<section class="card cost-check" id="cost-check"><h2>Cost check</h2>'
            f'<p class="note">Claude Code\'s own cost_usd against tokscope\'s API-eq for the same requests. Drift = the gap as a share '
            f'of Claude Code\'s cost; a model with no rate counts as $0 here, so it drifts 100%.</p>{table}{body}</section>')
