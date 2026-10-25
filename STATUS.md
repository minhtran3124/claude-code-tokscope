---
state: active        # active | paused | blocked | done
progress: 90          # rough estimate, 0-100
priority: medium     # high | medium | low
updated: 2026-10-25
updated_by: claude   # claude | manual
---

# claude-code-tokscope — Status

## Summary
#50 OTel receiver is done on `feat/otel-receiver` (final PR to main): `tokscope otel-receiver`, size caps, loopback only, README says nothing reads the data yet; 590 tests pass. macOS app #144-#148 is on `feat/macos-app`, unverified without a Mac.

## Next step
Review the #50 PR; on the M2: `cd desktop && npm run dist:mac`, open the app, report what fails. #58 is done on `feat/otel-ingest`: review its PR.

## Blockers
- GitHub Actions jobs did not start on 2026-10-25 (annotation: payment failed or spending limit; the runs on 2026-10-22 passed). Settings > Billing. Until then the new `lint` job and the 3.11 leg have not run on GitHub; both pass locally.

## Recent
- 2026-10-25: #58 OTel `api_request` events ingested (`core/otel.py`, `otel_requests`, `ingest --otel [DIR]`, matched to requests by session, tokens and time); Cost check card in report and dashboard Overview (drift per model, unmatched, telemetry only); 608 tests pass, ruff clean.
- 2026-10-25: #50 OTel receiver moved into the package (`tokscope otel-receiver`, `integrations/otel_receiver.py`), body and gzip size caps, loopback-only unless `--allow-remote`, README section says no view reads it yet (#58); 590 tests pass; no UI change.
- 2026-10-25: macOS app #144-#148 combined on feat/macos-app (PRs 149-153), final PR to main; 575 tests pass; no UI change; build and menus unverified without a Mac.
- 2026-10-25: #51 CI matrix adds 3.11, new ruff lint job, 10 ruff findings fixed (unused imports, shadowed names); the STATUS blocker stays because Actions still fail to start on billing.
- 2026-10-25: skill features #132-#136 combined on feat/skill-features (PRs 137-141), final PR to main; 535 tests pass; screenshots are in the sub-PRs.
- 2026-10-25: skill bugs #117-#123 combined on fix/skill-bugs-2 (PRs 124-130), final PR to main; 479 tests pass; no UI change.
- 2026-10-25: skill bugs #106-#110 combined on fix/skill-bugs (PRs 111-115), final PR to main; 455 tests pass; #110 lacks hosted screenshots.
- 2026-10-25: analytics #54-#57 combined on feat/analytics-54-57 (PRs 100-103), final PR to main; 430 tests pass; #54 official miss_causes need statusline snapshots, not stored yet.
- 2026-10-25: #54 official miss_causes: `statusline_snapshots` table, `cache.record_snapshot` (counters only), `cache.official_by` (skill/phase), Breakdowns tables; 450 tests pass; no screenshots yet; analytics #54-#57 combined on feat/analytics-54-57 (PRs 100-103), final PR to main; 430 tests pass; #54 official miss_causes need statusline snapshots, not stored yet.
- 2026-10-24: #97 `tokscope serve --projects-dir PATH` (a UAT server with a throwaway home no longer ingests every transcript: 40 sample files gave 40 sessions and a 1.9 MB database, against 44 MB); `uat.md` builds a sample and notes the `python -m` cwd and port-kill pitfalls from PR 94/96; PR #98 open (issue #97).
