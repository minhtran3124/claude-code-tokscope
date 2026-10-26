---
state: active        # active | paused | blocked | done
progress: 90          # rough estimate, 0-100
priority: medium     # high | medium | low
updated: 2026-10-26
updated_by: claude   # claude | manual
---

# claude-code-tokscope — Status

## Summary
OTel receiver (#50, #157) and ingest (#58, #158) are done on `feat/otel-leftovers`: hardened receiver, deduped and linear ingest, prompt.id join; 634 tests, 1 pre-existing failure (`test_week_finding_compares_with_the_week_before`). macOS app #144-#148 is unverified without a Mac.

## Next step
Review the final PR `feat/otel-leftovers` -> main; on the M2: `cd desktop && npm run dist:mac` and report what fails.

## Blockers
- GitHub Actions jobs did not start on 2026-10-25 (annotation: payment failed or spending limit; the runs on 2026-10-22 passed). Settings > Billing. Until then the new `lint` job and the 3.11 leg have not run on GitHub; both pass locally.

## Recent
- 2026-10-26: Sessions: an opened session is one tinted panel (summary row and body, `--tint` plus a mark left edge, both skins and dark); PR #167, review fixes: dead open-row CSS removed, opened+picked rule.
- 2026-10-26: Sessions filter by folder with a reason chip (PR #165, review rounds 1 and 2 fixed); 640 tests pass.
- 2026-10-26: Today row alignment (owner: Today and N sessions running on one line): dots and text share one baseline (`.live-head>h2{align-items:baseline}`), `.runnow` is a grid so the note starts at the label edge for any count (measured 0.0 px at 1, 3, 12 sessions); 636 tests pass, ruff clean.
- 2026-10-26: Overview Today card: heading and "N sessions running" share one row (`.live-head`, wraps on narrow screens); review fixes: region shrinks so a long note wraps inside it, spacing only on `.live-head`, stronger test; 636 tests pass, ruff clean; screenshots in the PR.
- 2026-10-25: #157/#158 combined on feat/otel-leftovers (PRs 159, 160), final PR to main; checked end to end on ::1 in a temp home (duplicate post ingested once, deep JSON 400, modes 700/600); no UI change.
- 2026-10-25: #158 OTel ingest: dedupe key plus unique index (migration drops stored duplicates), match() n log n, reader goes line by line, statusline `prompt_id` stored and joined to OTel events in `cache.official_by`; no UI change.
- 2026-10-25: PR #156 review fix: a malformed or hostile OTel line is skipped per line (offset still advances) and cannot stop the skills steps; a transient DB error (locked, disk full) now propagates so the offset is not advanced; telemetry-only sessions (OTel events, no transcript) are tagged Sessions rows and in the Sessions, Tokens, Output, From cache and API-eq totals at Claude Code's cost_usd, so every #58 criterion is met; 623 tests pass.
- 2026-10-25: #58 OTel `api_request` events ingested (`core/otel.py`, `otel_requests`, `ingest --otel [DIR]`, matched to requests by session, tokens and time); Cost check card in report and dashboard Overview (drift per model, unmatched, telemetry only); 608 tests pass, ruff clean; checked end to end in a temp home (re-run adds nothing), final PR to main, summary in `specs/otel-ingest/SUMMARY.md`.
- 2026-10-25: #50 OTel receiver moved into the package (`tokscope otel-receiver`, `integrations/otel_receiver.py`), body and gzip size caps, loopback-only unless `--allow-remote`, README section says no view reads it yet (#58); 590 tests pass; no UI change.
- 2026-10-25: macOS app #144-#148 combined on feat/macos-app (PRs 149-153), final PR to main; 575 tests pass; no UI change; build and menus unverified without a Mac.
