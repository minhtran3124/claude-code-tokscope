---
state: active        # active | paused | blocked | done
progress: 0          # rough estimate, 0-100
priority: medium     # high | medium | low
updated: 2026-10-21
updated_by: claude   # claude | manual
---

# claude-code-tokscope — Status

## Summary
Ink redesign is complete on branch `v1`: brand mark (#4), palette (#6), design-prompt fixes (#5), shapes (#7) and type (#9) are merged, and the README screenshots show the new look. `main` still has the old design.

## Next step
Owner review of `v1`, then merge `v1` into `main`. CI is still blocked by GitHub billing.

## Blockers
- GitHub Actions jobs do not start: account payment or spending limit (see Settings > Billing).

## Recent
- 2026-10-21: released 0.1.0, merged the worktree-folding fix (#1), setup.sh, repo About and topics, design update (borders, colours, weights, fonts); fixed the review findings (amber text, mono weights); README screenshots (redacted); docs/design-prompt.md: ink style adapted for tokscope; brand mark and favicon redrawn in ink (PR opened); #4 and #6 (ink palette) merged to v1; design-prompt fixes (#5) rebased onto them; ink shapes PR to v1; ink type PR to v1; #7 shapes and #9 type merged to v1; README screenshots retaken in the ink style
- 2026-10-19: created STATUS.md
