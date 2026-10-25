---
state: active        # active | paused | blocked | done
progress: 0          # rough estimate, 0-100
priority: medium     # high | medium | low
updated: 2026-10-25
updated_by: claude   # claude | manual
---

# claude-code-tokscope — Status

## Summary
Skill features #132-#136 are merged. #51: CI runs Python 3.10-3.13 and a ruff job (`E9,F`, config in pyproject.toml); the first findings are fixed; 538 tests pass locally.

## Next step
Fix GitHub billing so Actions run, then confirm the new lint job and 3.11 leg pass.

## Blockers
- GitHub Actions jobs did not start on 2026-10-25 (annotation: payment failed or spending limit; the runs on 2026-10-22 passed). Settings > Billing. Until then the new `lint` job and the 3.11 leg have not run on GitHub; both pass locally.

## Recent
- 2026-10-25: #51 CI matrix adds 3.11, new ruff lint job, 10 ruff findings fixed (unused imports, shadowed names); the STATUS blocker stays because Actions still fail to start on billing.
- 2026-10-25: skill features #132-#136 combined on feat/skill-features (PRs 137-141), final PR to main; 535 tests pass; screenshots are in the sub-PRs.
- 2026-10-25: skill bugs #117-#123 combined on fix/skill-bugs-2 (PRs 124-130), final PR to main; 479 tests pass; no UI change.
- 2026-10-25: skill bugs #106-#110 combined on fix/skill-bugs (PRs 111-115), final PR to main; 455 tests pass; #110 lacks hosted screenshots.
- 2026-10-25: analytics #54-#57 combined on feat/analytics-54-57 (PRs 100-103), final PR to main; 430 tests pass; #54 official miss_causes need statusline snapshots, not stored yet.
- 2026-10-25: #54 official miss_causes: `statusline_snapshots` table, `cache.record_snapshot` (counters only), `cache.official_by` (skill/phase), Breakdowns tables; 450 tests pass; no screenshots yet; analytics #54-#57 combined on feat/analytics-54-57 (PRs 100-103), final PR to main; 430 tests pass; #54 official miss_causes need statusline snapshots, not stored yet.
- 2026-10-24: #97 `tokscope serve --projects-dir PATH` (a UAT server with a throwaway home no longer ingests every transcript: 40 sample files gave 40 sessions and a 1.9 MB database, against 44 MB); `uat.md` builds a sample and notes the `python -m` cwd and port-kill pitfalls from PR 94/96; PR #98 open (issue #97).
- 2026-10-24: merged #95; first open showed a white window and the Overview took 2.8 s: `tz.local_day` now caches per minute (the SQL function ran strptime 144k times; Overview 2.8 s to 0.9 s on a 64 MB database), the desktop window opens at once with a loading page and the paper colour, and the dashboard shows a top bar and dims the page while the next page loads; PR open.
- 2026-10-24: merged #94 (Time zone setting), service restarted, desktop app reinstalled; desktop window did not open because the Overview takes about 2.7 s on this database and `desktop/main.js` probed it with a 2 s timeout (then started a second server and retried forever); it now probes `/api/version`; PR open.
- 2026-10-24: times follow a Time zone setting (Local default, UTC; sidebar control, saved in localStorage `tokscope-tz`): session rows, day groups, session detail, Latest session, skill change notes, optimize start and report stamp use `<time data-ts>` rewritten by `tzSync`; 384 tests pass; not yet checked in a browser.
- 2026-10-24: #89 summary export (`core/summary.py` rows for `tokscope summary --format table|json|csv`, `/api/summary`, a Summary section with Download CSV/JSON and Copy) and #90 always-on baseline (`core/baseline.py`, `mcp_defs` table, parser v15, session-start line on Overview, Projects and the report) merged on feat/summary-export-baseline, final PR #93 to main; review of #93 fixed: `starts()` one grouped query and skips sessions whose first request left the database (forks, filtered copies; `sessions.first_req_ts`, parser v16), cost priced at the real size, CSV/Copy cells that start with = + - @ get a quote; 383 tests pass.
