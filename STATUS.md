---
state: active        # active | paused | blocked | done
progress: 0          # rough estimate, 0-100
priority: medium     # high | medium | low
updated: 2026-10-21
updated_by: claude   # claude | manual
---

# claude-code-tokscope — Status

## Summary
Ink redesign continues on `v1`. PR #11 (headless `claude -p` child sessions shown indented under their parent, #8) is open to `v1` with screenshots and a clean review.

## Next step
Decide on PR #11's open review notes (background-call window can mislink, ghost fade of child rows), then merge it to `v1`.

## Blockers
- GitHub Actions jobs do not start: account payment or spending limit (see Settings > Billing).

## Recent
- 2026-10-21: released 0.1.0, merged the worktree-folding fix (#1), setup.sh, repo About and topics, design update (borders, colours, weights, fonts); fixed the review findings (amber text, mono weights); README screenshots (redacted); docs/design-prompt.md: ink style adapted for tokscope; brand mark and favicon redrawn in ink (PR opened); #4 and #6 (ink palette) merged to v1; design-prompt fixes (#5) rebased onto them; ink shapes PR to v1; investigated headless `claude -p` child sessions and filed #8 (indent them under their parent session) and implemented it (PR #11 to v1; review: 0 findings ≥80, security: 0)
- 2026-10-19: created STATUS.md
