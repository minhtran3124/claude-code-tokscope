---
state: active        # active | paused | blocked | done
progress: 0          # rough estimate, 0-100
priority: medium     # high | medium | low
updated: 2026-10-21
updated_by: claude   # claude | manual
---

# claude-code-tokscope — Status

## Summary
Ink redesign in progress on branch `v1`: brand mark (#4) merged, design-prompt fixes (#5) and the palette swap open as PRs to `v1`.

## Next step
Merge the README screenshots PR, then fix the CI billing block (GitHub says the account's payments failed) so the workflow can run.

## Blockers
- GitHub Actions jobs do not start: account payment or spending limit (see Settings > Billing).

## Recent
- 2026-10-21: released 0.1.0, merged the worktree-folding fix (#1), setup.sh, repo About and topics, design update (borders, colours, weights, fonts); fixed the review findings (amber text, mono weights); README screenshots (redacted); docs/design-prompt.md: ink style adapted for tokscope; brand mark and favicon redrawn in ink (PR opened); #4 and #6 (ink palette) merged to v1; design-prompt fixes (#5) rebased onto them; ink shapes PR to v1; ink type PR to v1
- 2026-10-19: created STATUS.md
