# Skill features #132-#136: summary

Combined on `feat/skill-features` (sub-PRs #137-#141, all merged into it). 535 tests pass.

## Shipped

| Issue | PR | What |
|---|---|---|
| #132 | #137 | `budgets.json` `regression` gate (`pct`, `min_loads`): `check --once` (exit 11), statusline, SessionEnd, Overview bars, report versions card |
| #133 | #139 | Library: "unused 90+ days" / "never used", Unused-only filter, sorts, `~` description tokens in the session prefix, finding |
| #134 | #138 | `skill_calls.failed` (parser v24); a failed load keeps the previous skill active; `summary --by skill --errors` `failed_loads`; Versions card column; DECISIONS.md rule |
| #135 | #141 | Loads by source (typed /command vs Skill tool) with medians in `summary --by skill`, report and Library Versions card |
| #136 | #140 | `tokscope skills --format table\|json\|csv`, formula-cell guard, README |

## Gaps

- None against the acceptance criteria (checked against the tests listed in the PR).
- `test_optimize ... test_a_running_job_can_be_cancelled_and_keeps_what_it_spent` was flaky once on the base (#139 note); it passed in the final run.
- Screenshots live in the sub-PRs (#137 in `docs/uat/`, #138/#139/#141 on `pr-assets`), not re-taken here.
