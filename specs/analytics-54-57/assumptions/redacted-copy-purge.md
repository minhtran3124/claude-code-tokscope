# Assumption: fix the redacted copy once, not per section

PR #104, review-fix (score 75). A filtered redacted copy (by project or date) showed other projects' tool calls in the new Context and Errors sections.

## Decision
Purge `tool_calls` and `turn_events` of removed sessions inside `redacted_copy` (commit `5739ae6`, test in `tests/test_privacy.py`).

Why: one small change covers every reader of those tables, including readers added later.

## Alternative, not taken
Add a `session_id IN (...)` restriction to `context.load` and `errors.rows`, `totals` and `classes`.

Why not: four queries to change, and every new reader must remember the same rule.

## Impact
Sessions with tool calls but zero requests are also dropped under a filter. This is harmless because they are out of scope for the report.

*Artifact tool was unavailable (daily publish limit, 429), so this is the Markdown fallback.*
