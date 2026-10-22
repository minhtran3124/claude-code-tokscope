---
state: active        # active | paused | blocked | done
progress: 0          # rough estimate, 0-100
priority: medium     # high | medium | low
updated: 2026-10-22
updated_by: claude   # claude | manual
---

# claude-code-tokscope — Status

## Summary
v0.2.0 is on `main`. The Managed page lists Managed Agents through the `ant` CLI (#63, PR #64) and pauses or unpauses a deployment (#65, PR stacked on #64).

## Next step
Review and merge PR #64, then the #65 PR (retarget it to `main` after #64 merges).

## Blockers
- GitHub Actions jobs do not start: account payment or spending limit (see Settings > Billing).

## Recent
- 2026-10-22: released v0.2.0 (the #23 dashboard redesign): version bump and changelog entry (PR #40); tag v0.2.0 and GitHub release follow the merge; #63 Managed page (read only, PR #64): `tokscope/managed.py` reads deployments, sessions and agents through `ant`, full level only; review findings 1-4 fixed (unknown data shape shows as text, note wording, refresh test checks the fresh read); research in `docs/research-ant-managed-agents.md`; #65 Pause / Unpause buttons on Managed deployments (full level, asks first, button inside the status cell so the table still fits at 1440), PR #66 reviewed (5 reviewers + security, no finding scored 80) and all 5 sub-threshold findings fixed (write that landed despite an ant error counts as done, fullmatch id, docstring, a long pause reason wraps, OSError from ant).
- 2026-10-22: checked the subagents; all three (2 factory-implementer, 1 general-purpose) had already completed, nothing to close; merged the whole #23 stack into main (#25 to #29, #31, #33, #32; #31 and #34 had to land again as #36 and #37 because their stack base had already merged); main passes 271 tests.
- 2026-10-22: #23 reviews done and findings fixed; skin-tokens token test made strict (no longer skips tokens neither skin defines); merging the stack.
- 2026-10-22: #23 step 0 part 2: skins are tokens plus a look block (Ink 400 to 69 rules, Classic 385 to 87; value-only rules written once in layout.py); screenshots and computed styles identical to the base (PR open, on top of the stack).
- 2026-10-22: #23 step 5: phone layout under 640 px (52 px top bar, menu sheet, filter pill, 2-column KPIs, two-line table rows, 14-day chart) (PR open, stacked on step 1).
- 2026-10-22: #23 step 2: answer-first Overview (typical-day line and band, one KPI strip with per-day deltas, biggest movers, stacked daily tokens, one spenders container, labelled filters, segmented sidebar controls) (PR open).
- 2026-10-22: #23 step 4: Breakdowns sections show their finding in the summary line (share bar, empty-state hints); PR open on #26.
- 2026-10-22: #23 step 3: Sessions is a 44 px table grouped by day, with a sort control and a compare tray (PR open, stacked on step 1).
- 2026-10-22: #23 step 1: motion tokens, first-paint-only entrances, delta chip instead of count-up, one-ring live dot, per-rule reduced motion (PR open).
