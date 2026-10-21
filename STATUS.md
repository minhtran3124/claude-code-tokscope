---
state: active        # active | paused | blocked | done
progress: 0          # rough estimate, 0-100
priority: medium     # high | medium | low
updated: 2026-10-21
updated_by: claude   # claude | manual
---

# claude-code-tokscope — Status

## Summary
The ink redesign and headless child sessions (#8) are on `main` (PR #15, merged 2026-10-21). A temporary Classic/Ink switch (#14) is still in the code for comparison.

## Next step
Remove the temporary Classic/Ink switch (checklist in `tokscope/classic.py`). CI is still blocked by GitHub billing.

## Blockers
- GitHub Actions jobs do not start: account payment or spending limit (see Settings > Billing).

## Recent
- 2026-10-21: released 0.1.0, merged the worktree-folding fix (#1), setup.sh, repo About and topics, design update (borders, colours, weights, fonts); fixed the review findings (amber text, mono weights); README screenshots (redacted); docs/design-prompt.md: ink style adapted for tokscope; brand mark and favicon redrawn in ink (PR opened); #4 and #6 (ink palette) merged to v1; design-prompt fixes (#5) rebased onto them; ink shapes PR to v1; ink type PR to v1; #7 shapes and #9 type merged to v1; README screenshots retaken in the ink style; filed #8 (headless child sessions) and merged it to v1 as #11 after fixing all review findings; #8 headless-link review: fix PR for exact-match calls adopting window runs and prompt paths as folders; #8 follow-ups PR (from-link, collapse, DECISIONS.md, upgrade note); #13 merged; temporary Classic/Ink switch PR; v1 merged to main (#15), #8 closed; Claude Code config (CLAUDE.md, REVIEW.md, .claude/) committed
- 2026-10-19: created STATUS.md
