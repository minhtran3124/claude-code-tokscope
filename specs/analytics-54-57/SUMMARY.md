# Analytics 54-57: summary

Final tests: `python3 -m unittest discover -s tests -q` -> Ran 430 tests, OK.

## Shipped
- #55 Budgets and alerts (PR 100): `core/budgets.py`, `check --once` (0/10/11/30, 2 for a bad file), `statusline`, SessionEnd line, mod pane, Overview bars.
- #57 Errors, retries, interrupts (PR 101): ingest columns and `turn_events`, `core/errors.py`, `summary --errors`, Breakdowns Errors section, Versions card, `change`, bench and replay diffs.
- #54 Prompt cache (PR 102): `core/cache.py`, Breakdowns "Prompt cache" section, Overview 7-day re-cache card.
- #56 Context findings (PR 103): `core/context.py`, Breakdowns "Context" section, Projects MCP p95 column, compaction events.

## Gaps
- #54: official statusline `miss_causes` per session/skill/phase are shown only when snapshots exist, but snapshot storage does not exist yet. Heuristic causes work.
- #56: the Projects MCP p95 column is tested but not screenshotted.
