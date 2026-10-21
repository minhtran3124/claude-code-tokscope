---
state: active        # active | paused | blocked | done
progress: 0          # rough estimate, 0-100
priority: medium     # high | medium | low
updated: 2026-10-21
updated_by: claude   # claude | manual
---

# claude-code-tokscope — Status

## Summary
The ink redesign and headless child sessions (`claude -p` under their parent) are on `main`. The Classic/Ink switch is permanent (#18). #22 (merged, closes #21) removed the Skills page: the Library filters by project and shows skill versions on each skill page.

## Next step
Fix CI billing so GitHub Actions run.

## Blockers
- GitHub Actions jobs do not start: account payment or spending limit (see Settings > Billing).

## Recent
- 2026-10-21: tagged v0.1.0 and published the release (the changelog's Unreleased notes folded into 0.1.0); earlier: 0.1.0 prepared, merged the worktree-folding fix (#1), setup.sh, repo About and topics, design update (borders, colours, weights, fonts); fixed the review findings (amber text, mono weights); README screenshots (redacted); docs/design-prompt.md: ink style adapted for tokscope; brand mark and favicon redrawn in ink (PR opened); #4 and #6 (ink palette) merged to v1; design-prompt fixes (#5) rebased onto them; ink shapes PR to v1; ink type PR to v1; #7 shapes and #9 type merged to v1; README screenshots retaken in the ink style; filed #8 (headless child sessions) and merged it to v1 as #11 after fixing all review findings; #8 headless-link review: fix PR for exact-match calls adopting window runs and prompt paths as folders; #8 follow-ups PR (from-link, collapse, DECISIONS.md, upgrade note); #13 merged; temporary Classic/Ink switch PR; v1 merged to main (#15), #8 closed; Claude Code config (CLAUDE.md, REVIEW.md, .claude/) committed; Classic/Ink switch removed, #15 review fixes (focus ring, cross-project parent title, link pass writes only changes, dead code); checked the light/dark theme button (present); restored the Classic/Ink switch as permanent at the owner's request (#18), plus Classic session nesting and docstring fixes from its review; stopped the dashboard server; merged #18 to main; checked the "New data · reload" button in Ink (present, but a small dark pill); pages now check for new data every 2 s instead of 5 (#19; review fix: the version check skips the redacted database copy); Skills page now follows the filters, and the filter bar has an Apply button (#20, merged); merged #19; filed #21 and opened PR #22 for it (Skills page into the Library, project filter); reviewed; fixed the hidden filter bar and the malformed-hash crash; merged #22
- 2026-10-19: created STATUS.md
