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
- 2026-11-06: Overview: the Today card is flat (no offset shadow over the KPI strip) (PR open).
- 2026-11-06: Sessions got its right rail (This range, Biggest session with a main/subagent split) (PR open). All screens now have a design-match PR merged.
- 2026-11-06: Settings matches the design: one 760 px column, framed segmented controls, key pills and an About card (PR open). The Sessions rail is next.
- 2026-11-06: Overview matches the design more closely: rail order, equal KPI tiles, paired Session start and Models cards, plain table links (PR open). Settings and the Sessions rail are in progress.
- 2026-11-06: Benchmarks and Managed match the design: flat tables with verdict and status pills, per-task before/after cards, and a rail on each (PR open). The Benchmarks header no longer shows filters it ignored.
- 2026-11-06: Breakdowns matches the design: a rail (Needs a look, Share of all tokens), a Share bar column in the summary and one flat list of sections with bars and ok/warn pills (PR open).
- 2026-11-06: Projects matches the design: a table (sessions, tokens, API-eq, session start, MCP pills) with a rail (Needs a look, Session start by project) (PR open).
- 2026-11-06: Library matches the design: a right rail (Needs a look, description cost per session) and a cost bar on each skill card (PR open).
- 2026-11-06: Page header matches the design: slim top bar (name, range tabs, filters, dates), then a big title and one line in the body (PR open). Breakdowns, Projects, Library, Benchmarks and Managed are being matched in parallel.
- 2026-11-06: Owner found the screens do not match the approved design. Starting a per-screen pass: Sessions first (full-width main/subagent bar, right-aligned numbers, brighter top skill), then page header, Breakdowns, Projects, Library, Benchmarks, Managed.
