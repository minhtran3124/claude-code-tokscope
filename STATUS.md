---
state: active        # active | paused | blocked | done
progress: 0          # rough estimate, 0-100
priority: medium     # high | medium | low
updated: 2026-10-25
updated_by: claude   # claude | manual
---

# claude-code-tokscope — Status

## Summary
Analytics #55-#57 are merged (PR #104). #54 is finished on feat/54-official-miss-causes: `tokscope statusline` stores the `prompt_cache` counters and Breakdowns groups official misses by skill and phase; 450 tests pass.

## Next step
Review and merge the #54 PR; then point Claude Code's statusLine at `tokscope statusline` to collect snapshots.

## Blockers
- GitHub Actions jobs do not start: account payment or spending limit (Settings > Billing).

## Recent
- 2026-10-25: #54 official miss_causes: `statusline_snapshots` table, `cache.record_snapshot` (counters only), `cache.official_by` (skill/phase), Breakdowns tables; 450 tests pass; no screenshots yet; analytics #54-#57 combined on feat/analytics-54-57 (PRs 100-103), final PR to main; 430 tests pass; #54 official miss_causes need statusline snapshots, not stored yet.
- 2026-10-24: #97 `tokscope serve --projects-dir PATH` (a UAT server with a throwaway home no longer ingests every transcript: 40 sample files gave 40 sessions and a 1.9 MB database, against 44 MB); `uat.md` builds a sample and notes the `python -m` cwd and port-kill pitfalls from PR 94/96; PR #98 open (issue #97).
- 2026-10-24: merged #95; first open showed a white window and the Overview took 2.8 s: `tz.local_day` now caches per minute (the SQL function ran strptime 144k times; Overview 2.8 s to 0.9 s on a 64 MB database), the desktop window opens at once with a loading page and the paper colour, and the dashboard shows a top bar and dims the page while the next page loads; PR open.
- 2026-10-24: merged #94 (Time zone setting), service restarted, desktop app reinstalled; desktop window did not open because the Overview takes about 2.7 s on this database and `desktop/main.js` probed it with a 2 s timeout (then started a second server and retried forever); it now probes `/api/version`; PR open.
- 2026-10-24: times follow a Time zone setting (Local default, UTC; sidebar control, saved in localStorage `tokscope-tz`): session rows, day groups, session detail, Latest session, skill change notes, optimize start and report stamp use `<time data-ts>` rewritten by `tzSync`; 384 tests pass; not yet checked in a browser.
- 2026-10-24: #89 summary export (`core/summary.py` rows for `tokscope summary --format table|json|csv`, `/api/summary`, a Summary section with Download CSV/JSON and Copy) and #90 always-on baseline (`core/baseline.py`, `mcp_defs` table, parser v15, session-start line on Overview, Projects and the report) merged on feat/summary-export-baseline, final PR #93 to main; review of #93 fixed: `starts()` one grouped query and skips sessions whose first request left the database (forks, filtered copies; `sessions.first_req_ts`, parser v16), cost priced at the real size, CSV/Copy cells that start with = + - @ get a quote; 383 tests pass.
- 2026-10-24: ingest hardening (#47, #48, #49) combined on feat/ingest-hardening, final PR to main; 345 tests pass; #48 chip lacks screenshots.
- 2026-10-24: #47 transcripts folders: `paths.projects_dirs()` ($CLAUDE_CONFIG_DIR list, else XDG + ~/.claude), `ingest --projects-dir`, ingest prints the folders; 335 tests pass.
- 2026-10-24: confirmed #46 with a real fork and fixed it (one session keeps a shared request).
- 2026-10-24: running sessions: `features/live.py` reads `~/.claude/sessions/*.json` (pid alive, status busy or idle, entrypoint), `/api/live`, Overview "N sessions running" with a pulsing dot while any works, Sessions rows tagged "running · Terminal" or "open · VS Code"; 302 tests pass; checked at 1440 and 375 px (phone shows the dot only); PR #75 merged; desktop app rebuilt (install.sh) and service restarted on main.
