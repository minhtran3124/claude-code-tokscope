"""Local live dashboard: `tokscope serve` answers on 127.0.0.1 only, reads the database on every request and ingests
new transcripts in the background, so the pages follow your work without a rebuild. The pages reuse the report's
sections; one filter bar (range, project, model, skill) scopes every number on a page, and lives in the URL.

Overview updates in place when new data lands (numbers count to their new value); the other pages offer a reload,
so a list you are reading does not move under you. /api/* returns the same numbers as JSON."""

import copy
import difflib
import hmac
import html
import json
import re
import secrets
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from . import charts, fonts, library, markdown, optimize, paths, privacy, projects, registry, skills
from .brand import FAVICON, MARK, favicon_link
from .changes import BENCH_PROJECT, list_changes
from .ingest import PROJECTS_DIR, connect, ingest
from .pricing import API_EQ_NOTE
from .report import (CSS, JS_BENCH, JS_CORE, JS_SESSIONS, JS_TREND, TOKENS, _benchmarks, _breakdowns, _change_cards,
                     _daily_chart, _diff_html, _more, _sessions_json, _skill_versions, _table, _tok, _usd)

PAGES = {"overview": "Overview", "projects": "Projects", "sessions": "Sessions", "skills": "Skills", "library": "Library",
         "benchmarks": "Benchmarks", "breakdowns": "Breakdowns"}
RANGES = {"7": "Last 7 days", "30": "Last 30 days", "90": "Last 90 days", "all": "All time"}


def _iso(dt):
    # transcript timestamps are '2026-10-20T14:59:27.168Z'; this prefix compares with them as text
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


class Filters:
    """The filter bar: a range in days (None = all time) and optional project, model and skill."""

    def __init__(self, qs):
        one = lambda k: (qs.get(k) or [""])[0].strip()  # noqa: E731
        days = one("range") or "30"
        self.range = days if days in RANGES else "30"
        self.days = None if self.range == "all" else int(self.range)
        self.project, self.model, self.skill = one("project"), one("model"), one("skill")
        self.now = datetime.now(timezone.utc)

    def cond(self, shift=0):
        """(WHERE clause, params) for the report's helpers; shift=1 is the same-length range just before."""
        clauses, params = [f"s.project NOT LIKE '{BENCH_PROJECT}'"], []
        if self.days:
            end = self.now - timedelta(days=self.days * shift)
            clauses.append("r.ts >= ?")
            params.append(_iso(end - timedelta(days=self.days)))
            if shift:
                clauses.append("r.ts < ?")
                params.append(_iso(end))
        for col, value in (("s.project", self.project), ("r.model", self.model), ("r.skill", self.skill)):
            if value:
                clauses.append(f"{col} = ?")
                params.append(value)
        return "WHERE " + " AND ".join(clauses), tuple(params)

    def link(self, page, **change):
        q = self.query(**change)
        return f"/{page}?{q}" if q else f"/{page}"

    def query(self, **change):
        keep = {"range": self.range, "project": self.project, "model": self.model, "skill": self.skill, **change}
        return urlencode({k: v for k, v in keep.items() if v and not (k == "range" and v == "30")})

    def label(self):
        return RANGES[self.range].lower() if self.days else "all time"


def _q(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def _totals(conn, cond, params):
    base = f"FROM requests r JOIN sessions s USING (session_id) {cond}"
    return conn.execute(
        f"SELECT sum({TOKENS}), sum(cost_usd), count(DISTINCT session_id), sum(output), "
        f"count(DISTINCT CASE WHEN agent_id IS NOT NULL THEN session_id || agent_id END), sum(cache_read) {base}", params).fetchone()


def _spark(values, w=96, h=22):
    if len(values) < 2 or not max(values):
        return ""
    top = max(values)
    pts = " ".join(f"{w * i / (len(values) - 1):.1f},{h - 2 - (h - 4) * v / top:.1f}" for i, v in enumerate(values))
    return f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true"><polyline points="{pts}"/></svg>'


def _delta(now, before, label, history=None):
    """The change against the range before; `history` (the first day with data) when too little of that range has data."""
    if history:
        return f'<span class="dl note">history starts {history}: too short to compare</span>'
    if not before or now is None:
        return f'<span class="dl note">nothing in {label} to compare</span>' if label else ""
    pct = now / before - 1
    text = f"×{now / before:,.0f}" if pct >= 9.995 else f"{pct:+.0%}"  # +1,000% and up read better as a multiple
    return f'<span class="dl"><span class="trend {"up" if pct > 0 else "down"}">{text}</span> vs {label}</span>'


def _history_start(conn, f):
    """The first request the filters can see, over all time."""
    whole = copy.copy(f)
    whole.days = None
    cond, params = whole.cond()
    return conn.execute(f"SELECT min(r.ts) FROM requests r JOIN sessions s USING (session_id) {cond}", params).fetchone()[0]


def _kpis(conn, f):
    cond, params = f.cond()
    now = _totals(conn, cond, params)
    before = _totals(conn, *f.cond(1)) if f.days else (None,) * 6
    days = _days(conn, f)
    daily, usd_daily = [t or 0 for _, t, _ in days], [u or 0 for _, _, u in days]
    prev = f"the {f.days} days before" if f.days else ""
    # the range before is a fair baseline only when data covers at least half of it; else +440,571% says nothing
    start = _history_start(conn, f) if f.days else None
    short = start[:10] if start and start[:19] > _iso(f.now - timedelta(days=f.days * 1.5)) else None
    cache = lambda t: round(100 * (t[5] or 0) / (t[0] or 1)) if t[0] else None  # noqa: E731
    tiles = [("tokens", "Tokens", now[0] or 0, _tok(now[0]), "tok", before[0], daily),
             ("usd", "API-eq", round(now[1] or 0, 2), _usd(now[1]), "usd", before[1], usd_daily),
             ("sessions", "Sessions", now[2] or 0, f"{now[2] or 0:,}", "int", before[2], None),
             ("output", "Output tokens", now[3] or 0, _tok(now[3]), "tok", before[3], None),
             ("runs", "Subagent runs", now[4] or 0, f"{now[4] or 0:,}", "int", before[4], None),
             ("cache", "From cache", cache(now) or 0, f"{cache(now) or 0}%", "pct", cache(before) if f.days else None, None)]
    out = []
    for i, (key, label, raw, text, kind, was, series) in enumerate(tiles):
        title = f' title="{html.escape(API_EQ_NOTE)}"' if key == "usd" else ""
        out.append(f'<div class="kpi" style="--i:{i}"{title}><span>{label}</span>'
                   f'<b data-count="{raw}" data-kind="{kind}" data-key="{key}">{text}</b>'
                   f'{_spark(series) if series else ""}{_delta(raw, was, prev, short)}</div>')
    return f'<div class="kpis">{"".join(out)}</div>'


def _days(conn, f):
    cond, params = f.cond()
    return _q(conn, f"SELECT substr(r.ts,1,10) d, sum({TOKENS}), sum(cost_usd) FROM requests r JOIN sessions s "
                    f"USING (session_id) {cond} GROUP BY d ORDER BY d", params)


def _local_midnight():
    return datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)


def _today(conn, f):
    """Today (local midnight on) and the latest session, whatever the range; project/model/skill still apply."""
    today = Filters({"range": ["all"], "project": [f.project], "model": [f.model], "skill": [f.skill]})
    cond, params = today.cond()
    cond, params = f"{cond} AND r.ts >= ?", (*params, _iso(_local_midnight()))
    tokens, usd, n, _, _, _ = _totals(conn, cond, params)
    last = conn.execute(
        f"SELECT session_id, s.title, max(r.ts) FROM requests r JOIN sessions s USING (session_id) {cond} "
        f"GROUP BY session_id ORDER BY 3 DESC LIMIT 1", params).fetchone()
    body = (f'<div class="today-nums"><div><span>Tokens today</span><b data-count="{tokens or 0}" data-kind="tok" data-key="today-tokens">'
            f'{_tok(tokens)}</b></div><div><span>API-eq today</span><b data-count="{round(usd or 0, 2)}" data-kind="usd" '
            f'data-key="today-usd">{_usd(usd)}</b></div><div><span>Sessions today</span><b data-count="{n or 0}" data-kind="int" '
            f'data-key="today-sessions">{n or 0}</b></div></div>')
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
        body += (f'<div class="latest"><span class="note">Latest session · <time data-ts="{ts}">{ts[11:16]} UTC</time></span>'
                 f'<a href="{f.link("sessions", q=sid[:8])}"><b>{html.escape(title or sid[:8])}</b></a>'
                 f'<span>{_tok(tk)} tokens · {prompts} prompts</span>'
                 + (f'<span class="note">#{turn[0]} {html.escape((turn[1] or "")[:110])}{" · " + html.escape(skill) + tag if skill else ""}'
                    f' · {_tok(turn[3])}</span>' if turn else "") + "</div>")
    else:
        body += "<p class='note'>Nothing yet today. Numbers appear here a few seconds after a turn ends.</p>"
    return body


def _movers(conn, f, key, label, n=3):
    if not f.days:
        return f"<p class='note'>Pick a range to compare {label} against the one before.</p>"
    (cond, params), (pcond, pparams) = f.cond(), f.cond(1)
    sql = f"SELECT {key}, sum({TOKENS}) FROM requests r JOIN sessions s USING (session_id) {{}} AND {key} IS NOT NULL GROUP BY 1"
    now, before = dict(_q(conn, sql.format(cond), params)), dict(_q(conn, sql.format(pcond), pparams))
    deltas = sorted(((k, before.get(k, 0), now.get(k, 0)) for k in set(now) | set(before)), key=lambda r: r[2] - r[1])
    picked = [r for r in deltas[::-1][:n] if r[2] > r[1]] + [r for r in deltas[:n] if r[2] < r[1]]
    if not picked:
        return f"<p class='note'>No {label} moved.</p>"
    rows = [(k, (_tok(b) if b else "–", "lm"), a, (charts.change_text(b, a) if a else "gone", "lm")) for k, b, a in picked]
    return _table([label, "before", "now", "change"], rows, 2)


