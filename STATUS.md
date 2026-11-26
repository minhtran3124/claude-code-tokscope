---
state: active         # active | paused | blocked | done
progress: 44          # rough estimate, 0-100
priority: medium     # high | medium | low
updated: 2026-11-26
updated_by: claude   # claude | manual
---

# claude-code-tokscope — Status

## Summary
Milestone 2 "Skill Optimize v2" (#187-#195): 4 of 9 issues are closed in `main`; the rest (#190, #192-#195) is merged into the integration branch `feat/skill-optimize-v2-b`. PR #221 takes that branch into `main`. #190 also reached `main` through PR #220; the branch keeps its own version, which the `/optimize` page calls.

## Next step
Review and merge PR #267 (Summary tab keeps the range and filters); then owner checks the Indigo redesign (#257) and merges PR #221 by hand.

## Blockers
- macOS app (#144-#148) cannot be verified without a Mac.

## Recent
- 2026-11-26: Sessions take the title from `custom-title` (the last one wins over `ai-title`) and, with no title and no counted prompt, from the first cross-session message; parser version 26 re-reads old sessions (#268, PR #269, reviewed, CI green).
- 2026-11-21: Replaced the repo's own `.claude/` (factory skill, agents, hooks, rules) with the pd-bot plugin: ran pd-setup (specs/ and docs/solutions/ scaffold, deny rules in `.claude/settings.json`) and updated CLAUDE.md (Run and test, pd-bot workflow section) (PR #264, merged). Market research picked the next feature: `summary --by version|entrypoint` (#265), built on the CLI, API, Breakdowns tabs and report with a not-a-cause note (PR #266, merged). Manual test of #266 on the Mac app passed except one check: the range tabs and filter form dropped the Summary tab (?by=), also true on main; fixed in PR #267 (open, review pending).
- 2026-11-12: Subagent rows with no `description` in `meta.json` (SDK/bridge sessions) now take the title from the parent's Agent call input; parser version 25 re-reads old sessions (PR open). Redesign with the Indigo look (#257), step 1 of 5: new colour tokens in light and dark, bundled Hanken Grotesk and DM Mono, line icons in the left menu, restyled buttons, chips, tabs and the compare tray; the desktop loading screen and icon follow (PR #258, merged). Step 2: Overview gets six stat-tile cards, Needs a look icons, tinted skill chips in Biggest movers and a Share of all tokens card; Sessions rows show the project under the title and a tinted top-skill chip, the sort is one joined control; the opened session gets a sunken id box (PR #260, merged). The 8 small findings from its review are fixed (PR #261, merged). Steps 3 and 4: Breakdowns, Projects, Library, Optimize, Benchmarks, Managed and Settings restyled; Library has no median-tokens column (no per-skill figure exists) (PR #262, merged). Step 5: AA status fills, Indigo design prompt, stale Ink wording removed, README screenshots retaken, report and colour-blind checks (PR open).
- 2026-11-06: Projects page: List/Cards toggle, find box, sort (tokens, cost, sessions, latest activity, session start, name) and Remove, which only hides the folder in projects.json after a question; "Removed from this list" restores it (PR open).
- 2026-11-06: Optimize list (#252): decision-first page with a top card (runs needing a decision, Review newest), filter links, runs grouped by skill then decision need, verdict pills, one result line and relative time; the Decision column is gone (PR open).
- 2026-11-06: Sessions: a Project dropdown next to the filter box lists the projects in the range (with session counts) and filters the list at once (PR #245). Optimize run page (#249): Decide block first (verdict, rule-built sentence, three numbers, gate chips, Approve/Reject), then diff, plain-word gates and two Change tables, then one-line collapsed rows; at 375 px Approve and Reject sit in the first screen (PR open). The dashboard no longer prints a traceback when a browser drops the connection mid-page (BrokenPipeError; PR open).
- 2026-11-06: Added a root `Makefile`: `make deb` (rebuild + install the .deb), `make dev` (run the desktop app from the clone), `make serve`, `make test` (PR open). The page now uses the full window width: the 1180 px and 1460 px caps are gone (PR open). Fixed an optimize preflight crash when a system event had a string message (PR open). Library: a skill with no usable eval suite shows a plain-words card and a Generate button that drafts the suite in the background with one capped `claude -p` call (PR open).
- 2026-11-06: Library: a clear "Run optimize" button on each of your skill cards and on the skill page (PR open). The desktop `reinstall-deb.sh` restarts the tokscope user service after installing, so a new build is not shown with the old code (PR open); `desktop/scripts/dev.sh` runs the app from the clone with no .deb or sudo (PR open).
- 2026-11-06: Fixed the header date range overlapping the filters: it now sits on the line under the page title (PR open).
- 2026-11-06: Overview: the Today card is flat (no offset shadow over the KPI strip) (PR open).
- 2026-11-06: Sessions got its right rail (This range, Biggest session with a main/subagent split) (PR open). All screens now have a design-match PR merged.
