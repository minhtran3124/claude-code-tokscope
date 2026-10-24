# Plan: summary export (#89) and always-on baseline (#90)

Branch base: `feat/summary-export-baseline` (from `github/main`). Each issue gets its own branch/PR off this one.
Test: `python3 -m unittest discover -s tests -q` (baseline: 345 OK). Layout rule: `core` imports nothing from features/web (`tests/test_layout.py`).

## #89 Summary export (CSV/JSON)
Tasks
1. `cli.py`: extract a shared rows function (key, requests, prompt_tokens, output_tokens, cost_usd, carried_cost_usd) from `summary()`; add `--format table|json|csv` (default table, byte-identical). json/csv print only data on stdout; API-equivalent and unpriced notes go to stderr.
2. `web/dashboard/server.py`: `GET /api/summary?by=phase|skill|agent|model&format=json|csv` with filter-bar filters (range, project, model, skill), reusing the same rows function; keep host/site checks.
3. UI: Summary section/page (group-by selector kept in URL, table, Download CSV/JSON, Copy, notes). Pick `pages/breakdowns.py` section or new `pages/summary.py`; page script in `web/dashboard/scripts`. Must work in the desktop app.
4. Report: two download links from data already in the file (`web/report/sections/`, scripts).
5. Docs: PRODUCT.md, README.md.
6. Tests: CLI json/csv vs table on a fixture, default output unchanged, endpoint filters and host/site refusal, report links.

Files: `tokscope/cli.py`, `tokscope/web/dashboard/server.py`, `pages/breakdowns.py` or `pages/summary.py`, `web/dashboard/scripts`, `web/report/sections/`, `PRODUCT.md`, `README.md`, `tests/test_dashboard.py`, `tests/test_report.py`, new CLI test.

Verify: unit tests; `bin/tokscope summary --by skill --format csv|json` with a throwaway `TOKSCOPE_HOME`; `curl` `/api/summary` on a scratch server; screenshots at 1440 and 375 px before/after.

## #90 Always-on baseline
Tasks
1. Phase 1, `core/ingest.py`: per-session baseline = first non-sidechain request `input+cache_creation+cache_read` (column or view over `requests`; no new transcript parsing). Mind schema migration for existing DBs.
2. `features/projects.py`: median/p90 baseline per project, 30-day trend, session-start cost (tokens x cache-write rate of model, via pricing); range-filtered; a project with no sessions yields no baseline and no error.
3. `pages/projects.py`, `pages/overview.py`: "Every new session starts at ~X tokens (~$Y)", trend; `~` marks with method tooltip. Report section in `web/report/sections/`.
4. Phase 2: parse `shape` records (`{system, tools}`) in ingest for per-MCP-server definition tokens (~4 chars/token); MCP table column; finding "N unused MCP servers add ~X tokens (~$Y)".
5. Docs: PRODUCT.md. Tests: fixture session with a sidechain request, empty range, estimates labelled.

Files: `tokscope/core/ingest.py`, `tokscope/features/projects.py`, `web/dashboard/pages/projects.py`, `pages/overview.py`, `web/report/sections/`, `PRODUCT.md`, `tests/test_ingest.py`, `tests/test_projects.py`, `tests/test_report.py`, `tests/test_dashboard.py`.

Verify: unit tests; scratch `TOKSCOPE_HOME` ingest of fixtures; screenshots at 1440 and 375 px.

## Likely conflicts between the two
- `PRODUCT.md` (both add feature entries): separate sections, rebase the second PR.
- `tests/test_dashboard.py`, `tests/test_report.py`: both add cases; use new classes / distinct places.
- `web/report/sections/` and report scripts: both add a section; they register in the same section list.
- `server.py`, `cli.py`, `README.md` are #89 only; `core/ingest.py` is #90 only; dashboard pages are mostly disjoint (breakdowns/summary vs projects/overview).
- Suggested order: #89 first (smaller), then #90 rebased.