def _new_versions(conn, f):
    """Versions first seen in the range that replaced an earlier one (a skill's first sight is not a change)."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'skill_versions'").fetchone():
        return "<p class='note'>No skill versions yet.</p>"
    since = _iso(f.now - timedelta(days=f.days)) if f.days else ""
    rows = _q(conn, "SELECT v.skill, v.version, v.first_seen, v.label FROM skill_versions v WHERE v.source != 'transcript' "
                    "AND v.first_seen >= ? AND EXISTS (SELECT 1 FROM skill_versions o WHERE o.skill = v.skill AND o.version != v.version) "
                    "ORDER BY v.first_seen DESC LIMIT 6", (since,))
    if not rows:
        return "<p class='note'>No skill changed in this range.</p>"
    items = "".join(f'<li><a href="{f.link("skills")}#v-{html.escape(sk)}">{html.escape(sk)}</a> <code class="ver">{v[:6]}</code>'
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
    cols = [("Skills", _table(["skill", "tokens", "share"], [(link(f.link("overview", skill=k), k), t, share(t)) for k, t in sk], 1)),
            ("Subagent types", _table(["type", "tokens", "share"], [((f'<span title="{html.escape(k)}">{html.escape(k)}</span>', "raw"), t, share(t))
                                                                    for k, t in ag], 1)),
            ("Sessions", _table(["session", "tokens", "share"],
                                [(link(f.link("sessions", q=sid[:8]), (title or sid[:8])[:44]), t, share(t)) for sid, title, t in se], 1))]
    return '<div class="cols3">' + "".join(f'<section class="card"><h3>{h}</h3>{t}</section>' for h, t in cols) + "</div>"


def page_overview(conn, f):
    return "".join([
        f'<div data-region="kpis">{_kpis(conn, f)}</div>',
        '<div class="cols2">',
        f'<section class="card live-card"><h2><span class="dot"></span>Today</h2><div data-region="today">{_today(conn, f)}</div></section>',
        f'<section class="card"><h2>What changed</h2><p class="note">{f.label()} against the range before</p>'
        f'<div data-region="changed"><h3>Skills</h3>{_movers(conn, f, "r.skill", "skill")}'
        f'<h3>Subagent types</h3>{_movers(conn, f, "r.agent_type", "subagent type")}'
        f'<h3>New skill versions</h3>{_new_versions(conn, f)}</div></section>',
        "</div>",
        f'<section class="card" id="trend"><h2>Daily tokens</h2><p class="note">{f.label()}; the mustard line is the 7-day average</p>'
        f'<div data-region="trend">{_daily_chart(_days(conn, f), list_changes(conn))}</div></section>',
        f'<h2 class="sec">Top spenders</h2><div data-region="top">{_top(conn, f)}</div>',
    ])


def page_sessions(conn, f, qs):
    cond, params = f.cond()
    data = json.dumps(_sessions_json(conn, cond, params), separators=(",", ":")).replace("</", "<\\/")
    prefill = html.escape((qs.get("q") or [""])[0])
    return (f'<section class="card" id="sessions"><p class="note"><span class="key"><i></i>main thread</span><span class="key">'
            f'<i class="a"></i>subagents</span> Sessions with activity in {f.label()}. Open a row for each prompt; tick 2 to 4 to compare.</p>'
            f'<div class="tools"><input type="search" id="s-q" value="{prefill}" placeholder="Filter by title, skill or session id  ( / )">'
            '<select id="s-sort"><option value="recent">Newest first</option><option value="tokens">Most tokens first</option></select>'
            '<span class="note" id="s-count"></span></div><section class="card" id="compare"><h3>Compare</h3>'
            '<p class="note">Bold = fewest. Tokens per prompt evens out sessions of different length.</p><table></table></section>'
            '<div id="session-list"></div><div class="pickbar" id="pickbar" hidden><span id="pick-hint"></span><span class="acts">'
            '<button class="btn" id="clear-pick">Clear</button><button class="primary" id="do-compare" disabled>Compare</button></span></div>'
            '<p><button class="btn" id="s-more">Show more</button></p></section>'
            f'<script type="application/json" id="sessions-data">{data}</script>')


def page_skills(conn, f, level):
    _, inner = _skill_versions(conn, level)
    return f'<section class="card" id="skill-versions"><p class="note">Every skill version tokscope has seen, all time.</p>{inner}</section>'


def _ste_counts(findings):
    h = library.hard(findings)
    return f'<span class="ste-n" title="STE check: {h} hard findings, {len(findings) - h} hints">STE {h} · {len(findings) - h} hints</span>'


def _skill_card(k, used, lint=None):
    loads, last = used.get(k["dir"], (0, None))
    findings = (lint or {}).get(k["folder"] / "SKILL.md")
    meta = (f"{loads:,} load{'s' * (loads != 1)}" + (f" · last {last[:10]}" if last else "")
            + (f" · {_ste_counts(findings)}" if findings is not None else ""))
    keys = f' data-loads="{loads}" data-ste="{library.hard(findings) if findings is not None else -1}"' 
    badge = f'<span class="badge inst" title="{html.escape(k["reason"])}">installed</span>' if k["origin"] == "installed" else ""
    hide = " hidden" if k["origin"] == "installed" else ""
    return (f'<a class="sk" href="/library?skill={k["id"]}" data-origin="{k["origin"]}"{keys} '
            f'data-find="{html.escape((k["name"] + " " + k["description"]).lower())}"{hide}>'
            f'<b>{html.escape(k["name"])}{badge}</b><p title="{html.escape(k["description"])}">{markdown.inline(k["description"]) or "<i>No description.</i>"}</p>'
            f'<span class="meta">{meta}</span></a>')


def _library_list(found, used, lint=None, lint_note=""):
    if not found:
        return ('<div class="empty"><b>No skills found</b>tokscope looks in ~/.claude/skills and in the .claude/skills '
                'folder of every project a session ran in.</div>')
    installed = sum(k["origin"] == "installed" for k in found)
    tools = ('<div class="tools libtools"><input type="search" id="lib-find" placeholder="Find a skill" aria-label="Find a skill">'
             + (f'<label class="chip"><input type="checkbox" id="lib-inst"> Show installed ({installed})</label>' if installed else "")
             + '<select id="lib-sort" aria-label="Sort skills"><option value="">By name</option><option value="loads">Most loads</option>'
             + ('<option value="ste">Most STE findings</option>' if lint else "") + '</select></div>')
    groups = []
    for scope in dict.fromkeys(k["scope"] for k in found):
        ks = [k for k in found if k["scope"] == scope]
        mine = sum(k["origin"] == "mine" for k in ks)
        title = "Personal · ~/.claude/skills" if scope == "personal" else f"Project · {scope}"
        groups.append(f'<section class="libgroup"><h2 class="sec">{html.escape(title)} <span class="note">{mine} yours'
                      f'{f", {len(ks) - mine} installed" if len(ks) > mine else ""}</span></h2>'
                      f'<div class="libgrid">{"".join(_skill_card(k, used, lint) for k in ks)}</div></section>')
    return (f'<p class="note">Skills you wrote, to read. Installed ones (npx skills, a lock file, an installer) are hidden; '
            f'<code>library.json</code> in the data folder corrects a wrong guess.{lint_note}</p>{tools}{"".join(groups)}'
            '<div class="empty" id="lib-none" hidden><b>No skill matches</b>Try another word.</div>')


def _source(text, pane=""):
    """The file with numbered lines; each line is an anchor (#L12) the STE findings link to."""
    lines = "".join(f'<span class="ln" id="L{i}">{html.escape(line) or " "}</span>' for i, line in enumerate(text.split("\n"), 1))
    return f'<pre class="src"{f" data-pane={pane} hidden" if pane else ""}>{lines}</pre>'


def _marked(line, v):
    """The line with the finding's match marked: the occurrence nearest its column, else the line as it is."""
    m, col = (v.get("match") or "").lower(), max(0, int(v.get("col") or 1) - 1)
    low = line.lower()
    at = low.find(m, max(0, col - len(m))) if m else -1
    at = at if at >= 0 else (low.find(m) if m else -1)
    if at < 0:
        return html.escape(line)
    return f"{html.escape(line[:at])}<mark>{html.escape(line[at:at + len(m)])}</mark>{html.escape(line[at + len(m):])}"


def _ste_pane(findings, text, words, linter, error):
    if error or linter is None:
        why = (f"<b>STE check failed</b>{html.escape(error)}" if error else
               "<b>No STE linter</b>Install the asd-ste100 skill, or set TOKSCOPE_STE_LINT to a ste-lint.py file.")
        return f'<div data-pane="ste" hidden><div class="empty">{why}</div></div>'
    if not findings:
        return '<div data-pane="ste" hidden><div class="empty"><b>No STE findings</b>ste-lint found nothing to change.</div></div>'
    lines, h = text.split("\n"), library.hard(findings)
    rules = {}
    for v in findings:
        rules[v.get("rule", "?")] = rules.get(v.get("rule", "?"), 0) + 1
    items = []
    for v in sorted(findings, key=lambda v: (v.get("line") or 0, v.get("col") or 0)):
        n, hard = v.get("line") or 0, v.get("level") == "advisory-free"
        src = lines[n - 1] if 0 < n <= len(lines) else ""
        items.append(f'<li class="{"hard" if hard else "adv"}"><a class="lnk" href="#L{n}" data-goto="L{n}">L{n}</a>'
                     f'<span class="rule">{html.escape(v.get("rule", "?"))}</span><span class="lvl">{"hard" if hard else "hint"}</span>'
                     f'<code class="line">{_marked(src, v)}</code><span class="msg">{html.escape(v.get("message", ""))}</span></li>')
    by_rule = " · ".join(f"{html.escape(r)} {c}" for r, c in sorted(rules.items(), key=lambda rc: -rc[1]))
    return (f'<div data-pane="ste" hidden><p class="note">{h} hard, {len(findings) - h} hints · '
            f'{len(findings) * 100 / max(words, 1):.1f} per 100 words · {by_rule}. Hints are heuristics (passive voice, tenses): '
            f'read each one. Rules from <code>{html.escape(library._tilde(linter))}</code>.</p>'
            '<label class="chip"><input type="checkbox" id="ste-adv" checked> Show hints</label>'
            f'<ol class="ste">{"".join(items)}</ol></div>')


JOB_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{6}$")


def _optimize_panel(k, found):
    if k["origin"] != "mine":
        return '<p class="note">Installed skills cannot be optimized: the next update of the installer would undo the change.</p>'
    have = optimize.guides_available(found)
    if not have:
        return '<p class="note">To optimize, install one of these skills: ' + ", ".join(optimize.GUIDES) + ".</p>"
    notes = {"optimize-skill": "runs test prompts in subagents, so it costs more",
             "asd-ste100": "STE100 rewrite, checked with ste-lint", "unslop": "removes AI tells from the prose"}
    boxes = "".join(f'<label class="opt"><input type="checkbox" name="guide" value="{g}"{" checked" if g != "optimize-skill" else ""}'
                    f'{"" if g in have else " disabled"}> <b>{g}</b> <span class="note">{notes[g] if g in have else "not installed"}</span></label>'
                    for g in optimize.GUIDES)
    personal = ('<p class="note">This is a personal skill. Test prompts in the job load your personal copy, not the draft, '
                'so optimize-skill cannot test its own cuts.</p>' if k["scope"] == "personal" else "")
    models = "".join(f'<option value="{m}">{m or "default model"}</option>' for m in optimize.MODELS)
    return (f'<form class="optform" id="optimize" data-skill="{k["id"]}">{boxes}{personal}<div class="optrow">'
            f'<select name="model" aria-label="Model">{models}</select>'
            '<label>Spend at most $<input type="number" name="budget" value="2" min="0.5" max="50" step="0.5"></label>'
            '<button type="submit" class="primary">Optimize</button></div>'
            '<p class="note">Runs <code>claude -p</code> on a copy of the skill. The skill changes only when you apply the result.</p>'
            '<p class="err" id="opt-err" hidden></p></form>')


def _jobs_list(k):
    jobs = optimize.jobs_for(k["folder"])
    if not jobs:
        return ""
    rows = "".join(f'<li><a href="/library?skill={k["id"]}&amp;job={j["job"]}">{html.escape(j["started"][:16].replace("T", " "))}</a> '
                   f'<span class="state {j["state"]}">{j["state"]}</span> {html.escape(", ".join(j["guides"]))}'
                   f'{" · " + _usd(j["cost"]) if j.get("cost") is not None else ""}</li>' for j in jobs[:10])
    return f'<h3 class="sub3">Earlier runs</h3><ul class="plain jobs">{rows}</ul>'


def _measure(folder, rel, linter):
    """(words, ≈tokens, hard STE findings or None) of one Markdown file."""
    path = folder / rel
    if not path.is_file():
        return 0, 0, None
    text = path.read_text(errors="replace")
    hard = None
    if linter:
        try:
            hard = library.hard(library.ste_lint(linter, [path])[path])
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired):
            pass
    return len(markdown.frontmatter(text)[1].split()), len(text) // 4, hard


def _words(a, b):
    """The two lines with the changed words marked, so a one-word edit does not read as a new line."""
    wa, wb = re.split(r"(\s+)", a), re.split(r"(\s+)", b)
    left, right = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, wa, wb, autojunk=False).get_opcodes():
        x, y = html.escape("".join(wa[i1:i2])), html.escape("".join(wb[j1:j2]))
        left.append(x if tag == "equal" or not x.strip() else f"<mark>{x}</mark>")
        right.append(y if tag == "equal" or not y.strip() else f"<mark>{y}</mark>")
    join = lambda parts: re.sub(r"</mark>(\s+)<mark>", r"\1", "".join(parts))  # noqa: E731  one mark per changed run
    return join(left), join(right)


