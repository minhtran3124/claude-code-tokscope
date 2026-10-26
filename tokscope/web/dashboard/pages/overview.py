"""The Overview page: today against a typical day, the KPI strip, biggest movers and the daily chart."""

import copy
import html
from datetime import date, datetime, timedelta, timezone

from ....core import baseline, budgets, cache, otel, skills, tz
from ....features import library, live
from ... import charts
from ....features.changes import list_changes
from ....core.pricing import API_EQ_NOTE, unpriced, unpriced_text
from ...report.common import TOKENS
from ...report.sections.cost_check import cost_check
from ...report.widgets import _start_line, _table, _tok, _usd
from ..common import Filters, _iso, _q


def _totals(conn, cond, params):
    base = f"FROM requests r JOIN sessions s USING (session_id) {cond}"
    return conn.execute(
        f"SELECT sum({TOKENS}), sum(cost_usd), count(DISTINCT session_id), sum(output), "
        f"count(DISTINCT CASE WHEN agent_id IS NOT NULL THEN session_id || agent_id END), sum(cache_read) {base}", params).fetchone()


def _with_only(t, only):
    """_totals plus the telemetry-only sessions (tokens, cost, sessions, output, cache; subagent runs stay)."""
    return ((t[0] or 0) + only["tokens"], (t[1] or 0) + only["usd"], (t[2] or 0) + only["sessions"],
            (t[3] or 0) + only["output"], t[4], (t[5] or 0) + only["cache_read"])


def _spark(values, w=96, h=22):
    if len(values) < 2 or not max(values):
        return ""
    top = max(values)
    pts = " ".join(f"{w * i / (len(values) - 1):.1f},{h - 2 - (h - 4) * v / top:.1f}" for i, v in enumerate(values))
    return f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true"><polyline points="{pts}"/></svg>'


def start_detail(base):
    """The sessions behind the start line: median, p90 and the 30-day trend (all `~`: estimates)."""
    bits = [f"median of {base['n']:,} session{'s' * (base['n'] != 1)}", f"p90 ~{_tok(base['p90'])}"]
    if base["first"] and base["last"] is not None:
        bits.append(f"30 days: ~{_tok(base['first'])} → ~{_tok(base['last'])} ({base['last'] / base['first'] - 1:+.0%})")
    return f'<span class="note" title="{html.escape(baseline.METHOD)}">{" · ".join(bits)}</span> {_spark(base["trend"])}'


def _session_start(conn, f):
    """What every new session starts at, over the range and project of the filter bar (not the model or skill filter)."""
    cond, params = Filters({"range": [f.range], "project": [f.project]}).cond()
    base = baseline.stats(baseline.starts(conn, cond, params), None,
                          baseline.starts(conn, *Filters({"range": ["all"], "project": [f.project]}).cond()))
    body = (f'<p>{_start_line(base)}</p><p>{start_detail(base)}</p>' if base
            else '<p class="note">No sessions in this range.</p>')
    return (f'<section class="card"><h2>Session start</h2><p class="note">{f.label()}, before you type anything: system prompt, '
            f'tools, MCP servers, skills and CLAUDE.md</p>{body}</section>')


MIN_HISTORY_DAYS = 7  # a change chip needs more than this many elapsed days of history; a typical day, more than this many active days


def _delta(now, before):
    """The change chip, or nothing when there is no fair baseline (the caller says once what it compares)."""
    if not before or now is None:
        return ""
    pct = now / before - 1
    text = f"×{now / before:,.0f}" if pct >= 9.995 else f"{pct:+.0%}"  # +1,000% and up read better as a multiple
    kind = "flat" if abs(pct) < .01 else "up" if pct > 0 else "down"  # under 1% either way reads as no change
    text = "+0%" if kind == "flat" else text
    return f'<span class="dl"><span class="trend {kind}">{text}</span></span>'


def _history_start(conn, f):
    """The first request the filters can see, over all time."""
    whole = copy.copy(f)
    whole.days = None
    cond, params = whole.cond()
    return conn.execute(f"SELECT min(r.ts) FROM requests r JOIN sessions s USING (session_id) {cond}", params).fetchone()[0]


