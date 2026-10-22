"""The last-7-days hero at the top of the report."""

import html
from datetime import datetime, timedelta, timezone

from ....core.pricing import API_EQ_NOTE, COSTS_DOC
from ..common import TOKENS
from ..widgets import _tok, _usd


def _week_compare(conn, cond, params, now):
    def window(start, end):
        return conn.execute(f"SELECT sum({TOKENS}), count(DISTINCT session_id), sum(cost_usd) FROM requests r "
                            f"JOIN sessions s USING (session_id) {cond} AND r.ts >= ? AND r.ts < ?",
                            (*params, start.isoformat(), end.isoformat())).fetchone()
    return window(now - timedelta(days=7), now), window(now - timedelta(days=14), now - timedelta(days=7))


def _hero(conn, cond, params):
    now = datetime.now(timezone.utc)
    (tk, n, usd), (prev_tk, prev_n, _) = _week_compare(conn, cond, params, now)
    per, prev_per = (tk or 0) / max(n or 0, 1), (prev_tk or 0) / max(prev_n or 0, 1)
    if prev_per:
        pct = per / prev_per - 1
        trend = (f'<span class="trend {"up" if pct > 0 else "down"}">{pct:+.0%}</span> tokens per session vs the 7 days before '
                 f'({_tok(prev_per)} → {_tok(per)})')
    else:
        trend = "no sessions in the 7 days before to compare with"
    since = (now - timedelta(days=7)).isoformat()
    owner = conn.execute(f"""SELECT CASE WHEN agent_id IS NULL THEN 'the main thread' ELSE agent_type END, sum({TOKENS})
                             FROM requests r JOIN sessions s USING (session_id) {cond} AND r.ts >= ?
                             GROUP BY 1 ORDER BY 2 DESC LIMIT 1""", (*params, since)).fetchone()
    skill = conn.execute(f"""SELECT skill, sum({TOKENS}) FROM requests r JOIN sessions s USING (session_id) {cond}
                             AND r.ts >= ? AND skill IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 1""", (*params, since)).fetchone()
    top = []
    if owner and tk:
        top.append(f"{html.escape(owner[0])} uses {owner[1] / tk:.0%} of them")
    if skill:
        top.append(f"the costliest skill is <b>{html.escape(skill[0])}</b> ({_tok(skill[1])})")
    sentence = "; ".join(top)
    return (f'<section class="hero"><div class="big">Last 7 days: <em data-count="{tk or 0}" data-kind="tok">{_tok(tk)}</em> tokens in {n or 0} sessions</div>'
            f'<p>{trend}.</p>{f"<p>{sentence[:1].upper() + sentence[1:]}.</p>" if sentence else ""}'
            f'<p class="usd">{_usd(usd)} API-eq. {html.escape(API_EQ_NOTE.removeprefix("API-eq = "))[:1].upper()}{html.escape(API_EQ_NOTE.removeprefix("API-eq = "))[1:]} '
            f'<a href="{COSTS_DOC}" target="_blank" rel="noopener">How Claude Code usage is limited</a></p></section>')
