---
state: active        # active | paused | blocked | done
progress: 0          # rough estimate, 0-100
priority: medium     # high | medium | low
updated: 2026-10-24
updated_by: claude   # claude | manual
---

# claude-code-tokscope — Status

## Summary
On main at v0.2.0: dashboard redesign (#23), Managed page with Pause/Unpause and agent config view, and the desktop app are merged. The latest work added running sessions (#75): Overview counts the open sessions with a pulsing dot, Sessions rows show where each runs; before that, report.py and dashboard.py were split into packages (#73, #74).

## Next step
Try Pause / Unpause once on a real deployment; then close #23 after a look at the dashboard at 1440 and 375 px.

## Blockers
- GitHub Actions jobs do not start: account payment or spending limit (Settings > Billing).

## Recent
- 2026-10-24: #43 unpriced models: 9 rates added (Opus 4/4.1/4.5, Sonnet 4/4.5, Haiku 3.5, Mythos 5/5.1), snapshot suffix must be 8 digits, `unpriced:` notice in summary, session, report and Overview, PARSER_VERSION 12; 309 tests pass; PR on fix/bug-issues.
- 2026-10-24: running sessions: `features/live.py` reads `~/.claude/sessions/*.json` (pid alive, status busy or idle, entrypoint), `/api/live`, Overview "N sessions running" with a pulsing dot while any works, Sessions rows tagged "running · Terminal" or "open · VS Code"; 302 tests pass; checked at 1440 and 375 px (phone shows the dot only); PR #75 merged; desktop app rebuilt (install.sh) and service restarted on main.
- 2026-10-22: split `web/report.py` (1,022 lines) into `web/report/` (common, styles, scripts, widgets, sections/, writer; report byte-identical at full, redacted and numbers, 25 dashboard URLs identical; PR #74 reviewed, nothing found, merged; service restarted); split `web/dashboard.py` (1,835 lines) into the package `web/dashboard/` (common, pages/ one per page, scripts, shell, server; HTML of 27 URLs byte-identical to main at full and redacted levels; PR #73 reviewed, nothing found, merged); restructured `tokscope/` into core, features, integrations, experiments, web and web/theme plus assets/ (research in docs/research-package-layout.md; `tests/test_layout.py` keeps imports one way; wheel and clone checked; PR #72 reviewed, 3 small points fixed, merged; service restarted); docs split (PR #71, merged; the security-review step no longer runs `git fetch -q origin`, which cannot work here, in CLAUDE.md, factory SKILL.md and the PR hook): CLAUDE.md cut to the rules, PRODUCT.md holds the features, README.md only install, run, the desktop app and how to build the .deb and install it on another machine, new redacted screenshots (Overview, Sessions, Breakdowns, Managed with demo data, report); released v0.2.0 (the #23 dashboard redesign): version bump and changelog entry (PR #40); tag v0.2.0 and GitHub release follow the merge; #63 Managed page (read only, PR #64): `tokscope/managed.py` reads deployments, sessions and agents through `ant`, full level only; review findings 1-4 fixed (unknown data shape shows as text, note wording, refresh test checks the fresh read); research in `docs/research-ant-managed-agents.md`; #65 Pause / Unpause buttons on Managed deployments (full level, asks first, button inside the status cell so the table still fits at 1440), PR #66 reviewed (5 reviewers + security, no finding scored 80) and all 5 sub-threshold findings fixed (write that landed despite an ant error counts as done, fullmatch id, docstring, a long pause reason wraps, OSError from ant); checked billing via ant with org:admin: no balance command, spend limits not supported for this org type, cost report needs a read:analytics API key (owner: not needed); merged #64 and #66 into main, then `desktop-app` (#59, #61, #62) into main; checked the desktop app on this machine: service restarted on the new code, Electron window shows the dashboard from 127.0.0.1:8770, the service could not find `ant` (`~/.local/bin` is not on the systemd user PATH), fixed by looking in user bin folders too (PR #68, merged; service restarted on main); clicking an agent on Managed opens its configuration (model, prompt, toolsets and permissions, MCP servers, skills), read only (#69, PR #70: review found nothing blocking, the 6 small points fixed, merged; service restarted).
- 2026-10-22: checked the subagents; all three (2 factory-implementer, 1 general-purpose) had already completed, nothing to close; merged the whole #23 stack into main (#25 to #29, #31, #33, #32; #31 and #34 had to land again as #36 and #37 because their stack base had already merged); main passes 271 tests.
- 2026-10-22: #23 reviews done and findings fixed; skin-tokens token test made strict (no longer skips tokens neither skin defines); merging the stack.
- 2026-10-22: #23 step 0 part 2: skins are tokens plus a look block (Ink 400 to 69 rules, Classic 385 to 87; value-only rules written once in layout.py); screenshots and computed styles identical to the base (PR open, on top of the stack).
- 2026-10-22: #23 step 5: phone layout under 640 px (52 px top bar, menu sheet, filter pill, 2-column KPIs, two-line table rows, 14-day chart) (PR open, stacked on step 1).
- 2026-10-22: #23 step 2: answer-first Overview (typical-day line and band, one KPI strip with per-day deltas, biggest movers, stacked daily tokens, one spenders container, labelled filters, segmented sidebar controls) (PR open).
- 2026-10-22: #23 step 4: Breakdowns sections show their finding in the summary line (share bar, empty-state hints); PR open on #26.
- 2026-10-22: #23 step 3: Sessions is a 44 px table grouped by day, with a sort control and a compare tray (PR open, stacked on step 1).
- 2026-10-22: #23 step 1: motion tokens, first-paint-only entrances, delta chip instead of count-up, one-ring live dot, per-rule reduced motion (PR open).
