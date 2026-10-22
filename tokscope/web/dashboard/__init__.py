"""Local live dashboard: `tokscope serve` answers on 127.0.0.1 only, reads the database on every request and ingests
new transcripts in the background, so the pages follow your work without a rebuild. The pages reuse the report's
sections; one filter bar (range, project, model, skill) scopes every number on a page, and lives in the URL.

Overview updates in place when new data lands (numbers count to their new value); the other pages offer a reload,
so a list you are reading does not move under you. /api/* returns the same numbers as JSON.

Layout: common (shared helpers), pages/ (one module per page), scripts (CSS and page JS), shell (the frame and render)
and server (HTTP handler, POST writes, background ingest)."""

from .common import PAGES, RANGES, Filters
from .pages.benchmarks import page_benchmarks
from .pages.breakdowns import page_breakdowns
from .pages.library import page_library
from .pages.managed import page_managed
from .pages.overview import page_overview, typical_day
from .pages.projects import page_projects
from .pages.sessions import page_sessions
from .scripts import DASH_CSS, DASH_JS, LIB_JS, MANAGED_JS
from .server import Live, api, handler, post, serve
from .shell import render, skills_moved

__all__ = ["PAGES", "RANGES", "Filters", "page_benchmarks", "page_breakdowns", "page_library", "page_managed",
           "page_overview", "typical_day", "page_projects", "page_sessions", "DASH_CSS", "DASH_JS", "LIB_JS", "MANAGED_JS",
           "Live", "api", "handler", "post", "serve", "render", "skills_moved"]
