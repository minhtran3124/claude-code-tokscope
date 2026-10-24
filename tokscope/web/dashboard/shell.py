"""The frame around every page: sidebar, filter bar, filter pill and the HTML document (render)."""

import html
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote, urlencode

from ... import paths
from ...core import tz
from ...features import library, projects
from ..theme import fonts
from ..theme.classic import CLASSIC_CSS, CLASSIC_DASH_CSS, SKIN_APPLY
from ..theme.layout import LAYOUT_CSS, LAYOUT_DASH_CSS, LAYOUT_TOKEN_CSS, LAYOUT_TOKEN_DASH_CSS
from ..theme.brand import MARK, favicon_link
from ...features.changes import BENCH_PROJECT
from ..report.scripts import JS_BENCH, JS_CORE, JS_SESSIONS, JS_SUMMARY, JS_TREND
from ..report.styles import CSS
from .common import Filters, PAGES, RANGES, _q
from .pages.benchmarks import page_benchmarks
from .pages.breakdowns import page_breakdowns
from .pages.library import page_library
from .pages.managed import page_managed
from .pages.overview import page_overview
from .pages.projects import page_projects
from .pages.sessions import page_sessions
from .scripts import DASH_CSS, DASH_JS, LIB_JS, MANAGED_JS


def _options(conn, f, only=None):
    projects = _q(conn, f"SELECT s.project, max(s.cwd), count(*) FROM sessions s WHERE s.project NOT LIKE '{BENCH_PROJECT}' "
                        "GROUP BY 1 ORDER BY 3 DESC")
    models = [m for (m,) in _q(conn, "SELECT DISTINCT model FROM requests WHERE model LIKE 'claude-%' ORDER BY 1")]
    skill_names = [k for (k,) in _q(conn, "SELECT DISTINCT skill FROM requests WHERE skill IS NOT NULL ORDER BY 1")]

    def select(name, current, options, blank):
        opts = [f'<option value="">{blank}</option>'] + [
            f'<option value="{html.escape(v)}"{" selected" if v == current else ""}>{html.escape(t)}</option>' for v, t in options]
        return f'<label class="fl"><span>{name.capitalize()}</span><select name="{name}">{"".join(opts)}</select></label>'

    if only == "project":
        return select("project", f.project, [(p, Path(cwd or p).name or p) for p, cwd, _ in projects], "All projects")
    return "".join([
        select("range", f.range, [(k, v) for k, v in RANGES.items()], "Last 30 days").replace('<option value="">Last 30 days</option>', ""),
        select("project", f.project, [(p, Path(cwd or p).name or p) for p, cwd, _ in projects], "All projects"),
        select("model", f.model, [(m, m.removeprefix("claude-")) for m in models], "All models"),
        select("skill", f.skill, [(k, k) for k in skill_names], "All skills"),
    ])


# (kind, HOME, data home, database) -> (time, count): folding projects and reading every SKILL.md is not for each render;
# HOME is in the key because both counts read ~/.claude
_NAV_CACHE = {}
NAV_TTL = 30.0


def _cached_count(conn, kind, compute):
    db = next((r[2] for r in conn.execute("PRAGMA database_list")), "")
    key = (kind, str(Path.home()), str(paths.home()), db)
    hit = _NAV_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < NAV_TTL:
        return hit[1]
    value = compute()
    _NAV_CACHE[key] = (time.monotonic(), value)
    return value


def _nav_counts(conn, level="full"):
    """The all-time number beside a page in the sidebar (not filtered; the label says so). Projects, Library and Benchmarks
    show their contents at the full level only, so they carry no count below it."""
    n = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    out = {"sessions": n(f"SELECT count(*) FROM sessions WHERE project NOT LIKE '{BENCH_PROJECT}'")}
    if level != "full":
        return out
    try:
        out["projects"] = _cached_count(conn, "projects", lambda: len([g for g in projects.discover(conn) if g["root"]]))
        out["library"] = _cached_count(conn, "library", lambda: len(library.discover(conn, None)))
        out["benchmarks"] = sum(1 for p in paths.tasks().iterdir() if p.is_dir()) if paths.tasks().is_dir() else 0
    except OSError:
        pass
    return out


