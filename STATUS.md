---
state: blocked        # active | paused | blocked | done
progress: 90          # rough estimate, 0-100
priority: medium     # high | medium | low
updated: 2026-11-02
updated_by: claude   # claude | manual
---

# claude-code-tokscope — Status

## Summary
OTel receiver and ingest are done and merged, and recent work added dashboard polish: a Models card, Sessions folder filter and open-row panel. The macOS app (#144-#148) is unverified without a Mac. The last recorded run failed at the canary stage. A smaller logs-to-plan design (a CLI command and a skill) is in `docs/research-prompt-insights.md` (PR #170), not built yet.

## Next step
Fix the failed run 01M602P6H66Q15NXYZ7FJM45GP: get a fresh canary pass for the implement stage, then re-run it.

## Blockers
- GitHub Actions jobs stopped starting on 2026-10-25 (payment or spending limit); the new lint job and the 3.11 leg have not run on GitHub.
- Run 01M602P6H66Q15NXYZ7FJM45GP failed: the implement stage has no canary result.
- macOS app (#144-#148) cannot be verified without a Mac.

## Recent
- 2026-11-02: Research on the logs-to-plan idea: measured repetition on the local database (repeated real tasks are at most 8% of spend; 97% of tokens are cache reads), wrote `docs/research-prompt-insights.md` with the flow, 5 slices and risks (PR #170); no product code changed. An independent review overturned two conclusions, and the note is rewritten around 4 slices for the owner's goals (tokens, workflow, useful features). Trial runs: `/insights` works ($2.10, no token data), `autoCompactWindow` 100000 compacts and 80000 did nothing; numbers re-run, note fixes still open.
- 2026-10-28: run 01M602P6H66Q15NXYZ7FJM45GP (default) failed, 4 stage run(s): canary: stage implement needs a fresh canary pass (no canary result)
- 2026-10-26: Overview gets a Models card (PR #168: models by request count, links to the model filter, region `models`); a follow-up shows exact counts and trims Recent to 10 lines.
- 2026-10-26: Rule added: one assumptions artifact per PR, all that PR's assumptions in it (`.claude/rules/behavior.md` #5); old per-assumption files left as they are.
- 2026-10-26: Sessions: an opened session is one tinted panel (summary row and body, `--tint` plus a mark left edge, both skins and dark); PR #167, review fixes: dead open-row CSS removed, opened+picked rule.
- 2026-10-26: Sessions filter by folder with a reason chip (PR #165, review rounds 1 and 2 fixed); 640 tests pass.
- 2026-10-26: Today row alignment (owner: Today and N sessions running on one line): dots and text share one baseline (`.live-head>h2{align-items:baseline}`), `.runnow` is a grid so the note starts at the label edge for any count (measured 0.0 px at 1, 3, 12 sessions); 636 tests pass, ruff clean.
- 2026-10-26: Overview Today card: heading and "N sessions running" share one row (`.live-head`, wraps on narrow screens); review fixes: region shrinks so a long note wraps inside it, spacing only on `.live-head`, stronger test; 636 tests pass, ruff clean; screenshots in the PR.
- 2026-10-25: #157/#158 combined on feat/otel-leftovers (PRs 159, 160), final PR to main; checked end to end on ::1 in a temp home (duplicate post ingested once, deep JSON 400, modes 700/600); no UI change.
- 2026-10-25: #158 OTel ingest: dedupe key plus unique index (migration drops stored duplicates), match() n log n, reader goes line by line, statusline `prompt_id` stored and joined to OTel events in `cache.official_by`; no UI change.
