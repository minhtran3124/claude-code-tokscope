"""write_report: one HTML file from the database, at a privacy level."""

import html
import json
from datetime import datetime, timezone

from ... import paths
from ...core import otel, privacy, tz
from ..theme import fonts
from ..theme.layout import LAYOUT_CSS, LAYOUT_TOKEN_CSS
from ..theme.brand import MARK, favicon_link
from ...features.changes import BENCH_PROJECT, list_changes
from ...core.ingest import connect
from ...core.pricing import API_EQ_NOTE, unpriced, unpriced_text
from .common import TOKENS
from .scripts import JS, SORT_SEG
from .sections.benchmarks import _benchmarks
from .sections.cost_check import cost_check
from .sections.breakdowns import _breakdowns
from .sections.rows import summary_view
from .sections.sessions import _sessions_json
from .sections.skills import FEW_LOADS, _change_cards, _skill_versions
from .sections.summary import _hero, _session_start
from .styles import CSS
from .widgets import _daily_chart, _more, _tok, _usd


PRIVACY_NOTE = {
    "redacted": "Redacted report: prompts, session titles, subagent descriptions, benchmark answers, change notes, "
                "paths and project names are removed. Numbers and skill, agent and tool names are unchanged.",
    "numbers": "Numbers-only report: all text is removed, and skill, agent, tool, MCP server and task names are replaced "
               "by stable aliases (the same name gets the same alias in every report from this machine). Numbers are unchanged.",
}


def _unpriced(conn, cond, params):
    note = unpriced_text(unpriced(conn, cond, params))
    return f'<p class="note unpriced" role="note">{html.escape(note)}</p>' if note else ""


def write_report(db_path, out_path, where="", params=(), tasks_dir=None, level="full"):
    conn = connect(db_path)
    conn.executescript("CREATE TABLE IF NOT EXISTS prompts (session_id TEXT, prompt_idx INTEGER, ts TEXT, text TEXT)")
    tasks_dir = tasks_dir or paths.tasks()
    scoped = bool(where)  # a filter (project, model, skill, range) is on: the Cost check leaves out events no request owns
    if level != "full":
        conn.close()
        conn = privacy.redacted_copy(db_path, level, where, params)
        where, params, tasks_dir = "", (), None  # the copy is already filtered; task specs hold text (about, grader words)
    cond = f"{where} {'AND' if where else 'WHERE'} s.project NOT LIKE '{BENCH_PROJECT}'"
    params = tuple(params)

    (n_sess, tokens, out, cache_read, usd, first, last, n_runs) = conn.execute(
        f"SELECT count(DISTINCT session_id), sum({TOKENS}), sum(output), sum(cache_read), sum(cost_usd), min(r.ts), max(r.ts), "
        f"count(DISTINCT CASE WHEN agent_id IS NOT NULL THEN session_id || agent_id END) "
        f"FROM requests r JOIN sessions s USING (session_id) {cond}", params).fetchone()
    only = [] if scoped else otel.only_sessions(conn)  # no transcript: counted in the totals, not in any breakdown
    if only:
        t = otel.only_totals(conn)
        n_sess += t["sessions"]
        tokens, out, cache_read, usd = (tokens or 0) + t["tokens"], (out or 0) + t["output"], (cache_read or 0) + t["cache_read"], (usd or 0) + t["usd"]
        first = min(filter(None, (first, *(s["first"] for s in only))), default=None)
        last = max(filter(None, (last, *(s["last"] for s in only))), default=None)
    kpis = [("Sessions", f"{n_sess:,}", n_sess, "int"), ("Tokens", _tok(tokens), tokens, "tok"),
            ("Output tokens", _tok(out), out, "tok"), ("Subagent runs", f"{n_runs:,}", n_runs, "int"),
            ("From cache", f"{(cache_read or 0) / (tokens or 1):.0%}", round(100 * (cache_read or 0) / (tokens or 1)), "pct"),
            ("API-eq", _usd(usd), round(usd or 0, 2), "usd")]
    api_eq_title = f' title="{html.escape(API_EQ_NOTE + otel.ONLY_NOTE if only else API_EQ_NOTE)}"'
    kpi_html = "".join(f'<div class="kpi" style="--i:{i}"{api_eq_title if k == "API-eq" else ""}><span>{k}</span><b data-count="{raw or 0}" data-kind="{kind}">{v}</b></div>'
                       for i, (k, v, raw, kind) in enumerate(kpis))

    changes = list_changes(conn)
    n_changed, versions_html = _skill_versions(conn, level)
    days = conn.execute(f"SELECT localday(r.ts) d, sum({TOKENS}), sum(cost_usd) FROM requests r JOIN sessions s "
                        f"USING (session_id) {cond} GROUP BY d ORDER BY d", params).fetchall()
    bench_head, bench_detail = _benchmarks(conn, tasks_dir)
    data = json.dumps(_sessions_json(conn, cond, params, only), separators=(",", ":")).replace("</", "<\\/")
    now_utc = datetime.now(timezone.utc)
    generated = f'<time data-ts="{now_utc:%Y-%m-%dT%H:%M:%SZ}" data-fmt="dt">{now_utc:%Y-%m-%d %H:%M} UTC</time>'

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>tokscope report{"" if level == "full" else f" ({level})"}</title>{favicon_link()}<script>document.documentElement.classList.add('js');
try{{const t=localStorage.getItem('tokscope-theme');if(t)document.documentElement.dataset.theme=t}}catch(_){{}}</script>
<style>{fonts.face_css(True)}</style><style id="layout">{LAYOUT_CSS}{LAYOUT_TOKEN_CSS}</style><style id="skin-ink">{CSS}</style></head><body><div id="progress"></div><div class="layout">
<aside class="side" aria-label="Sections"><div class="brand">{MARK}tokscope</div><nav class="toc">
<a href="#overview">Overview</a>
<a href="#sessions">Sessions<span class="cnt">{n_sess:,}</span></a>
<a href="#benchmarks">Benchmarks</a>
<a href="#trend">Daily trend</a>
<a href="#changes">Config changes<span class="cnt">{len(changes)}</span></a>
<a href="#skill-versions">Skill versions<span class="cnt">{n_changed}</span></a>
<a href="#summary">Summary</a>
<a href="#breakdowns">Breakdowns</a>
<div class="sub-toc"><a href="#by-week">Week over week</a><a href="#by-mcp">By MCP server</a><a href="#by-tool">By tool</a><a href="#by-phase">By phase</a>
<a href="#by-owner">By owner</a><a href="#by-skill">By skill</a><a href="#agent-types">Subagent types</a><a href="#errors">Errors</a><a href="#cache">Prompt cache</a><a href="#context">Context</a></div>
</nav><div class="side-foot"><button type="button" class="chip" id="theme">Theme</button>
<span class="segctl" role="group" aria-label="Time zone"><button type="button" class="chip" data-set-tz="local" aria-pressed="false" title="Show times in this browser's time zone">Local</button><button type="button" class="chip" data-set-tz="utc" aria-pressed="false">UTC</button></span>
<button type="button" class="chip" id="keys-btn" aria-label="Keyboard shortcuts"><kbd>?</kbd></button></div></aside><main>
<div id="overview">
<h1>Claude Code token usage</h1>
{f'<p class="privacy" role="note"><b>{level}</b> {PRIVACY_NOTE[level]}</p>' if level != "full" else ""}
<p class="sub">{(first or '')[:10]} → {(last or '')[:10]} · real sessions (benchmarks separate) · generated {generated}</p>
{_hero(conn, cond, params)}
{_session_start(conn, cond, params)}
<div class="kpis">{kpi_html}</div>{_unpriced(conn, cond, params)}
{cost_check(conn, cond, params, scoped=scoped)}</div>