def _filter_pill(conn, f, name):
    """The filters as one line for a phone: "Last 30 days · all projects", then any model or skill that is set."""
    proj = "all projects"
    if f.project:
        row = conn.execute("SELECT max(cwd) FROM sessions WHERE project = ?", (f.project,)).fetchone()
        proj = Path(row[0] or f.project).name or f.project
    parts = ([] if name == "library" else [RANGES[f.range]]) + [proj]
    if name != "library":
        parts += [x for x in (f.model.removeprefix("claude-"), f.skill) if x]
    return " · ".join(parts)


def _range_dates(f):
    """The exact days the applied range covers, in local time, shown after Apply."""
    if not f.days:
        return '<span class="range-dates note">all time</span>'
    first, last = (f.now - timedelta(days=f.days)).astimezone(tz.zone()), f.now.astimezone(tz.zone())
    return f'<span class="range-dates note">{first:%d %b %Y} – {last:%d %b %Y}</span>'


# the sidebar's two segmented controls: Theme (Light, Dark, Auto) and Design (Ink, Classic); report.JS_CORE drives them
SIDE_CONTROLS = (
    '<div class="side-foot ctls"><div class="ctl"><span class="ctl-l" id="theme-l">Theme</span><div class="segctl" role="group" aria-labelledby="theme-l">'
    + "".join(f'<button type="button" class="chip" data-set-theme="{m}" aria-pressed="false">{m.capitalize()}</button>' for m in ("light", "dark", "auto"))
    + '</div></div><div class="ctl"><span class="ctl-l" id="skin-l">Design</span><div class="segctl" role="group" aria-labelledby="skin-l">'
    + "".join(f'<button type="button" class="chip" data-set-skin="{m}" aria-pressed="false">{m.capitalize()}</button>' for m in ("ink", "classic"))
    + '</div></div>'
    + '<div class="ctl"><span class="ctl-l" id="tz-l">Time zone</span><div class="segctl" role="group" aria-labelledby="tz-l"><button type="button" class="chip" data-set-tz="local" aria-pressed="false" title="Show times in this browser\'s time zone">Local</button><button type="button" class="chip" data-set-tz="utc" aria-pressed="false">UTC</button></div></div>'
    + '<button type="button" class="chip" id="keys-btn" aria-label="Keyboard shortcuts"><kbd>?</kbd></button></div>')


