# Plan: issues #54-#57 (integration branch feat/analytics-54-57)

## Order
1. #57 errors/retries/interrupts and #55 context findings (independent, both may touch core/ingest.py: do #57 first, then #55 rebases; bump PARSER_VERSION once per PR, currently 16).
2. #54 prompt cache and #56 budgets (after #57/#55, so shared ingest/Breakdowns edits are settled).

## Statusline snapshots: do not exist
Searched `grep -rniE "statusline|status_line|prompt_cache|rate_limits"` over the repo (excl. .git, node_modules): only hits are a slash-command name list (core/ingest.py:37) and BUILTIN_AGENTS (core/privacy.py:70). No `tokscope statusline` command, no `statusline.py`, no snapshot storage, no `prompt_cache`/quota fields. "snapshot" in the code means skill-version snapshots (core/skills.py), unrelated. `mod/hooks/register.tsx`, `mod/hooks/hooks.json`, `mod/tests/tokscope.test.ts` exist; `mod/types/` does not.
- #54: build the transcript-derived part fully. The official `miss_causes` part is conditional: read from a snapshot table only if present, show nothing (labelled official when shown) when absent. No snapshot writer is in scope of #54.
- #56: quota % budgets (`block_pct`, `weekly_pct`) need snapshots; skip them with state "no data" when none. `tokscope statusline` does not exist; record the gap as an assumption (statusline flag deferred) unless a minimal command is cheap.
- Neither issue depends on the other. A shared snapshot store (new `tokscope/core/snapshots.py`) would be a separate decision.

## Real file locations (issue paths are stale)
Core: `tokscope/core/{ingest,calls,skills,summary,pricing}.py`. Features: `tokscope/features/{changes,library,live,projects}.py`. Experiments: `tokscope/experiments/{bench,replay}.py`. Dashboard: `tokscope/web/dashboard/pages/{overview,breakdowns,library,projects,sessions,benchmarks}.py`, `scripts.py`, `shell.py`, `server.py`. Report: `tokscope/web/report/sections/{summary,breakdowns,skills,sessions,benchmarks}.py`. CLI: `tokscope/cli.py`. Paths: `tokscope/paths.py`. Rule: core never imports features/web (tests/test_layout.py).

| Issue | Core | Features / experiments | Web | CLI / other | Tests |
|---|---|---|---|---|---|
| #57 errors | core/ingest.py (tool_calls cols is_error, err_class, dup; interrupts; API errors; PARSER_VERSION 17; ALTER TABLE pattern ~line 508), core/calls.py, core/skills.py | features/changes.py, features/library.py, experiments/bench.py, replay.py | pages/breakdowns.py, pages/library.py (Versions card), report/sections/breakdowns.py, skills.py | cli.py `summary --by skill --errors` (core/summary.py), `change` | tests/test_ingest.py, test_changes.py, test_summary_export.py |
| #55 context | core/calls.py (percentiles, carry cost), core/ingest.py (compaction markers if not stored), core/pricing.py | - | pages/breakdowns.py "Context", pages/projects.py (MCP p95), report/sections/breakdowns.py | - | tests/test_dashboard.py, test_report.py, test_projects.py |
| #54 cache | new core/cache.py | - | pages/breakdowns.py "Prompt cache", pages/overview.py finding, report/sections/breakdowns.py + summary.py | - | new tests/test_cache.py, test_dashboard.py, test_report.py |
| #56 budgets | new core/budgets.py (pure, no web imports), paths.py | - | pages/overview.py (budget bars) | cli.py `check --once [--json]` exit 0/10/11/30; mod/hooks/register.tsx; SessionEnd ingest line; README.md | new tests/test_budgets.py, mod/tests/tokscope.test.ts |

All four touch web/, so each PR needs before/after screenshots at 1440 and 375 plus a Done-when table (.claude/skills/factory/references/uat.md).

## Acceptance commands
- All: `python3 -m unittest discover -s tests -q` (baseline: 389 tests OK; only thread ResourceWarnings).
- #57: `python3 -m unittest tests.test_ingest tests.test_changes -q`; `bin/tokscope summary --by skill --errors`; Library Versions card and `bin/tokscope change` show error rate.
- #55: `python3 -m unittest tests.test_dashboard tests.test_report tests.test_projects -q`; Breakdowns "Context" via `bin/tokscope serve`; Projects MCP rows show p95 with `~`.
- #54: `python3 -m unittest tests.test_cache -q`; Breakdowns "Prompt cache" and its empty state; Overview finding.
- #56: `python3 -m unittest tests.test_budgets -q`; `bin/tokscope check --once; echo $?` gives 0/10/11/30; invalid budgets.json gives a clear error.
