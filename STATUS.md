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
- 2026-11-06: Breakdowns matches the design: a rail (Needs a look, Share of all tokens), a Share bar column in the summary and one flat list of sections with bars and ok/warn pills (PR open).
- 2026-11-06: Projects matches the design: a table (sessions, tokens, API-eq, session start, MCP pills) with a rail (Needs a look, Session start by project) (PR open).
- 2026-11-06: Library matches the design: a right rail (Needs a look, description cost per session) and a cost bar on each skill card (PR open).
- 2026-11-06: Page header matches the design: slim top bar (name, range tabs, filters, dates), then a big title and one line in the body (PR open). Breakdowns, Projects, Library, Benchmarks and Managed are being matched in parallel.
- 2026-11-06: Owner found the screens do not match the approved design. Starting a per-screen pass: Sessions first (full-width main/subagent bar, right-aligned numbers, brighter top skill), then page header, Breakdowns, Projects, Library, Benchmarks, Managed.
- 2026-11-06: Fixed the dashboard header so the Project, Model and Skill filters stay on one row (PR open).
- 2026-11-06: Desktop `.deb` keeps only the en-US Electron locale (`electronLanguages`): 75.7 MB to 68.5 MB; PR open.
- 2026-11-06: Fixed the API-EQ tile cut-off on the Overview strip: tiles drop cents from $1,000, show K from $10,000, and the number shrinks to its tile width.
- 2026-11-06: Rebuilt the desktop `.deb` from `main` after removing the install.sh copy; added `desktop/scripts/reinstall-deb.sh` (rebuild and install over) and a README line; PR open.
- 2026-11-05: Resolved PR #221 conflicts with `main` (DECISIONS.md, STATUS.md). #193 removed the guide-based Optimize. #195 added a Real sessions card on an approved run. #192 added the `/optimize` page, Approve and Reject routes and Library start. Dashboard redesign steps merged into `main`, then `main` (with PR #220) merged into PR #221's branch. PR #221 security fixes: approve refuses symlinked subfolders, draft copies skip symlinks, and the commit reason stays on one line.