def render(conn, name, qs, stamp, level="full", token=""):
    f = Filters(qs)
    body = {"overview": lambda: page_overview(conn, f), "sessions": lambda: page_sessions(conn, f, qs),
            "library": lambda: page_library(conn, f, qs, level),
            "projects": lambda: page_projects(conn, f, qs, level),
            "benchmarks": lambda: page_benchmarks(conn, f),
            "breakdowns": lambda: page_breakdowns(conn, f, qs),
            "managed": lambda: page_managed(qs, level)}[name]()
    if (qs.get("partial") or [""])[0]:
        return body
    scripts = (JS_CORE + (JS_SESSIONS if name == "sessions" else "") + JS_TREND + (JS_BENCH if name == "benchmarks" else "") + (JS_SUMMARY if name == "breakdowns" else "")
               + (LIB_JS if name in ("library", "projects", "managed") else "") + (MANAGED_JS if name == "managed" else "") + DASH_JS)
    # on the Library, ?skill= is a skill's id, not the filter bar's skill name: other pages must not get it
    navf = Filters({**qs, "skill": [""]}) if name == "library" else f
    counts = _nav_counts(conn, level)
    nav = "".join(f'<a href="{navf.link(p, **({"skill": ""} if p == "library" else {}))}"{" class=on aria-current=page" if p == name else ""}>{t}'
                  + (f'<span class="cnt" title="All time, not filtered">{counts[p]:,}</span>' if p in counts else "") + "</a>" for p, t in PAGES.items())
    reset = f' <a href="/{name}">clear filters</a>' if (f.project if name == "library" else f.query()) else ""
    # a skill page or an optimize run has its own header; a ?skill= that matches no skill falls back to the list, with the bar
    bar = ("" if name in ("projects", "managed") or (name == "library" and 'class="card libhead"' in body) else
           f'<form class="filters" method="get" action="/{name}">{_options(conn, f, "project" if name == "library" else None)}'
           f'<button type="submit" class="chip">Apply</button>{reset}</form>')
    chip = "" if level == "full" else f'<span class="privacy" role="note" title="Names and text follow the {level} level"><b>{level}</b></span>'
    dates = _range_dates(f) if bar and name != "library" else ""
    pill = sheet_filters = ""
    if bar:  # a phone shows the filters as one pill that opens the menu sheet, where the same form sits
        sheet_filters = (bar.replace('<form class="filters"', '<form class="filters sheet-filters" aria-label="Filters"', 1)
                         .replace("<label", '<p class="ctl-l">Filters</p><label', 1))
        pill = (f'<button type="button" class="chip pill-btn" aria-controls="sheet" aria-expanded="false" aria-haspopup="dialog">'
                f'<span>{html.escape(_filter_pill(conn, f, name))}</span><span class="pill-i" aria-hidden="true"></span></button>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>tokscope · {PAGES[name]}</title>{favicon_link()}<meta name="tokscope-token" content="{token}"><script>document.documentElement.classList.add('js');
try{{const t=localStorage.getItem('tokscope-theme');if(t)document.documentElement.dataset.theme=t}}catch(_){{}}</script>
<style>{fonts.face_css(False)}</style><style id="layout">{LAYOUT_CSS}{LAYOUT_DASH_CSS}{LAYOUT_TOKEN_CSS}{LAYOUT_TOKEN_DASH_CSS}</style><style id="skin-ink">{CSS}{DASH_CSS}</style><style id="skin-classic" media="not all">{CLASSIC_CSS}{CLASSIC_DASH_CSS}</style>{SKIN_APPLY}</head><body data-page="{name}" data-stamp="{html.escape(stamp)}"><div id="progress"></div><div class="layout">
<aside class="side" aria-label="Pages"><div class="brand">{MARK}tokscope</div>
<button type="button" class="chip menu-btn" id="menu-btn" aria-controls="sheet" aria-expanded="false"><span class="menu-i" aria-hidden="true"></span>Menu</button>
<div class="sheet" id="sheet"><nav class="toc" aria-label="Pages">{nav}</nav>{sheet_filters}
{SIDE_CONTROLS}<p class="sheet-priv note">Privacy level: <b>{level}</b>. Names and text follow it.</p></div></aside><main>
<header class="dash-head"><h1>{PAGES[name]}</h1>{chip}<span class="fresh" id="fresh"><span class="dot"></span> live</span>
{bar}{pill}{dates}</header>
{body}
</main></div><div id="tip"></div><div id="toast" role="status" aria-live="polite"></div>
<dialog class="keys" id="keys"><h3 style="margin:0">Keyboard shortcuts</h3><dl>
<dt><kbd>t</kbd></dt><dd>Light or dark theme</dd><dt><kbd>s</kbd></dt><dd>Classic or Ink design</dd><dt><kbd>g</kbd></dt><dd>Back to the top</dd>
<dt><kbd>/</kbd></dt><dd>Filter sessions (Sessions page)</dd><dt><kbd>?</kbd></dt><dd>Show this list</dd></dl></dialog>
<script>{scripts}</script></body></html>"""


def skills_moved(conn, qs):
    """Where an old /skills link goes: the Library, or a skill's page there when ?skill= names one."""
    f = Filters(qs)
    k = next((k for k in library.discover(conn, f.project or None) if k["dir"] == f.skill), None) if f.skill else None
    q = urlencode({a: v for a, v in (("skill", k["id"] if k else ""), ("project", f.project)) if v})
    return "/library" + (f"?{q}" if q else "") + (f"#v-{quote(k['dir'])}" if k else "")
