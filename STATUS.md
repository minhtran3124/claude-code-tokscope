---
state: active         # active | paused | blocked | done
progress: 44          # rough estimate, 0-100
priority: medium     # high | medium | low
updated: 2026-11-06
updated_by: claude   # claude | manual
---

# claude-code-tokscope — Status

## Summary
Milestone 2 "Skill Optimize v2" (#187-#195): 4 of 9 issues are closed in `main`; the rest (#190, #192-#195) is merged into the integration branch `feat/skill-optimize-v2-b`. PR #221 takes that branch into `main`. #190 also reached `main` through PR #220; the branch keeps its own version, which the `/optimize` page calls.

## Next step
Owner reviews and merges PR #221 by hand.

## Blockers
- macOS app (#144-#148) cannot be verified without a Mac.

## Recent
- 2026-11-06: Fixed the dashboard header so the Project, Model and Skill filters stay on one row (PR open).
- 2026-11-06: Desktop `.deb` keeps only the en-US Electron locale (`electronLanguages`): 75.7 MB to 68.5 MB; PR open.
- 2026-11-06: Fixed the API-EQ tile cut-off on the Overview strip: tiles drop cents from $1,000, show K from $10,000, and the number shrinks to its tile width.
- 2026-11-06: Rebuilt the desktop `.deb` from `main` after removing the install.sh copy; added `desktop/scripts/reinstall-deb.sh` (rebuild and install over) and a README line; PR open.
- 2026-11-05: Resolved PR #221 conflicts with `main` (DECISIONS.md, STATUS.md). #193 removed the guide-based Optimize. #195 added a Real sessions card on an approved run. #192 added the `/optimize` page, Approve and Reject routes and Library start. Dashboard redesign steps merged into `main`, then `main` (with PR #220) merged into PR #221's branch. PR #221 security fixes: approve refuses symlinked subfolders, draft copies skip symlinks, and the commit reason stays on one line.
- 2026-11-05: Background service: `setup.sh` and the Linux desktop app (first launch) turn the user service on by themselves (#222); Settings page gets a Background service card (status, Stop/Start, Start automatically; PR 2). DECISIONS.md updated.
- 2026-11-04: #190 merged into the feat branch (PR #206): `tokscope optimize approve|reject|revert` installs the measured draft, commits only the skill's files and can finish or undo an interrupted apply.
- 2026-11-04: #194 merged into the feat branch (PR #207): description changes are gated by a trigger eval; a budget stop saves a partial state that resumes.
- 2026-11-04: Skill Optimize v2 slice 1: #187-#189 merged; final PR #200 merged into `main` (`073f017`).
- 2026-11-04: #180 and #181 shipped (final PR #185, `a895f3e`); milestone 1 closed. Brief `docs/research-skill-optimize.md` and milestone 2 (#187-#195, epic #196) created.
- 2026-11-04: PR #179 merged into `main` (`57ab775`); #171-#173 closed.