<section class="card reveal" id="sessions"><h2>Sessions</h2>
<p class="note"><span class="key"><i></i>main thread</span><span class="key"><i class="a"></i>subagents</span>
Open a row to see each prompt, its skill, tokens and calls. Tick 2 to 4 rows, then press Compare.
Sessions do different work, so a comparison describes them; for a controlled before/after use a benchmark.</p>
<div class="tools"><input type="search" id="s-q" placeholder="Filter by title, skill, folder or session id  ( / )">
{SORT_SEG}
<span class="note" id="s-count"></span></div>
<section class="card" id="compare"><h3>Compare</h3>
<p class="note">Bold = fewest. Tokens per prompt evens out sessions of different length.</p><table></table></section>
<div id="session-list"></div>
<div class="pickbar" id="pickbar" role="region" aria-label="Compare sessions" hidden><span id="pick-hint"></span><span class="acts"><button class="btn" id="clear-pick">Clear</button>
<button class="primary" id="do-compare" disabled>Compare</button></span></div>
<p><button class="btn" id="s-more">Show more</button></p></section>

<section class="card reveal" id="benchmarks"><h2>Benchmarks</h2>
<p class="note">Same task, fresh session per run, variants interleaved. Open the details to read each answer.</p>
{bench_head}
{_more("Benchmark details", "per-variant spread, main vs subagent tokens, every answer", bench_detail)}</section>

{_more("Daily trend", f"tokens per day in {tz.label()}; the mustard line is the 7-day average; a dashed line marks a config change", _daily_chart(days, changes), "trend")}
{_more("Config changes", f"{len(changes)} recorded; before/after medians per run", _change_cards(conn, changes), "changes")}
{_more("Skill versions", f"{n_changed} skill{'' if n_changed == 1 else 's'} changed. A version is a hash of the skill's folder; each row is the median tokens of one "
       f"prompt's requests while that version was loaded. Few loads = fewer than {FEW_LOADS}: watch, do not judge. "
       f"For a fair comparison, run a benchmark or a replay", versions_html, "skill-versions")}
{summary_view(conn, cond, params)}
<div id="breakdowns">{_breakdowns(conn, cond, params)}</div>
</main></div><div id="tip"></div><div id="toast" role="status" aria-live="polite"></div>
<dialog class="keys" id="keys"><h3 style="margin:0">Keyboard shortcuts</h3><dl>
<dt><kbd>/</kbd></dt><dd>Filter sessions</dd><dt><kbd>t</kbd></dt><dd>Light or dark theme</dd>
<dt><kbd>c</kbd></dt><dd>Compare the ticked sessions</dd><dt><kbd>g</kbd></dt><dd>Back to the top</dd>
<dt><kbd>Esc</kbd></dt><dd>Clear the filter, close this</dd><dt><kbd>?</kbd></dt><dd>Show this list</dd></dl></dialog>
<button type="button" class="totop" id="totop" aria-label="Back to top" title="Back to top">↑</button>
<script type="application/json" id="sessions-data">{data}</script><script>{JS}</script></body></html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page)
