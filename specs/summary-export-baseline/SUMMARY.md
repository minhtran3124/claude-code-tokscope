# Summary: summary export (#89) and always-on baseline (#90)

Merged result of PR #91 and PR #92 on `feat/summary-export-baseline` (tip ea048c8). Suite: 378 tests OK. ruff is not installed, so lint was skipped.

## Shipped
- #89: `core/summary.py` holds the rows once. `tokscope summary --format table|json|csv` (default unchanged; json/csv print only data, notes on stderr). `GET /api/summary?by=&format=json|csv` with the filter-bar filters and the usual host/site checks. A Summary section on Breakdowns (group-by in `?by=`, Download CSV/JSON, Copy, notes) and the same downloads in the HTML report, built in the browser from embedded rows.
- #90: `core/baseline.py` (first main-thread request per session, median, p90, 30-day trend, session-start cost at the cache-write rate), `mcp_defs` table from the `shape` record (parser v15), session-start line on Overview, Projects and the report, per-server definition tokens and an unused-server finding, all marked `~` with a method tooltip. No sessions in range shows an empty state, no error.

## Smoke test
`bin/tokscope summary --by skill --format csv` on an empty throwaway TOKSCOPE_HOME printed only `key,requests,prompt_tokens,output_tokens,cost_usd,carried_cost_usd`; `--format json` printed `[]`; the API-equivalent note went to stderr.

## Gaps (small, not blocking)
- Downloads use the table's row limit (25), not every group.
- The filter bar's Apply drops the group-by from the URL (the group-by links keep the filters).
- The Download/Copy buttons were checked in Chromium, not in the Electron desktop app (same page code).
- The Overview baseline line ignores the model and skill filters.
- The merged UI was not re-shot; the sub-PR screenshots (#91, #92) cover each part.
