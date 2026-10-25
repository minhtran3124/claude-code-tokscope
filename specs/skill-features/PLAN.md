# skill-features plan (issues #132-#136)

Integration branch: `feat/skill-features` (from `github/main`). Tests: `python3 -m unittest discover -s tests -q` (baseline: 271 OK, 0 failures).
Remote is `github`. Sub-PRs do not edit STATUS.md. UI PRs (#132 report card, #133, #134 and #135 markup) need before/after screenshots at 1440 and 375 px and a pass/fail table (`.claude/skills/factory/references/uat.md`).

## Order
1. #132, #133, #134 first (independent; #134 changes ingest, so land it early).
2. #135, #136 after (both read per-skill rows; #136 should include the failed count from #134 and the source split from #135 where cheap; expect rebases in `core/skills.py` `versions()`).

## Dependencies
- #134 adds `skill_calls.failed` and bumps `PARSER_VERSION`; #135 and #136 extend `versions()` rows, so rebase on #134.
- #132 also consumes `versions()` (budgets). Keep new row keys additive.
- `core` must not import `features/` or `web/` (`tests/test_layout.py`).

## Per issue (real files; the issue text names old paths)
- #132 regression gate: `tokscope/core/budgets.py` (`load` L46 validation with `_number`/`_group`, `evaluate` L95 already calls `versions(conn, name)` ~L119, `check`, `warnings` L143, `crossed` L148, `text` L156). Compare newest vs previous version `tokens_median` from `core/skills.py versions()` (L481) with `loads` on both >= min_loads. Surfaces: `tokscope check --once`, `_budget_line` (SessionEnd) and `statusline` in `tokscope/cli.py` (L89, L116), report card `tokscope/web/report/sections/skills.py _skill_versions` (L23), dashboard Library Versions card `tokscope/web/dashboard/pages/library.py` (L423). Document in README (exit codes). Tests: `tests/test_budgets.py`, `tests/test_skills.py`.
  Accept: `python3 -m unittest tests.test_budgets tests.test_skills -q`; +30%/5 loads flags, +30%/3 loads no, -30% no, single version no; invalid config gives a clear error.
- #133 dead and heavy skills: `tokscope/features/library.py` `usage()` (L138; loads, last use), `discover()` (L105; frontmatter description), `tokscope/core/baseline.py` (always-on baseline). UI: `tokscope/web/dashboard/pages/library.py` (`_skill_card` L24, `_library_list` L38, `page_library` L429) and a finding on `web/dashboard/pages/overview.py`. 4 chars per token, `~` mark plus tooltip. Tests: `tests/test_library.py`, `tests/test_dashboard.py`.
  Accept: `python3 -m unittest tests.test_library tests.test_dashboard -q`; used/unused/never-used fixtures; screenshots.
- #134 failed skill loads: `tokscope/core/ingest.py` (`_load_skill` ~L492 sets `state["skill"]`/phase before the result is known; tool_result `is_error` handled ~L463; `skill_calls` schema L83 and the ALTER block ~L605-610; `PARSER_VERSION` L114, bump it). Defer activation to the matching tool_result, or restore the previous skill/phase on error. Rule goes in `DECISIONS.md`. Show in `core/skills.py versions()` (failed count), Library Versions card, and `summary --by skill --errors` (`tokscope/core/summary.py`, summary parser in `cli.py` ~L363). Tests: `tests/test_ingest.py`, `tests/test_summary_export.py`.
  Accept: `python3 -m unittest tests.test_ingest tests.test_skills tests.test_summary_export -q`; Skill(nonexistent) error keeps prior skill and counts 1 failed; per-session token totals unchanged.
- #135 manual vs model loads: `skill_calls.source` ('command' | 'tool'); `core/skills.py versions()` (per-source loads and medians), `core/summary.py` (`summary --by skill`), `web/report/sections/skills.py`, `web/dashboard/pages/library.py` Versions card. Empty source shows nothing extra. Tests: `tests/test_skills.py`, `tests/test_summary_export.py`.
  Accept: `python3 -m unittest tests.test_skills tests.test_summary_export -q`; fixture with both kinds; screenshots.
- #136 skills export: `tokscope/cli.py` (`skills_text` L146, `skills` parser L360, dispatch L417) add `--format table|json|csv`; reuse `to_json`, `to_csv`, `safe_cell` from `tokscope/core/summary.py` (L32-42) for the injection guard. Fields: skill, version, loads, exact, median tokens, errors, repeats, interrupts, first/last seen. README mention. Tests: `tests/test_summary_export.py` or `tests/test_skills.py`.
  Accept: `python3 -m unittest tests.test_summary_export tests.test_skills -q`; table/json/csv fixture output and csv injection test.