def _side_by_side(a, b):
    al, bl = a.splitlines(), b.splitlines()
    rows = []

    def row(i, left, j, right, kind, marked=None):
        lt, rt = marked or (html.escape(left), html.escape(right))
        lc = "del" if kind in ("replace", "delete") and i is not None else "gap" if i is None else ""
        rc = "add" if kind in ("replace", "insert") and j is not None else "gap" if j is None else ""
        rows.append(f'<tr><td class="n">{"" if i is None else i + 1}</td><td class="{lc}">{lt}</td>'
                    f'<td class="n">{"" if j is None else j + 1}</td><td class="{rc}">{rt}</td></tr>')

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, al, bl, autojunk=False).get_opcodes():
        if tag == "equal":
            n = i2 - i1
            for k in (range(n) if n <= 6 else (0, 1, None, n - 2, n - 1)):  # a long unchanged run folds to its ends
                if k is None:
                    rows.append(f'<tr class="fold"><td colspan="4">… {n - 4} unchanged lines</td></tr>')
                else:
                    row(i1 + k, al[i1 + k], j1 + k, bl[j1 + k], "equal")
            continue
        for k in range(max(i2 - i1, j2 - j1)):
            i = i1 + k if i1 + k < i2 else None
            j = j1 + k if j1 + k < j2 else None
            left, right = al[i] if i is not None else "", bl[j] if j is not None else ""
            row(i, left, j, right, tag, _words(left, right) if i is not None and j is not None else None)
    return ('<table class="sbs"><colgroup><col class="n"><col><col class="n"><col></colgroup>'
            '<thead><tr><th></th><th>Before</th><th></th><th>After</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def _compare(rel, kind, lines, old_dir, new_dir):
    read = lambda d: (d / rel).read_text(errors="replace") if (d / rel).is_file() else ""  # noqa: E731
    old, new = read(old_dir), read(new_dir)
    tabs = [("sbs", "Side by side"), ("diff", "Diff")] + ([("after", "After"), ("before", "Before")] if rel.endswith(".md") else [])
    seg = "".join(f'<button type="button" class="chip{" on" if i == 0 else ""}" data-cmp="{t}">{label}</button>'
                  for i, (t, label) in enumerate(tabs))
    panes = (f'<div data-cmp-pane="sbs">{_side_by_side(old, new)}</div><div data-cmp-pane="diff" hidden>{_diff_html(lines)}</div>'
             + (f'<div data-cmp-pane="after" class="md" hidden>{markdown.render(markdown.frontmatter(new)[1])}</div>'
                f'<div data-cmp-pane="before" class="md" hidden>{markdown.render(markdown.frontmatter(old)[1])}</div>'
                if rel.endswith(".md") else ""))
    return (f'<section class="card cmp"><div class="viewbar"><h3 class="path">{html.escape(rel)} <span class="note">{kind}</span></h3>'
            f'<span class="seg" role="group" aria-label="Compare">{seg}</span></div>{panes}</section>')


def _bench_section(job, data, conn):
    skill = data["skill"]
    try:
        skills.check_pinnable(skill)
    except ValueError as e:
        return (f'<section class="card" id="bench"><h2 class="sec">Benchmark</h2><p class="note">This skill cannot be benchmarked: '
                f'{html.escape(str(e))}.</p></section>')
    b = optimize.bench_status(job)
    tasks = optimize.bench_tasks(skill)
    body = ""
    if b.get("state") == "running":
        body = ('<p class="runline"><span class="spin"></span>The benchmark is going: '
                f'<b>{b["runs"]}</b> run{"s" * (b["runs"] != 1)} of each version on <code>{html.escape(b["task"])}</code>, '
                f'at most {_usd(b["cap"])} in all.</p><div class="runbar" aria-hidden="true"><i></i></div>'
                f'<pre class="src" id="bench-log">{html.escape(chr(10).join(b["log"])) or "starting…"}</pre>')
    elif b.get("state") in ("done", "failed", "interrupted"):
        res = optimize.bench_results(job, conn.execute("PRAGMA database_list").fetchone()[2])
        trs = "".join(f'<tr><td>{r["label"]} <code>{r["version"][:8]}</code></td><td>{r["passed"]}/{r["runs"]}</td><td>{r["errors"]}</td>'
                      f'<td>{_usd(r["cost"]) if r["cost"] is not None else "–"}</td><td>{_tok(r["tokens"]) if r["tokens"] else "–"}</td>'
                      f'<td>{_dur(r["seconds"]) if r["seconds"] else "–"}</td>'
                      f'<td>{html.escape(", ".join(f"{k} {n}" for k, n in sorted(r["checks"].items())))}</td></tr>' for r in res)
        verdict = ""
        if len(res) == 2 and res[0]["runs"] and res[1]["runs"]:
            cur, new = res
            bits = [f'pass {new["passed"]}/{new["runs"]} vs {cur["passed"]}/{cur["runs"]}']
            for key, word in (("cost", "cost"), ("tokens", "tokens")):
                if cur[key] and new[key]:
                    bits.append(f"{word} {new[key] / cur[key] - 1:+.0%}")
            verdict = (f'<p class="verdict"><b>Draft against current:</b> {", ".join(bits)}. Medians of {cur["runs"]} '
                       f'and {new["runs"]} runs: a small sample, so read it with the diff.</p>')
        state = "" if b["state"] == "done" else f'<p class="err">The benchmark {b["state"]}: {html.escape(b.get("error") or "")}</p>'
        body = (state + verdict + '<table class="bres"><thead><tr><th>Version</th><th>Pass</th><th>Errors</th><th>Median $</th>'
                '<th>Median tokens</th><th>Median time</th><th>Skill check</th></tr></thead>'
                f'<tbody>{trs}</tbody></table><p class="note">Task <code>{html.escape(b["task"])}</code>. '
                'Skill check "ok" means the run read the pinned version.</p>')
    form = ""
    if b.get("state") != "running":
        opts = "".join(f'<option value="{html.escape(n)}" data-cap="{cap}">{html.escape(n)}{" · uses this skill" if uses else ""}</option>'
                       for n, _, cap, uses in tasks)
        runs = "".join(f'<option value="{n}"{" selected" if n == 2 else ""}>{n} per version</option>' for n in optimize.BENCH_RUNS)
        form = ((f'<form class="optrow" id="bench-form"><select name="task" aria-label="Task">{opts}</select>'
                 f'<select name="runs" aria-label="Runs">{runs}</select><button type="submit" class="primary">'
                 f'{"Run the benchmark again" if b.get("state") else "Run the benchmark"}</button>'
                 '<span class="note" id="bench-cap"></span></form>') if tasks else
                '<p class="note">No benchmark task yet. Make one below.</p>')
        form += ('<details class="more" id="task-new"' + ("" if tasks else " open") + '><summary><span class="ttl">Make a task for this skill</span>'
                 '<span class="note">a prompt that uses the skill, and words a good answer has</span></summary>'
                 '<form id="task-form" class="optform">'
                 f'<label class="wide">Prompt <textarea name="prompt" rows="3">/{html.escape(skill)} </textarea></label>'
                 '<label class="wide">Words a good answer has, comma-separated (the grader) <input name="grader" placeholder="CLAUDE_MODEL, ai_config"></label>'
                 '<div class="optrow"><label>Name <input name="name" value="' + html.escape(skill) + '-quick"></label>'
                 '<label>Paths to copy <input name="paths" value="." title="comma-separated; . copies the whole repository"></label>'
                 '<label>$ per run <input type="number" name="budget" value="1.5" min="0.25" max="10" step="0.25"></label></div>'
                 '<p class="note">The task runs in a copy of your repository at HEAD, with the skill version pinned in it. '
                 'Name only the paths the prompt needs: a smaller copy is quicker.</p>'
                 '<p><button type="submit" class="btn">Save the task</button></p></form></details>')
    return (f'<section class="card" id="bench" data-bench="{b.get("state") or ""}"><h2 class="sec">Benchmark</h2>'
            '<p class="note">Run one task on the current skill and on the draft, in fresh headless sessions, and compare pass rate, '
            'cost, tokens and time. It runs claude -p, so it costs money.</p>'
            f'{body}{form}<p class="err" id="bench-err" hidden></p></section>')


def _dur(seconds):
    m, sec = divmod(int(seconds or 0), 60)
    return f"{m}m {sec:02d}s" if m else f"{sec}s"


def _steps_html(job, started):
    shown, total, _ = optimize.steps(job)
    items = "".join(f'<li class="{st["kind"]}{" sub" if st.get("sub") else ""}"><time>+{_dur(st["t"] - started)}</time>'
                    f'<span>{html.escape(st["text"])}</span></li>' for st in shown)
    more = f'<p class="note">The last {len(shown)} of {total} steps.</p>' if total > len(shown) else ""
    return more + f'<ol class="steps" id="run-list">{items}</ol>'


def _job_view(k, job, linter, conn=None):
    data = optimize.status(job)
    base = f'/library?skill={k["id"]}'
    started = datetime.fromisoformat(data["started"]).timestamp()
    head = (f'<p><a href="{base}">← {html.escape(k["name"])}</a></p><section class="card libhead" id="job" data-job="{job}" '
            f'data-state="{data["state"]}" data-started="{started:.0f}"><h2 class="sec">Optimize run · '
            f'<span class="state {data["state"]}">{data["state"]}</span></h2>'
            f'<dl class="ids"><dt>Started</dt><dd>{html.escape(data["started"].replace("T", " "))}</dd>'
            f'<dt>Guides</dt><dd>{html.escape(", ".join(data["guides"]))}</dd><dt>Model</dt><dd>{html.escape(data["model"] or "default")}</dd>'
            f'<dt>Budget</dt><dd>{_usd(data["budget"])}{" · spent " + _usd(data["cost"]) if data.get("cost") is not None else ""}</dd></dl>')
    if data["state"] == "running":
        _, total, idle = optimize.steps(job)
        files = "".join(f"<li><code>{html.escape(rel)}</code> {kind}</li>" for rel, kind, _ in optimize.changes(job))
        return (head + '<div class="runbar" aria-hidden="true"><i></i></div>'
                f'<p class="runline"><span class="spin" aria-hidden="true"></span>claude -p is working on a copy · '
                f'<b id="run-elapsed">{_dur(time.time() - started)}</b> · <span id="run-count">{total} steps</span></p>'
                f'<p class="warn" id="run-idle"{"" if idle > 120 else " hidden"}>No new step for <span id="run-idle-s">{_dur(idle)}</span>. '
                'A long step (a subagent, a slow answer) can take minutes; if it stays, cancel the run.</p>'
                '<p class="acts"><button type="button" class="btn" data-job-act="cancel">Cancel the run</button></p>'
                '<p class="err" id="opt-err" hidden></p></section>'
                f'<section class="card"><h2 class="sec">Steps</h2>{_steps_html(job, started)}</section>'
                f'<section class="card"><h2 class="sec">Files changed so far</h2><ul class="plain" id="run-files">'
                f'{files or "<li class=note>none yet</li>"}</ul></section>')
    took = _dur(data.get("duration_s"))
    spent = f" · spent {_usd(data['cost'])}" if data.get("cost") is not None else ""
    log = _more("Steps", f"{optimize.steps(job)[1]} steps of the run", _steps_html(job, started), "run-steps")
    if data["state"] in ("failed", "interrupted", "cancelled"):
        word = {"failed": "✕ Failed", "interrupted": "✕ Interrupted", "cancelled": "■ Cancelled"}[data["state"]]
        cls = "off" if data["state"] == "cancelled" else "bad"
        return (head + f'<div class="outcome {cls}"><b>{word} after {took}{spent}</b>'
                f'<span>{html.escape(str(data.get("error") or "")[:1500])}</span></div>'
                '<p class="acts"><button type="button" class="btn" data-job-act="discard">Discard</button></p>'
                '<p class="err" id="opt-err" hidden></p></section>' + log)
    old_dir, new_dir = optimize.compared(job)
    changed = optimize.changes_between(old_dir, new_dir)
    rows, notes = [], []
    for rel, kind, _ in changed:
        if rel.endswith(".md"):
            a, b = _measure(old_dir, rel, linter), _measure(new_dir, rel, linter)
            ste = (f"{a[2] if a[2] is not None else '–'} → {b[2] if b[2] is not None else '–'}") if linter else "–"
            rows.append(f"<tr><td>{html.escape(rel)}</td><td>{kind}</td><td>{a[0]:,} → {b[0]:,}</td>"
                        f"<td>{_tok(a[1])} → {_tok(b[1])}</td><td>{ste}</td></tr>")
            notes.append(f"{rel}: {a[0]:,} → {b[0]:,} words" + (f", STE hard {ste}" if linter else ""))
        else:
            notes.append(f"{rel} {kind}")
    table = ('<table><thead><tr><th>File</th><th>Change</th><th>Words</th><th>≈Tokens</th><th>STE hard</th></tr></thead>'
             f'<tbody>{"".join(rows)}</tbody></table>') if rows else ""
    decide = ""
    if data["state"] == "applied":
        outcome = (f'<div class="outcome ok"><b>✓ Approved and applied {html.escape(data["applied"][:16].replace("T", " "))}</b>'
                   f'<span>Version <code>{data["old_version"]}</code> → <code>{data["new_version"]}</code>. The old version is kept: '
                   'the comparison below and the benchmark still work.</span></div>')
        acts = ""
    elif changed:
        outcome = (f'<div class="outcome ok"><b>✓ Done in {took}{spent} · {len(changed)} file{"s" * (len(changed) != 1)} changed</b>'
                   + "".join(f"<span>{html.escape(n)}</span>" for n in notes)
                   + '<span class="note">Compare the files below, benchmark the draft if you like, then approve or reject it.</span></div>')
        acts = ""
        decide = ('<div class="decide" role="region" aria-label="Decision"><span><b>Keep this draft?</b> '
                  '<span class="note">Approve writes it into the skill; tokscope keeps the old version.</span></span>'
                  '<span class="acts"><a class="btn" href="#bench">Benchmark first</a>'
                  '<button type="button" class="btn danger" data-job-act="discard">Reject</button>'
                  '<button type="button" class="primary" data-job-act="apply">Approve and apply</button></span></div>')
    else:
        outcome = (f'<div class="outcome off"><b>Done in {took}{spent} · nothing changed</b>'
                   '<span>The run left the skill as it was. Its report below says why.</span></div>')
        acts = '<p class="acts"><button type="button" class="btn" data-job-act="discard">Discard</button></p>'
    diffs = "".join(_compare(rel, kind, lines, old_dir, new_dir) for rel, kind, lines in changed)
    bench_html = _bench_section(job, data, conn) if changed and conn is not None else ""
    report = (f'<section class="card"><h2 class="sec">The run\'s report</h2><div class="md">{markdown.render(data["report"])}</div></section>'
              if data.get("report") else "")
    return head + outcome + table + acts + '<p class="err" id="opt-err" hidden></p></section>' + diffs + bench_html + report + log + decide


def _library_skill(k, qs, used, conn, linter=None, found=()):
    listed = library.files(k["folder"])
    names = {rel for rel, _ in listed}
    rel = (qs.get("file") or ["SKILL.md"])[0]
    rel = rel if rel in names else "SKILL.md"
    base = f"/library?skill={k['id']}"
    here = rel.rsplit("/", 1)[0] + "/" if "/" in rel else ""

    def link(href):  # a relative link to another file of the skill opens it here
        target = href.split("#")[0]
        parts = []
        for part in (here + target).split("/"):
            if part == "..":
                parts = parts[:-1]
            elif part not in ("", "."):
                parts.append(part)
        target = "/".join(parts)
        return f"{base}&file={target}" if target in names else None

    text, why = library.read(k, rel)
    if text is None:
        view = f'<div class="empty"><b>{html.escape(rel)}</b>{html.escape(why)}</div>'
    elif rel.endswith(".md"):
        meta, body = markdown.frontmatter(text)
        rest = {a: b for a, b in meta.items() if not (rel == "SKILL.md" and a in ("name", "description"))}
        fm = ('<dl class="fm">' + "".join(f"<dt>{html.escape(a)}</dt><dd>{html.escape(b)}</dd>" for a, b in rest.items())
              + "</dl>") if rest else ""
        words = len(body.split())
        findings, error = None, ""
        if linter:
            try:
                findings = library.ste_lint(linter, [k["folder"] / rel])[k["folder"] / rel]
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
                error = str(e)
        ste_tab = (f'<button type="button" class="chip" data-view="ste">STE check'
                   f'{f" <b>{library.hard(findings)}</b>" if findings else ""}</button>')
        view = (f'<div class="viewbar"><span class="note">{words:,} words · ≈{_tok(len(text) // 4)} tokens (characters ÷ 4)</span>'
                '<span class="seg" role="group" aria-label="View"><button type="button" class="chip on" data-view="md">Rendered</button>'
                f'<button type="button" class="chip" data-view="src">Source</button>{ste_tab}</span></div>'
                f'<div class="md" data-pane="md">{fm}{markdown.render(body, link)}</div>'
                f'{_source(text, "src")}{_ste_pane(findings, text, words, linter, error)}')
    else:
        view = f'<div class="viewbar"><span class="note">{text.count(chr(10)) + 1:,} lines</span></div>{_source(text)}'
    tree = "".join(f'<a href="{base}&file={html.escape(r)}"{" class=on aria-current=page" if r == rel else ""}>{html.escape(r)}</a>'
                   for r, _ in listed)
    loads, last = used.get(k["dir"], (0, None))
    tracked = conn.execute("SELECT count(*) FROM skill_versions WHERE skill = ?", (k["dir"],)).fetchone()[0] if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'skill_versions'").fetchone() else 0
    facts = [("Where", f"<code>{html.escape(library._tilde(k['folder']))}</code>"),
             ("Origin", "yours" if k["origin"] == "mine" else f"installed: {html.escape(k['reason'])}"),
             ("Version", f"<code>{skills.fingerprint(k['folder'])}</code>" + (f" · v{html.escape(k['label'])}" if k["label"] else "")),
             ("Loads", f"{loads:,}" + (f", last {last[:10]}" if last else "")
              + (f' · <a href="/skills#v-{html.escape(k["dir"])}">{tracked} tracked versions</a>' if tracked > 1  # only a changed skill has a card
                 else " · 1 tracked version" if tracked else ""))]
    desc = f'<p>{markdown.inline(k["description"])}</p>' if k["description"] else ""
    head = ('<p><a href="/library">← All skills</a></p>'
            f'<section class="card libhead"><h2 class="sec">{html.escape(k["name"])}</h2>{desc}'
            '<dl class="ids">' + "".join(f"<dt>{a}</dt><dd>{b}</dd>" for a, b in facts) + "</dl></section>")
    job = (qs.get("job") or [""])[0]
    if JOB_ID.match(job) and (optimize.jobs_dir() / job / "job.json").is_file() and optimize.status(job)["source"] == str(k["folder"]):
        return _job_view(k, job, linter, conn)
    opt = _more("Optimize", "rewrite on a copy with claude -p; apply it if you like the diff",
                _optimize_panel(k, found) + _jobs_list(k), "optimize-panel")
    going = [j for j in optimize.jobs_for(k["folder"]) if j["state"] == "running"]
    if going:  # a run you started and left: one click back to its progress
        opt = (f'<a class="outcome run" href="/library?skill={k["id"]}&amp;job={going[0]["job"]}"><b><span class="spin"></span>'
               f'An optimize run is going</b><span>Started {html.escape(going[0]["started"][11:16])} UTC · see its progress</span></a>') + opt
    return (f'{head}{opt}<div class="libview"><nav class="card files" aria-label="Files">{tree}</nav>'
            f'<article class="card viewer"><h3 class="path">{html.escape(rel)}</h3>{view}</article></div>')


def page_library(conn, f, qs, level):
    if level != "full":
        return f'<div class="empty"><b>Skill text is hidden</b>The library shows file contents at the full level only (now {level}).</div>'
    found, used = library.discover(conn), library.usage(conn)
    linter = library.ste_linter(found)
    pick = (qs.get("skill") or [""])[0]
    k = next((k for k in found if k["id"] == pick), None)
    if k:
        return _library_skill(k, qs, used, conn, linter, found)
    lint, note = None, " Install the asd-ste100 skill to see STE findings here." if linter is None else ""
    if linter:
        try:
            lint = library.ste_lint(linter, [k["folder"] / "SKILL.md" for k in found])
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
            note = f" The STE check failed: {html.escape(str(e))}"
    return _library_list(found, used, lint, note)


def _project_card(g):
    mcp = projects.servers(g, (projects.last_health(g["root"]) or (0, None))[1]) if g["root"] else []
    unused = sum(e["flag"] == "never used here" for e in mcp)
    meta = (f"{g['sessions']:,} sessions · last {(g['last'] or '')[:10]}"
            + (f" · {len(g['folders'])} folders" if len(g["folders"]) > 1 else "")
            + (f" · MCP {len(mcp)}" + (f", {unused} never used" if unused else "") if mcp else ""))
    return (f'<a class="sk" href="/projects?p={g["id"]}"><b>{html.escape(g["name"])}</b><p>{html.escape(g["path"])}</p>'
            f'<span class="pnums"><span><b>{_tok(g["recent"])}</b> last 30 days</span><span><b>{_tok(g["tokens"])}</b> all time</span>'
            f'<span><b>{_usd(g["usd"])}</b> API-eq</span></span><span class="meta">{meta}</span></a>')


def _projects_list(found):
    if not found:
        return '<div class="empty"><b>No projects yet</b>Run <code>tokscope ingest</code> after a Claude Code session.</div>'
    real = [g for g in found if g["root"]]
    return (f'<p class="note">{len(real)} projects from your sessions. Worktrees, eval copies and subfolders count with the repository '
            'they belong to; benchmark runs are left out.</p>'
            f'<div class="libgrid">{"".join(_project_card(g) for g in found)}</div>')


def _project_view(g):
    checked = projects.last_health(g["root"]) if g["root"] else None
    rows = projects.servers(g, checked[1] if checked else None)
    folders = "".join(f"<li><code>{html.escape(projects._tilde(c))}</code> · {n:,} session{'s' * (n != 1)}"
                      f"{'' if Path(c).exists() else ' · <span class=note>gone</span>'}</li>" for c, n in sorted(g["folders"], key=lambda f: -f[1]))
    keys = sorted(k for k in g["keys"] if k)
    sessions_link = (f' · <a href="/sessions?range=all&amp;project={html.escape(keys[0])}">its sessions</a>' if len(keys) == 1 else "")
    head = ('<p><a href="/projects">← All projects</a></p>'
            f'<section class="card libhead"><h2 class="sec">{html.escape(g["name"])}</h2><dl class="ids">'
            f'<dt>Where</dt><dd><code>{html.escape(g["path"])}</code></dd>'
            f'<dt>Sessions</dt><dd>{g["sessions"]:,}, {(g["first"] or "")[:10]} to {(g["last"] or "")[:10]}{sessions_link}</dd>'
            f'<dt>Tokens</dt><dd>{_tok(g["recent"])} in the last 30 days · {_tok(g["tokens"])} all time · {_usd(g["usd"])} API-eq</dd></dl>'
            + (f'<details class="folders"><summary>{len(g["folders"])} folders</summary><ul class="plain">{folders}</ul></details>'
               if len(g["folders"]) > 1 else "") + "</section>")
    if g["root"] is None:
        return head
    if not g["root"].exists():
        return head + '<p class="note">This folder is gone, so its MCP configuration cannot be read.</p>'
    body = []
    for e in rows:
        status = e.get("status") or ("disabled" if e["disabled"] else "")
        cls = ("ok" if status.startswith("✔") else "warn" if status.startswith(("!", "⏸")) else "bad" if status.startswith("✘")
               else "off" if status else "")
        name = html.escape(e["name"]) + (' <span class="badge">shadowed</span>' if e["shadowed"] else "")
        flag = f'<span class="badge flag">{e["flag"]}</span>' if e["flag"] else ""
        secrets = f'<span class="note" title="names only; values are never shown">{html.escape(", ".join(e["secrets"]))}</span>' if e["secrets"] else ""
        if e["source"] in projects.SCOPES:
            act = (f'<button type="button" class="btn" data-mcp-remove="{html.escape(e["name"])}" data-scope="{e["source"]}">Remove</button>')
        elif e["source"].startswith("plugin "):
            act = '<span class="note">with the plugin: /plugin</span>'
        elif e["source"] == "connector":
            act = '<a href="https://claude.ai/customize/connectors" target="_blank" rel="noopener">claude.ai</a>'
        else:
            act = ""
        if status.startswith("! Needs auth") and e.get("toggle", e["name"]):
            status_html = (f'<span class="pill">{html.escape(status)}</span>'
                           f'<code class="login">claude mcp login "{html.escape(e.get("toggle") or e["name"])}"</code>')
        else:
            status_html = f'<span class="pill">{html.escape(status)}</span>' if status else '<span class="note">not checked</span>'
        body.append(f'<tr><td data-label="Server">{name} {flag}</td><td data-label="Source">{html.escape(e["source"])}</td>'
                    f'<td data-label="Runs as">{html.escape(e["transport"])} <code>{html.escape(e["target"])}</code> {secrets}</td>'
                    f'<td data-label="Calls">{e["calls"]:,}</td><td data-label="≈Result tokens">{_tok(e["tokens"])}</td>'
                    f'<td data-label="Last session">{(e["last"] or "–")[:10]}</td><td data-label="Status" class="st {cls}">{status_html}</td>'
                    f'<td data-label="Change">{act}</td></tr>')
    when = (f"checked {time.strftime('%H:%M', time.localtime(checked[0]))}" if checked else "not checked yet")
    unused = sum(e["flag"] == "never used here" for e in rows)
    table = (f'<section class="card" id="mcp" data-project="{g["id"]}"><h2 class="sec">MCP servers</h2>'
             f'<p class="note">{len(rows)} servers{f", {unused} never used here" if unused else ""}. Calls and result tokens come from '
             'this project\'s transcripts. Precedence: local, project, user, plugin, claude.ai connector; a lower definition with the '
             'same name is shadowed. Plugin servers change with the plugin, connectors at claude.ai.</p>'
             f'<p class="acts"><button type="button" class="btn" id="mcp-check">Check health</button> <span class="note" id="mcp-when">{when}. '
             'The check runs <code>claude mcp list</code> here: it starts the stdio servers and connects to the remote ones.</span></p>'
             '<p class="err" id="opt-err" hidden></p>'
             '<table class="mcp"><thead><tr><th>Server</th><th>Source</th><th>Runs as</th><th>Calls</th><th>≈Result tokens</th>'
             f'<th>Last session</th><th>Status</th><th>Change</th></tr></thead><tbody>{"".join(body)}</tbody></table></section>')
    return head + table + _registry_panel() + _mcp_form()


def _registry_panel():
    return ('<details class="more" id="mcp-find"><summary><span class="ttl">Find in the MCP Registry</span>'
            '<span class="note">the official catalog; Use fills in the form below</span></summary>'
            '<form id="reg-form" class="optrow"><input type="search" name="q" placeholder="github, postgres, browser…" aria-label="Search the registry">'
            '<button type="submit" class="btn">Search</button></form>'
            '<p class="note">The search words go to registry.modelcontextprotocol.io. Nothing is installed until you click '
            '<b>Add server</b>; check the package and its author first.</p><p class="err" id="reg-err" hidden></p>'
            '<div class="libgrid" id="reg-results"></div></details>')


def _mcp_form():
    scopes = (("local", "local: only you, in this project (~/.claude.json)"),
              ("project", "project: .mcp.json, shared with the repository"), ("user", "user: you, in every project (~/.claude.json)"))
    return ('<details class="more" id="mcp-add"><summary><span class="ttl">Add a server</span>'
            '<span class="note">runs claude mcp add-json in this project folder</span></summary><form id="mcp-form" class="optform">'
            '<div class="optrow"><label class="namefield">Name <input name="name" required pattern="[A-Za-z0-9_\\-]{1,64}" placeholder="my-server"></label>'
            '<select name="scope" aria-label="Scope">' + "".join(f'<option value="{v}">{t}</option>' for v, t in scopes) + '</select>'
            '<select name="transport" aria-label="Transport"><option value="stdio">stdio (a command)</option>'
            '<option value="http">http (a URL)</option><option value="sse">sse (deprecated)</option></select></div>'
            '<div data-for="stdio"><label class="wide">Command <input name="command" placeholder="npx"></label>'
            '<label class="wide">Arguments, one per line <textarea name="args" rows="3" placeholder="-y&#10;some-mcp-server"></textarea></label></div>'
            '<div data-for="http" hidden><label class="wide">URL <input name="url" placeholder="https://example.com/mcp"></label></div>'
            '<div id="mcp-pairs"></div><p><button type="button" class="btn" id="mcp-pair"></button></p>'
            '<p class="note">In project scope, write a secret as <code>${VAR}</code>: Claude Code reads it from your environment, and the '
            'file you commit holds no secret. tokscope never shows a value again.</p>'
            '<p><button type="submit" class="primary">Add server</button></p><p class="err" id="mcp-err" hidden></p></form></details>')


def page_projects(conn, f, qs, level):
    if level != "full":
        return f'<div class="empty"><b>Projects are hidden</b>This page reads real paths and MCP settings, so it shows at the full level only (now {level}).</div>'
    found = projects.discover(conn)
    pick = (qs.get("p") or [""])[0]
    g = next((g for g in found if g["id"] == pick), None)
    return _project_view(g) if g else _projects_list(found)


def page_benchmarks(conn, f):
    head, detail = _benchmarks(conn, paths.tasks())
    return f'<section class="card" id="benchmarks">{head}</section>{_more("Benchmark details", "every run and answer", detail)}'


def page_breakdowns(conn, f):
    cond, params = f.cond()
    changes = list_changes(conn)
    return (f'<div id="breakdowns">{_breakdowns(conn, cond, params)}</div>'
            + _more("Config changes", f"{len(changes)} recorded; before/after medians per run", _change_cards(conn, changes), "changes"))


DASH_CSS = """
main{width:100%;min-width:0}main a{color:var(--mark-ink);text-underline-offset:2px}
.dash-head{display:flex;flex-wrap:wrap;align-items:center;gap:10px 16px;margin:0 0 14px}.dash-head h1{margin:0}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-left:auto}
.filters select{font:inherit;font-size:13px;padding:6px 12px;border:var(--line-w) solid var(--ink);border-radius:999px;background:var(--surface);color:var(--ink);max-width:220px}
.filters a{font-size:12px;color:var(--muted)}
.fresh{font-size:12px;color:var(--muted);display:inline-flex;align-items:center;gap:6px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--pass);margin-right:8px}
.fresh .dot,h2>.dot{animation:pulse 2s infinite}
.fresh .dot{margin:0}.fresh.stale .dot{background:var(--muted);animation:none}
@keyframes pulse{50%{opacity:.35}}
/* the report's .kpis is a content-sized flex row; here the six tiles fill the width, edge to edge with .cols2 below */
[data-region=kpis]>.kpis{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:14px}[data-region=kpis] .kpi{min-width:0}
@media (max-width:1200px){[data-region=kpis]>.kpis{grid-template-columns:repeat(3,minmax(0,1fr))}}
@media (max-width:560px){[data-region=kpis]>.kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
.kpi{position:relative}.kpi .dl{display:block;font-size:11px;color:var(--muted);margin-top:2px}.kpi .dl .trend{display:inline-block;font-size:11px;padding:0 6px}
.spark{display:block;margin-top:4px}.spark polyline{fill:none;stroke:var(--mark-ink);stroke-width:1.5;stroke-linejoin:round;stroke-linecap:round}
.cols2{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.3fr);gap:22px}
/* spender cards share one width: two to a row on a desktop (the third starts the next row), one on a phone;
   wide enough that a long name (compound-engineering:ce-simplify-code) fits on one line, and it wraps whole if not */
.cols3{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,400px),1fr));gap:14px}
.cols3 table{width:100%;table-layout:fixed}.cols3 th:nth-child(2),.cols3 td:nth-child(2){width:130px}
.cols3 th:nth-child(3),.cols3 td:nth-child(3){width:48px}.cols3 .bar i{width:48px}
.cols3 td:first-child{white-space:normal;overflow-wrap:anywhere}.cols3 td{vertical-align:baseline}
/* the "What changed" tables share fixed number columns so they line up one under the other */
[data-region=changed] table{table-layout:fixed}[data-region=changed] td{vertical-align:baseline}[data-region=changed] td:not(:first-child){text-align:right;white-space:nowrap}
[data-region=changed] :is(th,td):nth-child(2){width:76px}[data-region=changed] :is(th,td):nth-child(3){width:80px}[data-region=changed] :is(th,td):nth-child(4){width:80px}[data-region=changed] .bar i{display:none}
[data-region=changed] td:first-child{overflow-wrap:break-word}@container (max-width:520px){[data-region=changed] :is(th,td):nth-child(2){width:62px}[data-region=changed] :is(th,td):is(:nth-child(3),:nth-child(4)){width:70px}}
@media (max-width:900px){.cols2,.cols3{grid-template-columns:1fr}}
h2.sec{font-size:15px;margin:6px 0 10px}.card h2{display:flex;align-items:center}
.today-nums{display:flex;gap:22px;flex-wrap:wrap;margin:6px 0 12px}.today-nums span{display:block;font-size:12px;color:var(--ink2)}
.today-nums b{font-size:22px;font-variant-numeric:tabular-nums}
.latest{display:flex;flex-direction:column;gap:3px;border-top:1px solid var(--grid);padding-top:10px}.latest a{color:var(--ink);text-decoration:none}
.latest a:hover b{color:var(--mark-ink)}
ul.plain{list-style:none;margin:0;padding:0}ul.plain li{padding:4px 0;border-bottom:1px solid var(--grid)}
.flash{animation:flash 1.2s var(--ease)}@keyframes flash{from{background:color-mix(in oklch,var(--pass) 18%,transparent)}}
#newdata{position:fixed;right:20px;bottom:20px;z-index:40}
@media (prefers-reduced-motion:reduce){.dot,.flash{animation:none}}
.libtools{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 14px}.libtools input[type=search]{min-width:min(100%,280px);padding:6px 14px;border:var(--line-w) solid var(--ink);border-radius:999px}
.live-card{box-shadow:10px 12px 0 var(--shadow);margin:0 10px 12px 0}
.libtools .chip input{margin:0}
.libgroup{margin:0 0 18px}.libgroup h2 .note{margin:0 0 0 8px;font-weight:400}
.libgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,280px),1fr));gap:12px}
a.sk{display:flex;flex-direction:column;gap:6px;background:var(--surface);border:var(--line-w) solid var(--ink);border-radius:12px;padding:12px 14px;
color:var(--ink);text-decoration:none;transition:transform .15s var(--ease),box-shadow .15s var(--ease)}
a.sk:hover{transform:translate(-2px,-2px);box-shadow:5px 6px 0 var(--shadow)}a.sk b{font-size:14px;overflow-wrap:anywhere}
a.sk p{margin:0;color:var(--ink2);font-size:12.5px;line-height:1.45;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
a.sk .meta{margin-top:auto;font-size:11.5px;color:var(--muted)}
.badge{font-size:11px;font-weight:500;padding:1px 7px;border-radius:999px;background:var(--chip);color:var(--ink2);margin-left:8px;vertical-align:1px}
.badge.inst{color:var(--agent-ink)}
.libview{display:grid;grid-template-columns:minmax(150px,230px) minmax(0,1fr);gap:14px;align-items:start}
@media (max-width:860px){.libview{grid-template-columns:minmax(0,1fr)}.files{position:static;max-height:190px}}
.files{position:sticky;top:12px;padding:8px;max-height:calc(100vh - 24px);overflow:auto}
.files a{display:block;padding:4px 8px;border-radius:6px;font:12px/1.4 var(--mono);color:var(--ink2);overflow-wrap:anywhere;text-decoration:none}
.files a:hover{color:var(--mark-ink)}.files a.on{background:var(--tint);color:var(--mark-ink)}
.viewer{overflow:visible}.viewer .path{font:600 13px var(--mono);margin:0 0 8px;overflow-wrap:anywhere}
.viewbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between;margin:0 0 10px}.viewbar .note{margin:0}
.seg{display:inline-flex;gap:4px}.seg .chip:is(:hover,.on) b{color:inherit}
.md{font-size:14px;line-height:1.6;max-width:84ch;overflow-wrap:anywhere}.md>:first-child{margin-top:0}
.md h1{font-size:20px}.md h2{font-size:17px;border-bottom:1px solid var(--grid);padding-bottom:4px}.md h3{font-size:15px}.md h4{font-size:14px}
.md h1,.md h2,.md h3,.md h4{margin:20px 0 8px}.md p,.md ul,.md ol{margin:0 0 10px}.md ul,.md ol{padding-left:22px}.md li{margin:2px 0}
.md code{font:.88em var(--mono);background:var(--chip);border-radius:4px;padding:1px 4px}
.md pre,pre.src{font:12.5px/1.55 var(--mono);background:var(--page);border:var(--line-w) solid var(--ink);border-radius:8px;padding:10px 12px;
margin:0 0 12px;white-space:pre-wrap;overflow-wrap:anywhere}
.md pre code{background:none;padding:0;font-size:inherit}
.md blockquote{margin:0 0 10px;padding:2px 12px;border-left:3px solid var(--grid);color:var(--ink2)}
.md table{margin:0 0 12px}.md td,.md th{white-space:normal;overflow-wrap:anywhere;vertical-align:top;text-align:left}
.md hr{border:0;border-top:1px solid var(--grid);margin:16px 0}
.libhead .ids dd{display:block;min-width:0;overflow-wrap:anywhere}.libhead .ids dt:first-child{font-weight:400;color:var(--muted)}
pre.src{counter-reset:ln}pre.src .ln{display:block;padding-left:5.5ch;text-indent:-5.5ch}
pre.src .ln::before{counter-increment:ln;content:counter(ln);display:inline-block;width:4ch;margin-right:1.5ch;text-indent:0;
text-align:right;color:var(--muted);user-select:none}pre.src .ln.hit{background:var(--hl);border-radius:3px}
.ste-n{white-space:nowrap}.libtools select{font:inherit;font-size:13px;padding:6px 12px;border:var(--line-w) solid var(--ink);border-radius:999px;background:var(--surface);color:var(--ink)}.seg .chip b{color:var(--fail);font-weight:600}
ol.ste{list-style:none;margin:10px 0 0;padding:0}ol.ste li{display:grid;grid-template-columns:auto auto 1fr;gap:2px 10px;align-items:baseline;
padding:8px 0;border-bottom:1px solid var(--grid)}ol.ste .lnk{font:12px var(--mono);text-decoration:none}
ol.ste .rule{font:600 12px var(--mono)}ol.ste .lvl{font-size:11px;color:var(--muted);justify-self:start}
ol.ste li.hard .lvl{color:var(--fail)}ol.ste .line,ol.ste .msg{grid-column:1/-1}
ol.ste .line{font:12.5px/1.5 var(--mono);background:var(--page);border-radius:6px;padding:4px 8px;white-space:pre-wrap;overflow-wrap:anywhere}
ol.ste mark{background:var(--hl);color:inherit;border-radius:2px}ol.ste .msg{font-size:12.5px;color:var(--ink2)}
.pnums{display:flex;flex-wrap:wrap;gap:4px 16px;font-size:12px;color:var(--ink2)}.pnums b{color:var(--ink);font-size:14px}
details.folders{margin-top:8px;font-size:13px}details.folders summary{cursor:pointer;color:var(--mark-ink)}details.folders li{overflow-wrap:anywhere}
table.mcp td{vertical-align:baseline}table.mcp :is(th,td):is(:nth-child(2),:nth-child(3),:nth-child(7)){text-align:left}table.mcp td:nth-child(3){white-space:normal;overflow-wrap:anywhere}table.mcp td:nth-child(3) .note{display:block;margin:2px 0 0}
table.mcp .st{white-space:normal;text-align:left}
/* the status is what a reader looks for: a filled pill in the state's color, the text in ink for contrast */
.st .pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;line-height:1.5;
background:var(--chip);color:var(--ink2);border:1px solid transparent}
.st.ok .pill{background:color-mix(in oklch,var(--pass) 16%,transparent);border-color:color-mix(in oklch,var(--pass) 45%,transparent);color:var(--ink)}
.st.warn .pill{background:color-mix(in oklch,var(--agent) 18%,transparent);border-color:color-mix(in oklch,var(--agent) 50%,transparent);color:var(--ink)}
.st.bad .pill{background:color-mix(in oklch,var(--fail) 18%,transparent);border-color:color-mix(in oklch,var(--fail) 50%,transparent);color:var(--ink)}
.st.off .pill{font-weight:500}
table.mcp tbody tr{transition:background .15s var(--ease)}
table.mcp tbody tr:hover{background:color-mix(in oklch,var(--mark) 8%,transparent)}
table.mcp tbody tr:hover td:first-child{color:var(--mark-ink)}
.badge.flag{color:var(--agent-ink)}.badge{white-space:nowrap}code.login{display:block;margin-top:2px;font-size:11.5px;color:var(--ink2);overflow-wrap:anywhere}
#mcp-add{margin-top:14px}#mcp-find{margin-top:14px}#reg-form{margin:6px 0}#reg-form input{flex:1 1 20em;font:inherit;font-size:13px;
padding:6px 14px;border:var(--line-w) solid var(--ink);border-radius:999px;background:var(--surface);color:var(--ink)}
.sk.reg{cursor:default}.sk.reg:hover{transform:none;box-shadow:none}.sk.reg .acts{display:flex;flex-wrap:wrap;gap:4px}.sk.reg .meta a{margin-right:8px}#mcp-form label.wide{display:flex;flex-direction:column;gap:4px;font-size:13px;margin:0 0 8px}
#mcp-form input,#mcp-form textarea,#mcp-form select{font:inherit;font-size:13px;padding:6px 8px;border:var(--line-w) solid var(--ink);border-radius:8px;
background:var(--surface);color:var(--ink);min-width:0}#mcp-form textarea{font-family:var(--mono)}
.pair{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 6px}
#mcp-form .namefield{flex:1 1 20em;display:flex;align-items:center;gap:8px;font-size:13px}#mcp-form .namefield input{flex:1;min-width:12em}.pair input{flex:1 1 12em}
.ask{display:flex;flex-wrap:wrap;gap:8px 12px;align-items:center;margin:10px 0;padding:10px 12px;border:var(--line-w) solid var(--ink);border-radius:12px;
background:color-mix(in oklch,var(--mark) 9%,var(--surface));animation:reveal .2s var(--ease) both}.ask p{margin:0;flex:1 1 20em}.ask .acts{display:flex;gap:8px}
.busy{position:relative;padding-left:30px!important;opacity:.9;cursor:progress}
.busy::before{content:"";position:absolute;left:11px;top:50%;width:11px;height:11px;margin-top:-7px;border:2px solid currentColor;border-right-color:transparent;
border-radius:50%;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
.spin{display:inline-block;width:12px;height:12px;margin-right:7px;vertical-align:-1px;border:2px solid var(--mark);border-right-color:transparent;
border-radius:50%;animation:spin .8s linear infinite}
.runbar{height:8px;border-radius:4px;background:var(--track);overflow:hidden;margin:14px 0 10px}
.runbar i{display:block;width:35%;height:100%;border-radius:4px;background:var(--mark);box-shadow:inset 0 0 0 1px var(--ink);animation:slide 1.6s var(--ease) infinite}
@keyframes slide{from{transform:translateX(-100%)}to{transform:translateX(290%)}}.runline{margin:0 0 8px}.runline b{font-variant-numeric:tabular-nums}
p.warn{color:var(--agent-ink);font-size:13px}
ol.steps{list-style:none;margin:6px 0 0;padding:0;max-height:360px;overflow-y:auto;font-size:12.5px}
ol.steps li{display:flex;gap:10px;padding:4px 0;border-bottom:1px solid var(--grid)}ol.steps span{min-width:0;overflow-wrap:anywhere}
ol.steps time{flex:none;width:5.5em;color:var(--muted);font:12px var(--mono)}ol.steps li.sub span{padding-left:16px;color:var(--ink2)}
ol.steps li.say span{color:var(--ink2);font-style:italic}ol.steps li:is(.error,.denied) span{color:var(--fail)}ol.steps li.retry span{color:var(--agent-ink)}
ol.steps li.start span,ol.steps li.end span{font-weight:600}
.outcome{display:flex;flex-direction:column;gap:4px;margin:12px 0 6px;padding:12px 14px;border:var(--line-w) solid var(--ink);border-radius:12px;
animation:reveal .3s var(--ease) both}.outcome b{font-size:15px}.outcome span{overflow-wrap:anywhere}
.outcome.ok{background:color-mix(in oklch,var(--pass) 12%,transparent)}
.outcome.bad{background:color-mix(in oklch,var(--fail) 12%,transparent)}
.outcome.off{background:var(--chip)}
a.outcome.run{color:var(--ink);text-decoration:none;background:color-mix(in oklch,var(--mark) 9%,var(--surface));margin:-4px 0 14px}
a.outcome.run:hover{background:color-mix(in oklch,var(--mark) 15%,var(--surface))}
@media (prefers-reduced-motion:reduce){.runbar i,.spin,.busy::before{animation:none}}
.cmp .viewbar{margin-bottom:8px}.cmp .path{margin:0}
table.sbs{width:100%;table-layout:fixed;border-collapse:collapse;font:12.5px/1.5 var(--mono)}table.sbs col.n{width:3.2em}
table.sbs th{text-align:left;font:600 12px var(--sans)}table.sbs td{vertical-align:top;white-space:pre-wrap;overflow-wrap:anywhere;
padding:1px 6px;border-bottom:0;text-align:left}table.sbs td.n{color:var(--muted);text-align:right;user-select:none;padding-right:8px}
table.sbs td.del{background:color-mix(in oklch,var(--fail) 12%,transparent)}table.sbs td.add{background:color-mix(in oklch,var(--pass) 12%,transparent)}
table.sbs td.gap{background:var(--chip)}
table.sbs td.del mark{background:color-mix(in oklch,var(--fail) 32%,transparent);color:inherit;border-radius:2px}
table.sbs td.add mark{background:color-mix(in oklch,var(--pass) 34%,transparent);color:inherit;border-radius:2px}
table.sbs tr.fold td{color:var(--muted);text-align:center;font-family:var(--sans);background:var(--page);padding:3px}
@media (max-width:700px){table.sbs col.n{width:2.4em}table.sbs{font-size:11.5px}}
/* the decision stays in sight while you read the comparison */
.decide{position:sticky;bottom:12px;z-index:6;display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;justify-content:space-between;
margin:14px 0 0;padding:10px 14px;border:var(--line-w) solid var(--ink);border-radius:12px;background:var(--surface);
animation:reveal .3s var(--ease) both}
.decide .note{margin-left:6px}.decide .acts{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.btn.danger{color:var(--fail)}.btn.danger:hover{background:var(--ink);color:var(--page)}
#bench .verdict{font-size:14px;margin:6px 0 10px}#bench-form{margin:10px 0}#bench-form select{font:inherit;font-size:13px;padding:6px 12px;
border:var(--line-w) solid var(--ink);border-radius:999px;background:var(--surface);color:var(--ink);max-width:100%}
#task-form label.wide{display:flex;flex-direction:column;gap:4px;font-size:13px;margin:0 0 8px}
#task-form input,#task-form textarea{font:inherit;font-size:13px;padding:6px 8px;border:var(--line-w) solid var(--ink);border-radius:8px;background:var(--surface);color:var(--ink)}
#task-form textarea{font-family:var(--mono)}#task-new{margin-top:10px}
table.bres td:not(:first-child),table.bres th:not(:first-child){text-align:right}table.bres td:last-child,table.bres th:last-child{text-align:left}
details.more#optimize-panel{margin:-4px 0 14px}.optform{display:flex;flex-direction:column;gap:8px}.opt{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.opt .note{margin:0}.optrow{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
.optrow select,.optrow input{font:inherit;font-size:13px;padding:6px 12px;border:var(--line-w) solid var(--ink);border-radius:999px;background:var(--surface);color:var(--ink)}
.optrow input{width:6em}select option{background:var(--surface);color:var(--ink)}.err{color:var(--fail);font-size:13px;white-space:pre-wrap;overflow-wrap:anywhere}.sub3{font-size:13px;margin:14px 0 6px}
.state{font-size:12px;padding:1px 8px;border-radius:999px;background:var(--chip);color:var(--ink2)}.state.done,.state.applied{color:var(--pass)}
.state.failed,.state.interrupted{color:var(--fail)}.state.running{color:var(--mark-ink)}#job table{margin:10px 0}
.fm{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 14px;font-size:12.5px;background:var(--page);border:var(--line-w) solid var(--ink);
border-radius:8px;padding:10px 12px;margin:0 0 16px}.fm dt{color:var(--muted)}.fm dd{margin:0}
/* type: the controls and values of the dashboard pages (see the type block in report.CSS) */
.filters select,.libtools select,.libtools input[type=search],#bench-form select,.optrow select,.optrow input,#reg-form input,#mcp-form select{font-family:var(--mono);font-size:12px;font-weight:400}
.filters a,.fresh,.kpi .dl .trend,.state,.st .pill,.badge{font-family:var(--mono)}.filters a,.fresh{font-size:12px}.kpi .dl .trend{font-weight:600}
.st .pill,.state,.badge{font-weight:500}.badge,.state{font-size:11px}.st .pill{font-size:12px}
table.sbs th{font:500 11px/1.45 var(--mono)}a.sk .meta,.libview .ste-n{font-family:var(--mono)}
table.mcp td:is(:nth-child(2),:nth-child(3),:nth-child(7)),table.bres td:last-child,table.bres td:first-child{font-family:var(--sans)}table.mcp td.st{font-family:var(--mono)}
.runline b{font-family:var(--mono);font-weight:600}
.latest>.note:first-child{font:600 11px/1.45 var(--mono);text-transform:uppercase;letter-spacing:.08em}.latest>.note:first-child time{font-weight:400}
"""

LIB_JS = """
// library: find by name or description, show installed skills on request, rendered or source view
const libFind=document.getElementById('lib-find'),libInst=document.getElementById('lib-inst');
function libFilter(){const q=(libFind?.value||'').trim().toLowerCase(),all=libInst?.checked;let shown=0;
  document.querySelectorAll('a.sk').forEach(a=>{const ok=(all||a.dataset.origin==='mine')&&(!q||a.dataset.find.includes(q));a.hidden=!ok;shown+=ok});
  document.querySelectorAll('.libgroup').forEach(g=>g.hidden=!g.querySelector('a.sk:not([hidden])'));
  const none=document.getElementById('lib-none');if(none)none.hidden=shown>0}
libFind?.addEventListener('input',libFilter);libInst?.addEventListener('change',libFilter);if(libFind)libFilter();
document.getElementById('lib-sort')?.addEventListener('change',e=>{const by=e.target.value;
  document.querySelectorAll('.libgrid').forEach(g=>[...g.children].sort((a,b)=>by?(+b.dataset[by])-(+a.dataset[by])||a.dataset.find.localeCompare(b.dataset.find)
    :a.dataset.find.localeCompare(b.dataset.find)).forEach(a=>g.append(a)))});
document.getElementById('ste-adv')?.addEventListener('change',e=>document.querySelectorAll('ol.ste li.adv').forEach(li=>li.hidden=!e.target.checked));
document.querySelectorAll('[data-goto]').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();
  document.querySelector('[data-view=src]')?.click();const ln=document.getElementById(a.dataset.goto);if(!ln)return;
  document.querySelectorAll('.ln.hit').forEach(x=>x.classList.remove('hit'));ln.classList.add('hit');ln.scrollIntoView({block:'center'})}));
// optimize: start a run, follow it, apply or discard it; every write carries the token of this page
const token=document.querySelector('meta[name=tokscope-token]')?.content||'';
async function send(url,body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-Tokscope-Token':token},
  body:JSON.stringify(body||{})});const j=await r.json().catch(()=>({error:'no answer'}));if(!r.ok)throw new Error(j.error||r.status);return j}
function showErr(e){const el=document.getElementById('opt-err');if(el){el.textContent=e.message;el.hidden=false}}
// a question on the page, not confirm(): some browsers (an editor's built-in one) block dialogs, and confirm() then says no at once
function ask(anchor,text,ok='OK'){return new Promise(res=>{document.querySelector('.ask')?.remove();const box=el('div','ask');
  box.setAttribute('role','alertdialog');const y=el('button','primary',ok),n=el('button','btn','Cancel'),acts=el('span','acts');y.type=n.type='button';
  const esc=e=>{if(e.key==='Escape')done(false)},done=v=>{box.remove();document.removeEventListener('keydown',esc);res(v)};
  y.addEventListener('click',()=>done(true));n.addEventListener('click',()=>done(false));document.addEventListener('keydown',esc);
  acts.append(y,n);box.append(el('p','',text),acts);anchor.after(box);box.scrollIntoView({block:'nearest'});y.focus()})}
function busy(b,text){b.dataset.label=b.textContent;b.disabled=true;b.classList.add('busy');b.textContent=text}
function idle(b){b.disabled=false;b.classList.remove('busy');b.textContent=b.dataset.label||b.textContent}
document.getElementById('optimize')?.addEventListener('submit',async e=>{e.preventDefault();const f=e.target,b=f.querySelector('button[type=submit]'),
  guides=[...f.querySelectorAll('[name=guide]:checked')].map(x=>x.value),budget=+f.budget.value;
  if(!await ask(b.closest('.optrow'),`Run claude -p with ${guides.join(', ')||'no guide'} on a copy of this skill? It spends at most $${budget}. The skill changes only when you apply the result.`,'Run it'))return;
  busy(b,'Starting…');
  try{const j=await send('/api/optimize',{skill:f.dataset.skill,guides,model:f.model.value,budget});location.href=j.url}catch(err){showErr(err);idle(b)}});
document.getElementById('mcp-check')?.addEventListener('click',async e=>{const b=e.target,when=document.getElementById('mcp-when');
  b.disabled=true;when.textContent='Checking… this can take a minute.';
  try{await send(`/api/projects/${document.getElementById('mcp').dataset.project}/health`);location.reload()}
  catch(err){showErr(err);b.disabled=false;when.textContent='The check failed.'}});
const mcpCard=document.getElementById('mcp'),mf=document.getElementById('mcp-form');
function mcpKind(){const k=mf.transport.value==='stdio'?'stdio':'http';mf.querySelectorAll('[data-for]').forEach(d=>d.hidden=d.dataset.for!==k);
  document.getElementById('mcp-pair').textContent=k==='stdio'?'+ Environment variable':'+ Header'}
function addPair(key='',value='',hint='',title='',secret=true){const d=document.createElement('div');d.className='pair';d.innerHTML='<input placeholder="NAME" aria-label="Name">'+
  '<input type="password" placeholder="value or ${VAR}" aria-label="Value" autocomplete="off"><button type="button" class="btn">Remove</button>';
  const [k,v]=d.querySelectorAll('input');k.value=key;v.value=value;if(!secret)v.type='text';if(hint)v.placeholder=hint;if(title)d.title=title;
  d.querySelector('button').addEventListener('click',()=>d.remove());document.getElementById('mcp-pairs').append(d)}
// registry: results are drawn with textContent only, since every field comes from a public catalog
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text)e.textContent=text;return e}
function useOption(s,o){const add=document.getElementById('mcp-add');add.open=true;mf.elements['name'].value=s.name;
  mf.transport.value=o.transport==='stdio'?'stdio':o.transport;mcpKind();mf.command.value=o.command||'';mf.args.value=(o.args||[]).join('\\n');
  mf.url.value=o.url||'';document.getElementById('mcp-pairs').replaceChildren();
  (o.pairs||[]).forEach(p=>addPair(p.key,p.value,p.secret?'${'+p.key+'}':(p.required?'required':'optional'),p.description,p.secret));
  add.scrollIntoView({block:'start',behavior:smoothOk()?'smooth':'auto'});mf.elements['name'].focus()}
document.getElementById('reg-form')?.addEventListener('submit',async e=>{e.preventDefault();const out=document.getElementById('reg-results'),
  err=document.getElementById('reg-err'),b=e.target.querySelector('button');err.hidden=true;b.disabled=true;out.replaceChildren(el('p','note','Searching… the registry can take up to 30 seconds.'));
  try{const r=await fetch('/api/registry?q='+encodeURIComponent(e.target.q.value));const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);
    out.replaceChildren();if(!j.length)out.append(el('p','note','No server this form can install matches. Try another word.'));
    j.forEach(s=>{const c=el('div','sk reg');const h=el('b','',s.title);c.append(h,el('span','note',s.id+(s.version?' · '+s.version:'')),el('p','',s.description));
      const links=el('span','meta');[['repository',s.repository],['website',s.website]].forEach(([t,u])=>{if(u&&u.startsWith('https://')){
        const a=el('a','',t);a.href=u;a.target='_blank';a.rel='noopener noreferrer';links.append(a,' ')}});c.append(links);
      const acts=el('span','acts');s.options.forEach(o=>{const u=el('button','btn','Use '+o.label);u.type='button';
        u.addEventListener('click',()=>useOption(s,o));acts.append(u)});c.append(acts);out.append(c)})}
  catch(x){out.replaceChildren();err.textContent=x.message;err.hidden=false}finally{b.disabled=false}});
if(mf){mf.transport.addEventListener('change',mcpKind);mcpKind();document.getElementById('mcp-pair').addEventListener('click',()=>addPair());
  mf.addEventListener('submit',async e=>{e.preventDefault();const err=document.getElementById('mcp-err');err.hidden=true;
    const pairs=[...mf.querySelectorAll('.pair')].map(d=>({key:d.children[0].value.trim(),value:d.children[1].value})).filter(x=>x.key);
    const hole=mf.args.value.split('\\n').find(a=>/^<[^>]+>$/.test(a.trim()));
    if(hole){err.textContent=`Replace ${hole.trim()} in the arguments with a real value.`;err.hidden=false;return}
    const sub=mf.querySelector('button[type=submit]');
    if(mf.scope.value==='project'&&pairs.some(x=>x.value&&!x.value.includes('${'))&&
      !await ask(sub.parentElement,'A value is not a ${VAR} reference. It will be written into .mcp.json, which is usually committed. Continue?','Write it'))return;
    busy(sub,'Adding…');
    const body={name:mf.elements['name'].value,scope:mf.scope.value,transport:mf.transport.value,command:mf.command.value,
      args:mf.args.value.split('\\n'),url:mf.url.value,pairs};
    try{await send(`/api/projects/${mcpCard.dataset.project}/mcp`,body);location.reload()}
    catch(x){err.textContent=x.message;err.hidden=false;idle(sub)}})}
document.querySelectorAll('[data-mcp-remove]').forEach(b=>b.addEventListener('click',async()=>{
  if(!await ask(document.querySelector('#mcp .acts'),`Remove ${b.dataset.mcpRemove} from the ${b.dataset.scope} scope?`,'Remove'))return;
  busy(b,'Removing…');
  try{await send(`/api/projects/${mcpCard.dataset.project}/mcp/remove`,{name:b.dataset.mcpRemove,scope:b.dataset.scope});location.reload()}
  catch(x){showErr(x);idle(b)}}));
// a running job: the clock ticks every second, the steps and files come every two; the page reloads into the result
const jobEl=document.getElementById('job');
const clock=s=>{s=Math.max(0,Math.round(s));return s>=60?Math.floor(s/60)+'m '+String(s%60).padStart(2,'0')+'s':s+'s'};
if(jobEl&&jobEl.dataset.state==='running'){const t0=+jobEl.dataset.started;document.title='⏳ '+document.title;
  setInterval(()=>{const e=document.getElementById('run-elapsed');if(e)e.textContent=clock(Date.now()/1000-t0)},1000);
  setInterval(async()=>{try{const j=await (await fetch('/api/optimize/'+jobEl.dataset.job)).json();if(j.state!=='running'){location.reload();return}
    document.getElementById('run-count').textContent=j.nsteps+' steps';
    const w=document.getElementById('run-idle');w.hidden=j.idle<=120;document.getElementById('run-idle-s').textContent=clock(j.idle);
    const list=document.getElementById('run-list'),at=list.scrollTop+list.clientHeight>=list.scrollHeight-8;
    list.replaceChildren(...j.steps.map(st=>{const li=el('li',st.kind+(st.sub?' sub':''));li.append(el('time','','+'+clock(st.t-t0)),el('span','',st.text));return li}));
    if(at)list.scrollTop=list.scrollHeight;
    const files=document.getElementById('run-files');files.replaceChildren(...(j.files.length?j.files.map(([r,k])=>{const li=el('li');li.append(el('code','',r),' '+k);return li}):[el('li','note','none yet')]))}
  catch(_){}},2000)}
document.querySelectorAll('[data-job-act]').forEach(b=>b.addEventListener('click',async()=>{const act=b.dataset.jobAct,where=b.closest('.acts')||b;
  if(act==='apply'&&!await ask(where,'Write these changes into the skill folder? tokscope keeps the old version, so a benchmark can compare the two.','Apply'))return;
  if(act==='cancel'&&!await ask(where,'Stop the run? What it spent so far stays spent; the copy stays in the job folder until you discard it.','Stop it'))return;
  if(act==='discard'&&b.closest('.decide')&&!await ask(where,'Reject the draft? The job folder and its copy are deleted; the skill stays as it is.','Reject'))return;
  busy(b,{apply:'Applying…',discard:'Discarding…',cancel:'Stopping…'}[act]);
  try{await send(`/api/optimize/${jobEl.dataset.job}/${act}`);act==='discard'?location.href=location.pathname+'?skill='+new URLSearchParams(location.search).get('skill'):location.reload()}
  catch(err){showErr(err);idle(b)}}));
// compare: each changed file has its own tabs (side by side, diff, after, before)
document.querySelectorAll('.cmp').forEach(c=>c.querySelectorAll('[data-cmp]').forEach(b=>b.addEventListener('click',()=>{
  c.querySelectorAll('[data-cmp]').forEach(x=>x.classList.toggle('on',x===b));
  c.querySelectorAll('[data-cmp-pane]').forEach(p=>p.hidden=p.dataset.cmpPane!==b.dataset.cmp)})));
// benchmark: the cap is runs x 2 versions x the task's cap per run; the page follows the runs and reloads at the end
const bf=document.getElementById('bench-form'),benchErr=x=>{const e=document.getElementById('bench-err');e.textContent=x.message;e.hidden=false};
function benchCap(){if(!bf)return 0;const o=bf.task.selectedOptions[0],cap=+(o?.dataset.cap||0)*2*+bf.runs.value;
  document.getElementById('bench-cap').textContent=`${+bf.runs.value*2} runs, at most $${cap.toFixed(2)} in all`;return cap}
if(bf){bf.task.addEventListener('change',benchCap);bf.runs.addEventListener('change',benchCap);benchCap();
  bf.addEventListener('submit',async e=>{e.preventDefault();const b=bf.querySelector('button[type=submit]'),cap=benchCap();
    if(!await ask(bf,`Run ${bf.task.value} ${bf.runs.value} times on the current skill and ${bf.runs.value} times on the draft? It spends at most $${cap.toFixed(2)}.`,'Run it'))return;
    busy(b,'Starting…');try{await send(`/api/optimize/${jobEl.dataset.job}/bench`,{task:bf.task.value,runs:+bf.runs.value});location.reload()}
    catch(x){benchErr(x);idle(b)}})}
document.getElementById('task-form')?.addEventListener('submit',async e=>{e.preventDefault();const f=e.target,b=f.querySelector('button[type=submit]');
  busy(b,'Saving…');try{await send(`/api/optimize/${jobEl.dataset.job}/task`,{name:f.elements['name'].value,prompt:f.prompt.value,
    grader:f.grader.value,paths:f.paths.value,budget:+f.budget.value});location.reload()}catch(x){benchErr(x);idle(b)}});
const benchEl=document.getElementById('bench');
if(benchEl&&benchEl.dataset.bench==='running')setInterval(async()=>{try{const j=await (await fetch('/api/optimize/'+jobEl.dataset.job)).json();
  if(j.bench.state!=='running'){location.reload();return}const pre=document.getElementById('bench-log');pre.textContent=j.bench.log.join('\\n')||'starting…'}
  catch(_){}},3000);
document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('[data-view]').forEach(x=>x.classList.toggle('on',x===b));
  document.querySelectorAll('[data-pane]').forEach(p=>p.hidden=p.dataset.pane!==b.dataset.view)}));
"""

DASH_JS = """
// a filter change keeps only the filters set, so the URL reads like the view (range=30 is the default)
document.querySelectorAll('.filters select').forEach(s=>s.addEventListener('change',()=>{const q=new URLSearchParams();
  s.form.querySelectorAll('select').forEach(x=>{if(x.value&&!(x.name==='range'&&x.value==='30'))q.set(x.name,x.value)});
  location.href=s.form.getAttribute('action')+(q.toString()?'?'+q:'')}));
const freshEl=document.getElementById('fresh'),page=document.body.dataset.page;let stamp=document.body.dataset.stamp,seenAt=Date.now();
const ago=t=>{const s=Math.round((Date.now()-t)/1000);return s<60?'just now':s<3600?Math.round(s/60)+' min ago':Math.round(s/3600)+' h ago'};
function fresh(ok){freshEl.classList.toggle('stale',!ok);freshEl.lastChild.textContent=ok?' live · updated '+ago(seenAt):' offline · '+ago(seenAt)}
// counts from the value on screen to the new one; reduced motion writes the new text at once
function countFrom(el,from){const to=+el.dataset.count;if(from===to||!smoothOk())return;
  const kind=el.dataset.kind,f={int:v=>Math.round(v).toLocaleString('en-US'),tok:fmt,pct:v=>Math.round(v)+'%',
    usd:v=>'$'+v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}[kind]||fmt,end=el.textContent,t0=performance.now();
  el.closest('.kpi,.today-nums>div')?.classList.add('flash');
  const step=now=>{const p=Math.min(1,(now-t0)/900);el.textContent=p<1?f(from+(to-from)*(1-Math.pow(1-p,3))):end;if(p<1)requestAnimationFrame(step)};
  requestAnimationFrame(step)}
// overview: swap each region for its new render and count the numbers on; other pages offer a reload
async function refresh(){const url=location.pathname+location.search+(location.search?'&':'?')+'partial=1';
  const doc=new DOMParser().parseFromString(await (await fetch(url)).text(),'text/html');
  document.querySelectorAll('[data-region]').forEach(r=>{const next=doc.querySelector(`[data-region="${r.dataset.region}"]`);if(!next||next.innerHTML===r.innerHTML)return;
    const old={};r.querySelectorAll('[data-key]').forEach(el=>old[el.dataset.key]=+el.dataset.count);
    r.innerHTML=next.innerHTML;bindTips(r);r.querySelectorAll('[data-key]').forEach(el=>{if(el.dataset.key in old)countFrom(el,old[el.dataset.key])})})}
function offerReload(){if(document.getElementById('newdata'))return;const b=document.createElement('button');b.id='newdata';b.className='primary';
  b.textContent='New data · reload';b.addEventListener('click',()=>location.reload());document.body.append(b)}
async function poll(){if(document.hidden)return;
  try{const j=await (await fetch('/api/version')).json();seenAt=Date.now();
    if(j.stamp!==stamp){stamp=j.stamp;page==='overview'?await refresh():offerReload()}fresh(true)}catch(_){fresh(false)}}
setInterval(poll,5000);setInterval(()=>fresh(!freshEl.classList.contains('stale')),30000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll()});
"""


def _options(conn, f):
    projects = _q(conn, f"SELECT s.project, max(s.cwd), count(*) FROM sessions s WHERE s.project NOT LIKE '{BENCH_PROJECT}' "
                        "GROUP BY 1 ORDER BY 3 DESC")
    models = [m for (m,) in _q(conn, "SELECT DISTINCT model FROM requests WHERE model LIKE 'claude-%' ORDER BY 1")]
    skill_names = [k for (k,) in _q(conn, "SELECT DISTINCT skill FROM requests WHERE skill IS NOT NULL ORDER BY 1")]

    def select(name, current, options, blank):
        opts = [f'<option value="">{blank}</option>'] + [
            f'<option value="{html.escape(v)}"{" selected" if v == current else ""}>{html.escape(t)}</option>' for v, t in options]
        return f'<select name="{name}" aria-label="{name}">{"".join(opts)}</select>'

    return "".join([
        select("range", f.range, [(k, v) for k, v in RANGES.items()], "Last 30 days").replace('<option value="">Last 30 days</option>', ""),
        select("project", f.project, [(p, Path(cwd or p).name or p) for p, cwd, _ in projects], "All projects"),
        select("model", f.model, [(m, m.removeprefix("claude-")) for m in models], "All models"),
        select("skill", f.skill, [(k, k) for k in skill_names], "All skills"),
    ])


def render(conn, name, qs, stamp, level="full", token=""):
    f = Filters(qs)
    body = {"overview": lambda: page_overview(conn, f), "sessions": lambda: page_sessions(conn, f, qs),
            "skills": lambda: page_skills(conn, f, level), "library": lambda: page_library(conn, f, qs, level),
            "projects": lambda: page_projects(conn, f, qs, level),
            "benchmarks": lambda: page_benchmarks(conn, f),
            "breakdowns": lambda: page_breakdowns(conn, f)}[name]()
    if (qs.get("partial") or [""])[0]:
        return body
    scripts = (JS_CORE + (JS_SESSIONS if name == "sessions" else "") + JS_TREND + (JS_BENCH if name == "benchmarks" else "")
               + (LIB_JS if name in ("library", "projects") else "") + DASH_JS)
    nav = "".join(f'<a href="{f.link(p)}"{" class=on aria-current=page" if p == name else ""}>{t}</a>' for p, t in PAGES.items())
    reset = f' <a href="/{name}">clear filters</a>' if f.query() else ""
    note = "" if level == "full" else f'<p class="privacy" role="note"><b>{level}</b> names and text follow the {level} level.</p>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>tokscope · {PAGES[name]}</title>{favicon_link()}<meta name="tokscope-token" content="{token}"><script>document.documentElement.classList.add('js');
try{{const t=localStorage.getItem('tokscope-theme');if(t)document.documentElement.dataset.theme=t}}catch(_){{}}</script>
<style>{fonts.face_css(False)}{CSS}{DASH_CSS}</style></head><body data-page="{name}" data-stamp="{html.escape(stamp)}"><div id="progress"></div><div class="layout">
<aside class="side" aria-label="Pages"><div class="brand">{MARK}tokscope</div><nav class="toc">{nav}</nav>
<div class="side-foot"><button type="button" class="chip" id="theme">Theme</button>
<button type="button" class="chip" id="keys-btn" aria-label="Keyboard shortcuts"><kbd>?</kbd></button></div></aside><main>
<header class="dash-head"><h1>{PAGES[name]}</h1><span class="fresh" id="fresh"><span class="dot"></span> live</span>
{"" if name in ("library", "projects") else f'<form class="filters" method="get" action="/{name}">{_options(conn, f)}{reset}</form>'}</header>{note}
{body}
</main></div><div id="tip"></div><div id="toast" role="status" aria-live="polite"></div>
<dialog class="keys" id="keys"><h3 style="margin:0">Keyboard shortcuts</h3><dl>
<dt><kbd>t</kbd></dt><dd>Light or dark theme</dd><dt><kbd>g</kbd></dt><dd>Back to the top</dd>
<dt><kbd>/</kbd></dt><dd>Filter sessions (Sessions page)</dd><dt><kbd>?</kbd></dt><dd>Show this list</dd></dl></dialog>
<script>{scripts}</script></body></html>"""


def api(conn, name, qs, stamp):
    f = Filters(qs)
    if name == "version":
        return {"stamp": stamp}
    if name == "summary":
        cond, params = f.cond()
        t = _totals(conn, cond, params)
        return {"range": f.range, "tokens": t[0] or 0, "usd": t[1], "sessions": t[2], "output": t[3] or 0, "runs": t[4],
                "cache_read": t[5] or 0, "days": [{"day": d, "tokens": tk, "usd": u} for d, tk, u in _days(conn, f)]}
    if name == "projects":
        return [{"name": g["name"], "path": g["path"], "folders": [c for c, _ in g["folders"]], "sessions": g["sessions"],
                 "tokens": g["tokens"], "tokens_30d": g["recent"], "usd": round(g["usd"], 2), "last": g["last"],
                 "mcp": [{k: e[k] for k in ("name", "source", "transport", "calls", "tokens", "flag", "disabled", "status")}
                         for e in projects.servers(g, (projects.last_health(g["root"]) or (0, None))[1])]}
                for g in projects.discover(conn)]
    if name == "library":
        used = library.usage(conn)
        return [{"name": k["name"], "scope": k["scope"], "origin": k["origin"], "reason": k["reason"], "description": k["description"],
                 "path": str(k["folder"]), "loads": used.get(k["dir"], (0, None))[0]} for k in library.discover(conn)]
    if name == "sessions":
        cond, params = f.cond()
        return [{k: s[k] for k in ("id", "title", "start", "end", "prompts", "tokens", "output", "usd", "main", "agents", "runs")}
                for s in _sessions_json(conn, cond, params)]
    raise KeyError(name)


class Live:
    """Ingests new transcripts every `interval` seconds; `stamp` changes when the data does."""

    def __init__(self, db, phases, interval, projects_dir=PROJECTS_DIR):
        self.db, self.phases, self.interval, self.projects_dir = db, phases, interval, projects_dir
        self.stamp = self._stamp()
        self.error = None

    def _stamp(self):
        conn = connect(self.db)
        try:
            n, last = conn.execute("SELECT count(*), max(ts) FROM requests").fetchone()
            sv = conn.execute("SELECT count(*), max(last_seen) FROM skill_versions").fetchone() if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'skill_versions'").fetchone() else (0, "")
            return f"{n}:{last}:{sv[0]}"
        finally:
            conn.close()

    def tick(self):
        try:
            ingest(self.db, self.phases, self.projects_dir, log=lambda *_: None)
            self.stamp, self.error = self._stamp(), None
        except Exception as e:  # a half-written transcript or a locked db: keep serving, try again next tick
            self.error = str(e)

    def run(self):
        while True:
            time.sleep(self.interval)
            self.tick()


def post(db, path, body, level):
    """(code, JSON) for a write: start, apply or discard an optimize job."""
    if level != "full":
        return 403, {"error": "writes need the full privacy level"}
    if m := re.match(r"^api/projects/([0-9a-f]{10})/health$", path):
        conn = connect(db)
        try:
            g = next((g for g in projects.discover(conn) if g["id"] == m.group(1)), None)
        finally:
            conn.close()
        if not g or not g["root"] or not g["root"].is_dir():
            return 404, {"error": "no such project folder"}
        try:
            return 200, {"status": projects.health(g["root"], optimize._claude())}
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
            return 502, {"error": f"claude mcp list failed: {e}"}
    if m := re.match(r"^api/projects/([0-9a-f]{10})/mcp(/remove)?$", path):
        conn = connect(db)
        try:
            g = next((g for g in projects.discover(conn) if g["id"] == m.group(1)), None)
        finally:
            conn.close()
        if not g or not g["root"] or not g["root"].is_dir():
            return 404, {"error": "no such project folder"}
        try:
            if m.group(2):
                projects.remove(g["root"], body.get("name"), body.get("scope"), optimize._claude())
            else:
                name, scope = projects.add(g["root"], body, optimize._claude())
                return 200, {"name": name, "scope": scope}
            return 200, {"ok": True}
        except ValueError as e:
            return 400, {"error": str(e)}
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
            return 502, {"error": str(e)}
    if path == "api/optimize":
        conn = connect(db)
        try:
            found = library.discover(conn)
        finally:
            conn.close()
        k = next((k for k in found if k["id"] == body.get("skill")), None)
        if not k:
            return 404, {"error": "no such skill"}
        try:
            job = optimize.start(k, found, body.get("guides") or [], body.get("model") or "", body.get("budget") or 2)
        except (ValueError, TypeError) as e:
            return 400, {"error": str(e)}
        return 200, {"job": job, "url": f"/library?skill={k['id']}&job={job}"}
    m = re.match(r"^api/optimize/([^/]+)/(apply|discard|cancel|bench|task)$", path)
    if not m or not JOB_ID.match(m.group(1)) or not (optimize.jobs_dir() / m.group(1) / "job.json").is_file():
        return 404, {"error": "unknown endpoint"}
    job, act = m.groups()
    try:
        if act == "bench":
            return 200, optimize.bench_start(job, db, str(body.get("task", "")), body.get("runs") or 2)
        if act == "task":
            data = optimize.status(job)
            return 200, {"task": optimize.new_task(data["skill"], data["source"], body)}
        if act in ("discard", "cancel"):
            (optimize.discard if act == "discard" else optimize.cancel)(job)
            return 200, {"ok": True}
        conn = connect(db)
        try:
            old, new = optimize.apply(conn, job)
        finally:
            conn.close()
        return 200, {"old": old, "new": new}
    except ValueError as e:
        return 409, {"error": str(e)}


def handler(db, live, port, level, token=None):
    allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {f"http://{h}" for h in allowed}
    token = token or secrets.token_urlsafe(24)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _send(self, code, body, kind="text/html; charset=utf-8"):
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            # only this machine's browser: a page on another site cannot reach it by renaming itself (DNS rebinding)
            if self.headers.get("Host") not in allowed:
                return self._send(403, "tokscope serves this machine only")
            url = urlparse(self.path)
            qs = parse_qs(url.query)
            name = url.path.strip("/") or "overview"
            if name in ("favicon.ico", "favicon.svg"):  # browsers ask before they read the page's icon link
                return self._send(200, FAVICON, "image/svg+xml")
            if m := re.match(r"^fonts/([^/]+)$", name):
                data = fonts.read(m.group(1))
                if data is None:
                    return self._send(404, "no such font")
                self.send_response(200)
                self.send_header("Content-Type", "font/woff2")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "max-age=31536000, immutable")
                self.end_headers()
                return self.wfile.write(data)
            if name == "api/registry":
                if level != "full":
                    return self._send(403, json.dumps({"error": "the full level only"}), "application/json")
                try:
                    found = registry.search((qs.get("q") or [""])[0])
                except RuntimeError as e:
                    return self._send(502, json.dumps({"error": str(e)}), "application/json")
                return self._send(200, json.dumps(found), "application/json")
            if m := re.match(r"^api/optimize/([^/]+)$", name):
                if level != "full" or not JOB_ID.match(m.group(1)) or not (optimize.jobs_dir() / m.group(1) / "job.json").is_file():
                    return self._send(404, json.dumps({"error": "no such job"}), "application/json")
                data = optimize.status(m.group(1))
                shown, total, idle = optimize.steps(m.group(1))
                out = {k: data.get(k) for k in ("job", "state", "cost", "duration_s", "error")}
                bench_now = optimize.bench_status(m.group(1)) if data.get("bench") else {}
                out["bench"] = {"state": bench_now.get("state"), "log": bench_now.get("log", [])}
                out.update(steps=shown, nsteps=total, idle=idle,
                           files=[[rel, kind] for rel, kind, _ in optimize.changes(m.group(1))] if data["state"] == "running" else [])
                return self._send(200, json.dumps(out), "application/json")
            conn = privacy.redacted_copy(db, level) if level != "full" else connect(db)
            try:
                if name.startswith("api/"):
                    try:
                        return self._send(200, json.dumps(api(conn, name[4:], qs, live.stamp)), "application/json")
                    except KeyError:
                        return self._send(404, json.dumps({"error": "unknown endpoint"}), "application/json")
                if name not in PAGES:
                    return self._send(404, f"<p>No page {html.escape(name)}. Try <a href='/overview'>Overview</a>.</p>")
                return self._send(200, render(conn, name, qs, live.stamp, level, token))
            except sqlite3.OperationalError as e:
                return self._send(503, f"<p>The database is busy ({html.escape(str(e))}); reload in a moment.</p>")
            finally:
                conn.close()

        def do_POST(self):
            # a write needs this machine's host, this dashboard's origin, the token of a page it served and a JSON body:
            # another site's form or fetch fails the origin and token checks, and cannot set the header without CORS
            if self.headers.get("Host") not in allowed or self.headers.get("Origin") not in origins:
                return self._send(403, json.dumps({"error": "refused: not this dashboard"}), "application/json")
            if not hmac.compare_digest(self.headers.get("X-Tokscope-Token", ""), token):
                return self._send(403, json.dumps({"error": "refused: reload the page"}), "application/json")
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._send(415, json.dumps({"error": "send JSON"}), "application/json")
            n = int(self.headers.get("Content-Length") or 0)
            if n > 65536:
                return self._send(413, json.dumps({"error": "too large"}), "application/json")
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._send(400, json.dumps({"error": "bad JSON"}), "application/json")
            code, out = post(db, urlparse(self.path).path.strip("/"), body if isinstance(body, dict) else {}, level)
            return self._send(code, json.dumps(out), "application/json")

    return Handler


def serve(db, phases, port=8765, interval=10.0, open_browser=True, level="full", log=print, projects_dir=PROJECTS_DIR):
    live = Live(db, phases, interval, projects_dir)
    live.tick()  # start from fresh data
    server = ThreadingHTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
    port = server.server_address[1]  # the real one when asked for port 0
    server.RequestHandlerClass = handler(db, live, port, level)
    threading.Thread(target=live.run, daemon=True).start()
    url = f"http://127.0.0.1:{port}/overview"
    log(f"tokscope dashboard on {url} (this machine only; ingests every {interval:g}s; Ctrl+C stops it)")
    if open_browser:
        from .cli import open_in_browser
        open_in_browser(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
