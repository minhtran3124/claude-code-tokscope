---
state: active        # active | paused | blocked | done
progress: 0          # rough estimate, 0-100
priority: medium     # high | medium | low
updated: 2026-10-21
updated_by: claude   # claude | manual
---

# claude-code-tokscope — Status

## Summary
Version 0.1.0 is on `main` (PR #1 folded deleted worktrees into their repository). A design PR is open: darker light-mode borders, text-safe colours, one weight scale, and Be Vietnam Pro + IBM Plex Mono bundled.

## Next step
Review and merge the design PR, then fix the CI billing block (GitHub says the account's payments failed) so the workflow can run.

## Blockers
- GitHub Actions jobs do not start: account payment or spending limit (see Settings > Billing).

## Recent
- 2026-10-21: released 0.1.0, merged the worktree-folding fix (#1), setup.sh, repo About and topics, design update (borders, colours, weights, fonts)
- 2026-10-19: created STATUS.md