def _history_days(conn, f):
    """Days elapsed from the first request to now, as a fraction (0 when there is no data)."""
    start = _history_start(conn, f)
    if not start:
        return 0.0
    first = datetime.strptime(start[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    return max(0.0, (f.now - first).total_seconds() / 86400)


def _window(conn, f):
    """{"now": elapsed days of the range since the first request, "before": the same for the window before it}, or None
    when a change would say too little: no fixed range, 7 days of history or fewer (elapsed time, not calendar days), or
    less than a full day of data before the range. Both sides become an average per day, so a window before that holds only part of the range
    still compares fairly."""
    if not f.days:
        return None
    hist = _history_days(conn, f)
    before = min(f.days, max(0.0, hist - f.days))
    return {"now": min(f.days, hist), "before": before} if hist > MIN_HISTORY_DAYS and before >= 1 else None


def _day_rows(conn, f, shift=0):
    """One row per day with data (local days, or TOKSCOPE_TZ's, like Today): day, tokens, API-eq, sessions,
    output, subagent runs, cache read, main-thread tokens (shift=1: the window before the range)."""
    cond, params = f.cond(shift)
    return _q(conn, f"SELECT localday(r.ts) d, sum({TOKENS}), sum(cost_usd), count(DISTINCT session_id), sum(output), "
                    f"count(DISTINCT CASE WHEN agent_id IS NOT NULL THEN session_id || agent_id END), sum(cache_read), "
                    f"sum(CASE WHEN agent_id IS NULL THEN {TOKENS} ELSE 0 END) FROM requests r JOIN sessions s USING (session_id) "
                    f"{cond} GROUP BY d ORDER BY d", params)


def _kpis(conn, f):
    cond, params = f.cond()
    cmp = _window(conn, f)
    now, before = _totals(conn, cond, params), _totals(conn, *f.cond(1)) if cmp else (None,) * 6
    # sessions with OTel events and no transcript: in the tiles, not in the per-day series or any breakdown (no filter names them)
    only = None if (f.project or f.model or f.skill) else otel.only_totals(conn, _iso(f.now - timedelta(days=f.days)) if f.days else None)
    if only and only["sessions"]:
        now = _with_only(now, only)
        if cmp:
            end = f.now - timedelta(days=f.days)
            before = _with_only(before, otel.only_totals(conn, _iso(end - timedelta(days=f.days)), _iso(end)))
    else:
        only = None
    rows = _day_rows(conn, f)
    col = lambda i: [r[i] or 0 for r in rows]  # noqa: E731
    cache = lambda t: round(100 * (t[5] or 0) / (t[0] or 1)) if t[0] else None  # noqa: E731
    cache_daily = [round(100 * (r[6] or 0) / r[1]) if r[1] else 0 for r in rows]
    # (key, label, value, text, kind, column of the day rows or None for a share, series); the change compares the average
    # per day: the sum of the day rows over the elapsed days each side covers, from _window (sessions and runs count once
    # per day they appear)
    before_rows = _day_rows(conn, f, 1) if cmp else []
    per_day = lambda rs, i, n: sum(r[i] or 0 for r in rs) / n  # noqa: E731
    tiles = [("tokens", "Tokens", now[0] or 0, _tok(now[0]), "tok", 1, col(1)),
             ("usd", "API-eq", round(now[1] or 0, 2), _usd(now[1]), "usd", 2, col(2)),
             ("sessions", "Sessions", now[2] or 0, f"{now[2] or 0:,}", "int", 3, col(3)),
             ("output", "Output tokens", now[3] or 0, _tok(now[3]), "tok", 4, col(4)),
             ("runs", "Subagent runs", now[4] or 0, f"{now[4] or 0:,}", "int", 5, col(5)),
             ("cache", "From cache", cache(now) or 0, f"{cache(now) or 0}%", "pct", None, cache_daily)]
    out = []
    for i, (key, label, raw, text, kind, idx, series) in enumerate(tiles):
        title = f' title="{html.escape(API_EQ_NOTE + (otel.ONLY_NOTE if only else ""))}"' if key == "usd" else ""
        if only and key in ("tokens", "sessions", "output"):
            title = f' title="{html.escape(otel.ONLY_NOTE.strip())}"'
        if key == "cache":
            title = ' title="Share of all tokens that came from cache, against the window before"'
        chip = ""
        if cmp:
            chip = _delta(cache(now), cache(before)) if idx is None else _delta(per_day(rows, idx, cmp["now"]), per_day(before_rows, idx, cmp["before"]))
        out.append(f'<div class="kpi" style="--i:{i}"{title}><span>{label}</span>'
                   f'<b data-count="{raw}" data-kind="{kind}" data-key="{key}">{text}</b>{_spark(series)}{chip}</div>')
    n = int(cmp["before"]) if cmp else 0
    note = (f'<p class="note strip-note">Change = average per day in this range against the {n} day{"" if n == 1 else "s"} before it. '
            f'From cache compares its share of all tokens, not a per-day average.</p>' if cmp else "")
    warn = unpriced_text(unpriced(conn, cond, params))
    if only:
        note += (f'<p class="note strip-note"><span class="tag" title="{html.escape(otel.ONLY_TIP)}">telemetry only</span> '
                 f'{only["sessions"]:,} session{"s" * (only["sessions"] != 1)} with no transcript are in Tokens, API-eq, Sessions, Output tokens and '
                 f'From cache, at Claude Code\'s own cost_usd. The per-day change and the charts leave them out.</p>')
    note += f'<p class="note unpriced" role="note">{html.escape(warn)}</p>' if warn else ""
    return f'<div class="kpis strip">{"".join(out)}</div>{note}'


def _days(conn, f):
    cond, params = f.cond()
    return _q(conn, f"SELECT localday(r.ts) d, sum({TOKENS}), sum(cost_usd) FROM requests r JOIN sessions s "
                    f"USING (session_id) {cond} GROUP BY d ORDER BY d", params)


def _local_midnight():
    return tz.midnight()


TYPICAL_DAYS = 14      # a typical day is the median of this many of the latest active days
TYPICAL_LOOKBACK = 120  # days of requests read to find them


def _percentile(sorted_values, q):
    """Linear-interpolated percentile of an ascending list (q from 0 to 1)."""
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def typical_day(days, today, keep=TYPICAL_DAYS, need=MIN_HISTORY_DAYS):
    """The middle of a day's cumulative tokens: {"p25", "med", "p75"} with 25 marks each (mark k = tokens before hour k),
    taken over the last `keep` active days before `today`. `days` maps a local date to 24 hourly token counts and holds
    only days with a request, so days off never pull the median down. None unless there are more than `need` active days."""
    active = sorted(d for d in days if d < today)
    if len(active) <= need:
        return None
    cums = []
    for d in active[-keep:]:
        run, marks = 0, [0]
        for v in days[d]:
            run += v
            marks.append(run)
        cums.append(marks)
    return {name: [_percentile(sorted(c[k] for c in cums), q) for k in range(25)]
            for name, q in (("p25", .25), ("med", .5), ("p75", .75))} | {"n": len(cums)}


def _at_hour(marks, x):
    """A cumulative curve at hour x (0 to 24, fractions allowed)."""
    lo = min(int(x), 23)
    return marks[lo] + (marks[lo + 1] - marks[lo]) * (x - lo)


def _hours(conn, f):
    """{local date: 24 hourly token counts} for the last TYPICAL_LOOKBACK days, today included; project/model/skill apply.
    Requests are grouped by UTC minute and each minute is converted to local time, so half-hour zones are exact."""
    whole = Filters({"range": ["all"], "project": [f.project], "model": [f.model], "skill": [f.skill]})
    cond, params = whole.cond()
    since = _iso(_local_midnight() - timedelta(days=TYPICAL_LOOKBACK))
    days = {}
    for minute, tokens in _q(conn, f"SELECT substr(r.ts,1,16), sum({TOKENS}) FROM requests r JOIN sessions s USING (session_id) "
                                   f"{cond} AND r.ts >= ? GROUP BY 1", (*params, since)):
        local = datetime.strptime(minute, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc).astimezone(tz.zone())
        days.setdefault(local.date(), [0] * 24)[local.hour] += tokens or 0
    return days


def _today_chart(typ, mine, x_now, total):
    """Today's cumulative tokens (solid line) against the typical day: median (dashed) and the p25 to p75 band."""
    w, h, pad_l, pad_r, pad_t, pad_b = 720, 118, 44, 10, 8, 20
    top = max(typ["p75"][24], total, 1) * 1.05
    X = lambda x: pad_l + (w - pad_l - pad_r) * x / 24  # noqa: E731
    Y = lambda v: pad_t + (h - pad_t - pad_b) * (1 - v / top)  # noqa: E731
    pts = lambda marks: " ".join(f"{X(k):.1f},{Y(v):.1f}" for k, v in enumerate(marks))  # noqa: E731
    band = " ".join(f"{X(k):.1f},{Y(v):.1f}" for k, v in enumerate(typ["p75"])) + " " + \
        " ".join(f"{X(k):.1f},{Y(v):.1f}" for k, v in reversed(list(enumerate(typ["p25"]))))
    out = [f'<svg class="tchart" viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Tokens so far today against a typical day">']
    for frac in (0, .5, 1):
        y = pad_t + (h - pad_t - pad_b) * (1 - frac)
        out.append(f'<line class="g" x1="{pad_l}" x2="{w - pad_r}" y1="{y:.1f}" y2="{y:.1f}"/>'
                   f'<text x="{pad_l - 6}" y="{y + 4:.1f}" text-anchor="end">{_tok(top * frac)}</text>')
    for hr in (0, 6, 12, 18, 24):
        out.append(f'<text x="{X(hr):.1f}" y="{h - 5}" text-anchor="{"start" if hr == 0 else "end" if hr == 24 else "middle"}">{hr:02d}:00</text>')
    line = " ".join(f"{X(k):.1f},{Y(v):.1f}" for k, v in mine) + f" {X(x_now):.1f},{Y(total):.1f}"
    out.append(f'<polygon class="tband" points="{band}"/><polyline class="tmed" points="{pts(typ["med"])}"/>'
               f'<polyline class="tline" points="{line}"/><circle class="tdot" cx="{X(x_now):.1f}" cy="{Y(total):.1f}" r="4"/></svg>')
    return "".join(out)


def _today(conn, f):
    """Today (local midnight on) and the latest session, whatever the range; project/model/skill still apply."""
    today = Filters({"range": ["all"], "project": [f.project], "model": [f.model], "skill": [f.skill]})
    cond, params = today.cond()
    cond, params = f"{cond} AND r.ts >= ?", (*params, _iso(_local_midnight()))
    tokens, usd, n, _, _, _ = _totals(conn, cond, params)
    last = conn.execute(
        f"SELECT session_id, s.title, max(r.ts) FROM requests r JOIN sessions s USING (session_id) {cond} "
        f"GROUP BY session_id ORDER BY 3 DESC LIMIT 1", params).fetchone()
    nums = (f'<div class="today-nums"><div><span>Tokens today</span><b data-count="{tokens or 0}" data-kind="tok" data-key="today-tokens">'
            f'{_tok(tokens)}</b></div><div><span>API-eq today</span><b data-count="{round(usd or 0, 2)}" data-kind="usd" '
            f'data-key="today-usd">{_usd(usd)}</b></div><div><span>Sessions today</span><b data-count="{n or 0}" data-kind="int" '
            f'data-key="today-sessions">{n or 0}</b></div></div>')
    # is today normal? today's running total against the typical day at the same local time
    hours, clock = _hours(conn, f), tz.now()
    typ = typical_day(hours, clock.date())
    chart = ""
    if typ:
        x_now = clock.hour + clock.minute / 60
        total = tokens or 0
        mine, run = [], 0
        for k in range(clock.hour + 1):
            mine.append((k, run))
            run += hours.get(clock.date(), [0] * 24)[k]
        expect = _at_hour(typ["med"], x_now)
        at = f"{clock:%H:%M}"
        if expect <= 0:
            vs = ('<span class="trend flat">●</span> as quiet as a typical day by ' + at if not total else
                  f'<span class="trend up">▲</span> more than a typical day by {at} (a typical day has nothing yet)')
        else:
            ratio = total / expect
            kind, mark = ("up", "▲") if ratio >= 1.1 else ("down", "▼") if ratio <= .9 else ("flat", "●")
            vs = (f'<span class="trend {kind}">{mark} {ratio:.1f}×</span> a typical day by {at}' if kind != "flat" else
                  f'<span class="trend flat">● about</span> a typical day by {at}')
        vs = f'<p class="vs">{vs}</p>'
        chart = (f'<div class="today-chart">{_today_chart(typ, mine, x_now, total)}<div class="legend tlegend">'
                 f'<span class="key"><i class="tk band"></i>Middle half of days</span><span class="key"><i class="tk med"></i>Typical day (median of {typ["n"]} active days)</span>'
                 f'<span class="key"><i class="tk now"></i>Today</span></div></div>')
    else:
        vs = (f'<p class="vs note">A typical-day line appears once more than {MIN_HISTORY_DAYS} days have activity '
              f'({len([d for d in hours if d < clock.date()])} so far).</p>')
    body = f'<div class="today-top{" has-chart" if chart else ""}"><div class="today-main">{nums}{vs}</div>{chart}</div>'
    if last:
        sid, title, ts = last
        tk, prompts = conn.execute(f"SELECT sum({TOKENS}), count(DISTINCT prompt_idx) FROM requests WHERE session_id = ?",
                                   (sid,)).fetchone()
        turn = conn.execute(
            f"SELECT r.prompt_idx, p.text, max(r.skill), sum({TOKENS}) FROM requests r LEFT JOIN prompts p ON p.session_id = "
            f"r.session_id AND p.prompt_idx = r.prompt_idx WHERE r.session_id = ? AND r.prompt_idx IS NOT NULL "
            f"GROUP BY r.prompt_idx ORDER BY r.prompt_idx DESC LIMIT 1", (sid,)).fetchone()
        versions = skills.session_skill_versions(conn, sid)
        skill = turn[2] if turn else None
        tag = f' <code class="ver">{html.escape(versions[skill][:6])}</code>' if skill in versions else ""
        body += (f'<div class="latest"><span class="note">Latest session · <time data-ts="{html.escape(ts)}" data-fmt="hm">{html.escape(ts[11:16])} UTC</time></span>'
                 f'<a href="{f.link("sessions", q=sid[:8])}"><b>{html.escape(title or sid[:8])}</b></a>'
                 f'<span>{_tok(tk)} tokens · {prompts} prompts</span>'
                 + (f'<span class="note">#{turn[0]} {html.escape((turn[1] or "")[:110])}{" · " + html.escape(skill) + tag if skill else ""}'
                    f' · {_tok(turn[3])}</span>' if turn else "") + "</div>")
    else:
        body += "<p class='note'>Nothing yet today. Numbers appear here a few seconds after a turn ends.</p>"
    return body


def _movers(conn, f, cmp):
    """One table of the skills and subagent types whose tokens per day moved most against the window before the range,
    with one sentence that names the biggest cause."""
    if not cmp:
        if not f.days:
            return "<p class='note'>All time has no range before it. Pick a range to see the biggest movers.</p>"
        if _history_days(conn, f) <= MIN_HISTORY_DAYS:
            return f"<p class='note'>Biggest movers appear once there are more than {MIN_HISTORY_DAYS} days of history.</p>"
        return "<p class='note'>Less than a day of data before this range: nothing to compare yet.</p>"
    (cond, params), (pcond, pparams) = f.cond(), f.cond(1)
    rows = []
    for key, kind in (("r.skill", "skill"), ("r.agent_type", "subagent")):
        sql = f"SELECT {key}, sum({TOKENS}) FROM requests r JOIN sessions s USING (session_id) {{}} AND {key} IS NOT NULL GROUP BY 1"
        now, before = dict(_q(conn, sql.format(cond), params)), dict(_q(conn, sql.format(pcond), pparams))
        rows += [(k, kind, before.get(k, 0) / cmp["before"], now.get(k, 0) / cmp["now"]) for k in set(now) | set(before)]
    rows = sorted((r for r in rows if r[3] != r[2]), key=lambda r: -abs(r[3] - r[2]))[:6]
    if not rows:
        return "<p class='note'>Nothing moved.</p>"
    total_now, total_before = _totals(conn, cond, params)[0] or 0, _totals(conn, pcond, pparams)[0] or 0
    up = total_now / cmp["now"] > total_before / cmp["before"] if total_before else True
    pct = f" {abs(total_now / cmp['now'] / (total_before / cmp['before']) - 1):.0%}" if total_before else ""
    # the cause is the biggest mover that went the same way as the total; none did when the rest is main-thread tokens that no
    # skill or subagent type accounts for
    pick = next((r for r in rows if (r[3] > r[2]) == up), None)
    if pick:
        name, kind, was, now_pd = pick
        cause = (f'<p class="cause">Tokens per day {"rose" if up else "fell"}{pct}. Biggest cause: <b>{html.escape(name)}</b> ({kind}), '
                 f'{"+" if now_pd > was else "−"}{_tok(abs(now_pd - was))} a day.</p>')
    else:
        cause = (f'<p class="cause">Tokens per day {"rose" if up else "fell"}{pct}, mostly main-thread tokens that no skill or '
                 f'subagent type accounts for.</p>')
    body = "".join(f'<tr><td title="{html.escape(k)}">{html.escape(k)}</td><td class="tagc"><span class="tag">{kind}</span></td>'
                   f'<td>{_tok(b) if b else "–"}</td><td>{_tok(a) if a else "–"}</td><td>{charts.change_text(b, a)}</td></tr>'
                   for k, kind, b, a in rows)
    return (f'{cause}<table class="movers"><tr><th>Name</th><th>Kind</th><th>Before / day</th><th>Now / day</th><th>Change</th></tr>'
            f'{body}</table>')


def _new_versions(conn, f):
    """Versions first seen in the range that replaced an earlier one (a skill's first sight is not a change)."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'skill_versions'").fetchone():
        return "<p class='note'>No skill versions yet.</p>"
    since = _iso(f.now - timedelta(days=f.days)) if f.days else ""
    rows = _q(conn, "SELECT v.skill, v.version, v.first_seen, v.label FROM skill_versions v WHERE v.source != 'transcript' "
                    "AND v.first_seen >= ? AND EXISTS (SELECT 1 FROM skill_versions o WHERE o.skill = v.skill AND o.version != v.version "
                    "AND o.first_seen < v.first_seen) "
                    "ORDER BY v.first_seen DESC LIMIT 6", (since,))
    if not rows:
        return "<p class='note'>No skill changed in this range.</p>"
    ids = {}
    for k in library.discover(conn, f.project or None):
        for key in (k["dir"], k["name"]):
            ids.setdefault(key, k["id"])  # a personal copy wins, as it does when Claude Code loads the skill

    def href(sk):  # a plugin:skill links to the skill of that name, a frontmatter name to its folder
        i = ids.get(sk) or ids.get(sk.split(":", 1)[-1])
        return f'/library?skill={i}#v-{html.escape(sk)}' if i else "/library"
    items = "".join(f'<li><a href="{href(sk)}">{html.escape(sk)}</a> <code class="ver">{v[:6]}</code>'
                    f'{" v" + html.escape(lbl) if lbl else ""} <span class="note">{first[:10]}</span></li>' for sk, v, first, lbl in rows)
    return f'<ul class="plain">{items}</ul>'


def _top(conn, f):
    cond, params = f.cond()
    base = f"FROM requests r JOIN sessions s USING (session_id) {cond}"
    total = conn.execute(f"SELECT sum({TOKENS}) {base}", params).fetchone()[0] or 1
    share = lambda t: (f"{(t or 0) / total:.0%}", "lm")  # noqa: E731
    sk = _q(conn, f"SELECT skill, sum({TOKENS}) {base} AND skill IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 5", params)
    ag = _q(conn, f"SELECT agent_type, sum({TOKENS}) {base} AND agent_id IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 5", params)
    se = _q(conn, f"SELECT session_id, max(s.title), sum({TOKENS}) {base} GROUP BY 1 ORDER BY 3 DESC LIMIT 5", params)
    link = lambda href, text: (f'<a href="{href}" title="{html.escape(text)}">{html.escape(text)}</a>', "raw")  # noqa: E731
    rows = [("Skills", "skill", [(link(f.link("overview", skill=k), k), t, share(t)) for k, t in sk]),
            ("Subagent types", "type", [((f'<span title="{html.escape(k)}">{html.escape(k)}</span>', "raw"), t, share(t)) for k, t in ag]),
            ("Sessions", "session", [(link(f.link("sessions", q=sid[:8]), (title or sid[:8])[:44]), t, share(t)) for sid, title, t in se])]
    rows = [r for r in rows if r[2]]
    if not rows:
        return '<section class="card spenders"><h2>Top spenders</h2><p class="note">Nothing in this range.</p></section>'
    # a column with fewer rows leaves a hole under it, so the columns show one row more than the shortest (at most 5)
    keep = min(5, min(len(r[2]) for r in rows) + 1)
    return (f'<section class="card spenders"><h2 title="Each column shows at most {keep} rows so the three stay level">Top spenders</h2>'
            f'<div class="cols3" style="--n:{len(rows)}">'
            + "".join(f'<div class="col"><h3>{h}</h3>{_table([k, "tokens", "share"], r[:keep], 1)}</div>' for h, k, r in rows) + "</div></section>")


def _version_marks(conn, f, first, last):
    """Skill versions first seen on a day of the chart that replaced an earlier one: [(day, skill, version, label)]."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'skill_versions'").fetchone():
        return []
    rows = _q(conn, "SELECT substr(v.first_seen,1,10), v.skill, v.version, v.label FROM skill_versions v WHERE v.source != 'transcript' "
                    "AND substr(v.first_seen,1,10) BETWEEN ? AND ? AND EXISTS (SELECT 1 FROM skill_versions o WHERE o.skill = v.skill "
                    "AND o.version != v.version AND o.first_seen < v.first_seen) ORDER BY v.first_seen LIMIT 8", (first, last))
    return rows


def _daily_stacked(rows, changes, versions):
    """Tokens per day, main thread under subagents in each bar; a dashed line marks a skill version change (or a recorded
    config change), the mustard line is the 7-day average of the day's total. A second copy of the chart, the last 14 days
    on a narrow canvas with 4 day labels, is what a phone shows (layout.py /* phone */ swaps the two)."""
    if not rows:
        return "<p class='note'>No data.</p>"
    by_day = {d: (t or 0, m or 0, u or 0) for d, t, u, _s, _o, _r, _c, m in rows}
    first, last = date.fromisoformat(rows[0][0]), date.fromisoformat(rows[-1][0])
    # every calendar day from the first to the last, a day off as an empty slot, so the axis is time and the average is per day
    days = []
    for k in range((last - first).days + 1):
        d = (first + timedelta(days=k)).isoformat()
        t, m, u = by_day.get(d, (0, 0, 0))
        days.append((d, t, m, u))
    legend = ('<div class="legend"><span class="key"><i></i>Main thread</span><span class="key"><i class="a"></i>Subagents</span>'
              '<span class="key"><i class="ln"></i>7-day average</span>'
              + ('<span class="key"><i class="dash"></i>Skill version changed</span>' if versions else "") + "</div>")
    return (legend + _daily_svg(days, changes, versions, 1100, 240, 56, 8, "wide")
            + _daily_svg(days[-14:], changes, versions, 340, 200, 44, 4, "narrow"))


def _daily_svg(days, changes, versions, w, h, pad_l, labels, cls):
    pad_b, pad_t = 22, 34  # the top pad holds the two staggered rows of change labels
    top = max(t for _, t, _, _ in days) or 1
    step = (w - pad_l) / len(days)
    bw = max(2, step - 2)
    index = {d: i for i, (d, _t, _m, _u) in enumerate(days)}
    ph = h - pad_t - pad_b
    out = [f'<svg class="{cls}" viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Tokens per day, main thread and subagents">'
           f'<line class="guide" x1="0" x2="0" y1="{pad_t}" y2="{h - pad_b}"/>']
    for frac in (0, 0.5, 1):
        y = pad_t + ph * (1 - frac)
        out.append(f'<line class="g" x1="{pad_l}" x2="{w}" y1="{y:.1f}" y2="{y:.1f}"/>'
                   f'<text x="{pad_l - 6}" y="{y + 4:.1f}" text-anchor="end">{_tok(top * frac)}</text>')
    # labels: every n-th day on the wide chart; `labels` days spread from the first to the last on the narrow one
    narrow = cls == "narrow"
    marked = {round(k * (len(days) - 1) / (labels - 1)) for k in range(labels)} if narrow and len(days) >= labels else set()
    for i, (day, total, main, usd) in enumerate(days):
        x = pad_l + i * step
        sub = total - main
        hm, hs = ph * main / top, ph * sub / top
        tip = html.escape(f"<b>{day}</b><br>{_tok(total)} tokens<br>main {_tok(main)} · subagents {_tok(sub)}<br>"
                          f"<span class='usd'>{_usd(usd)} API-eq</span>")
        out.append(f'<g class="d" data-tip="{tip}"><rect class="hit" x="{x:.1f}" y="{pad_t}" width="{step:.1f}" height="{ph}"/>'
                   f'<rect class="m" x="{x:.1f}" y="{h - pad_b - hm:.1f}" width="{bw:.1f}" height="{hm:.1f}"/>'
                   + (f'<rect class="m a" x="{x:.1f}" y="{h - pad_b - hm - hs:.1f}" width="{bw:.1f}" height="{hs:.1f}"/>' if hs > 0 else "") + "</g>")
        if (i in marked) if narrow else i % max(1, len(days) // labels) == 0:
            anchor = "start" if marked and i == min(marked) else "end" if marked and i == max(marked) else "middle"
            lx = x if anchor == "start" else x + bw if anchor == "end" else x + bw / 2
            out.append(f'<text x="{lx:.1f}" y="{h - 6}" text-anchor="{anchor}">{day[5:]}</text>')
    vals = [t for _, t, _, _ in days]
    pts = []
    for i in range(len(days)):
        window = vals[max(0, i - 6):i + 1]
        pts.append(f"{pad_l + i * step + bw / 2:.1f},{h - pad_b - ph * (sum(window) / len(window)) / top:.1f}")
    if len(pts) > 1:
        out.append(f'<polyline class="ma" pathLength="1" points="{" ".join(pts)}"/>')
    # every calendar day has a slot, so a version sits on its own day; the narrow copy drops the ones before its 14 days
    nxt = lambda day: next((i for d, i in sorted(index.items()) if d >= day), None)  # noqa: E731
    short = 9 if narrow else 18
    marks = [(i, f"{charts.short(sk, short)} {v[:6]}", f"<b>{html.escape(sk)}</b> changed<br>version {v[:6]}{' v' + html.escape(lbl) if lbl else ''}")
             for day, sk, v, lbl in versions if (i := nxt(day)) is not None and (not narrow or day >= days[0][0])]
    marks += [(index[tz.local_day(at)], f"#{cid}", f"<b>change #{cid}</b><br>{html.escape(note)}") for cid, at, note, *_ in changes if tz.local_day(at) in index]
    for n, (i, text, tip) in enumerate(sorted(marks)):
        x = pad_l + i * step + bw / 2
        end = x > w - (110 if narrow else 150)
        out.append(f'<g class="vmark" data-tip="{html.escape(tip)}"><line class="chg" x1="{x:.1f}" x2="{x:.1f}" y1="{pad_t - 8 - 12 * (n % 2)}" y2="{h - pad_b}"/>'
                   f'<text class="chg-l" x="{x + (-4 if end else 4):.1f}" y="{pad_t - 12 * (n % 2) - 12}" text-anchor="{"end" if end else "start"}">{html.escape(text)}</text></g>')
    out.append("</svg>")
    return "".join(out)


def _running():
    """Sessions open right now: the count, how many are working, a pulsing dot while any is (files, not the database)."""
    open_ = live.running()
    busy = sum(s["status"] == "busy" for s in open_)
    if not open_:
        return '<p class="runnow none"><span class="dot off"></span>No Claude Code session is open</p>'
    by = {}
    for s in open_:
        by[s["entry"]] = by.get(s["entry"], 0) + 1
    where = " · ".join(f"{n} in {e}" for e, n in sorted(by.items()))
    return (f'<p class="runnow"><span class="dot live{" busy-now" if busy else ""}"></span><b data-count="{len(open_)}" data-kind="int" '
            f'data-key="running">{len(open_)}</b> <span class="lbl">session{"s" if len(open_) != 1 else ""} running</span>'
            f'<span class="note">{busy} working · {len(open_) - busy} waiting for you · {html.escape(where)}</span></p>')


def _budget_row(i):
    pct = i["pct"]
    detail = i["text"] if pct is None else i["text"].split("(", 1)[1].rstrip(")")
    width = min(pct or 0, 100)
    return (f'<li class="bgt {i["state"]}"><span class="bl">{html.escape(i["label"])}</span>'
            f'<i class="bt" role="img" aria-label="{html.escape(i["text"])}"><u style="width:{width:.1f}%"></u></i>'
            f'<b>{"–" if pct is None else format(pct, ".0f") + "%"}</b><span class="note">{html.escape(detail)}</span></li>')


def _budgets(conn):
    """Budget bars from budgets.json: today's spend against each limit. Nothing without the file; a bad file says why."""
    try:
        found = budgets.load()
    except budgets.BudgetError as e:
        return f'<section class="card"><h2>Budgets</h2><p class="note" role="alert">{html.escape(str(e))}</p></section>'
    if found is None:
        return ""
    result = budgets.check(conn, found)
    note = f'<p class="note">{html.escape(result["note"])}</p>' if result.get("note") else ""
    return (f'<section class="card budgets"><h2>Budgets</h2><p class="note">Today ({tz.label()}) against budgets.json; '
            f'yellow from {budgets.NEAR_PCT}%, red when over. <code>tokscope check --once</code> prints the same.</p>'
            f'<ul class="plain">{"".join(_budget_row(i) for i in result["items"])}</ul>{note}</section>')


def _cache_finding(conn, f):
    """One line when the last 7 days re-cached the prompt: the dollars and the top likely cause. Nothing without a miss."""
    cond, params = f.cond()
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    reqs, misses = cache.scan(conn, f"{cond} AND r.ts >= ?" if cond else "WHERE r.ts >= ?", (*params, since))
    if not misses:
        return ""
    t = cache.totals(reqs, misses)
    return (f'<section class="card cache-finding"><h2>Prompt cache</h2><p class="note">{_usd(t["recache_usd"])} of re-cache in the '
            f'last 7 days ({t["misses"]:,} likely miss{"es" * (t["misses"] != 1)}, {_tok(t["recache_tokens"])} tokens), '
            f'top cause: {html.escape(t["top_cause"])}; hit ratio {cache.pct(t["hit_ratio"])}. '
            f'<a href="{f.link("breakdowns")}#cache">Prompt cache</a> has the hints.</p></section>')


def page_overview(conn, f):
    cmp = _window(conn, f)
    rows = _day_rows(conn, f)
    versions = _version_marks(conn, f, rows[0][0], rows[-1][0]) if rows else []
    return "".join([
        f'<section class="card answer live-card"><div class="live-head"><h2><span class="dot"></span>Today</h2><div data-region="running">{_running()}</div></div><div data-region="today">{_today(conn, f)}</div></section>',
        f'<div data-region="budgets">{_budgets(conn)}</div>',
        f'<div data-region="kpis">{_kpis(conn, f)}</div>',
        f'<div data-region="cache">{_cache_finding(conn, f)}</div>',
        '<div data-region="cost-check">'
        + cost_check(conn, *f.cond(), since=_iso(f.now - timedelta(days=f.days)) if f.days else None,
                     scoped=bool(f.project or f.model or f.skill)) + '</div>',
        _session_start(conn, f),
        f'<section class="card"><h2>Biggest movers</h2><p class="note">{f.label()}, tokens per day against the window before</p>'
        f'<div data-region="changed">{_movers(conn, f, cmp)}<h3>New skill versions</h3>{_new_versions(conn, f)}</div></section>',
        f'<section class="card" id="trend"><h2>Daily tokens</h2><p class="note">{f.label()}, days in {tz.label()}</p>'
        f'<div data-region="trend">{_daily_stacked(rows, list_changes(conn), versions)}</div></section>',
        f'<div data-region="top">{_top(conn, f)}</div>',
    ])
