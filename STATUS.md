---
state: active         # active | paused | blocked | done
progress: 0           # rough estimate, 0-100
priority: medium     # high | medium | low
updated: 2026-11-02
updated_by: claude   # claude | manual
---

# claude-code-tokscope — Status

## Summary
Milestone 1 (logs to enhancement plan) is built: `tokscope patterns` (#171), the automatic `changes` row (#172) and the 300K context nudge (#173) are on `feat/logs-to-enhancement-plan`, and the final PR to `main` is open. The macOS app (#144-#148) is unverified without a Mac.

## Next step
Merge the final PR, close #171-#173, try the nudge in a real session (UAT did not run), and look at `tokscope patterns` on real data before ticketing the held skill slice.

## Blockers
- macOS app (#144-#148) cannot be verified without a Mac.

## Recent
- 2026-11-02: #173 implemented: `session --json` carries `context`; the mod toasts once per session at 300K and adds a pane line; `/tokscope nudge on|off` persists; docs updated. Removed the unused `compacted` field and merged PR #178 into the feat branch; final PR to `main` opened. Review fixes on the final PR: `patterns` masks quoted keys, `_KEY` names, URL passwords, glpat/xox/Stripe/npm tokens and Basic auth; in-prompt cost subtracts inherited reads with the request's own fast, US and long-Haiku factors; the facets read skips symlinks, non-files and files over 1 MiB.
- 2026-11-02: Autopilot run wf_4df1b949-bd0: PRs #176 and #175 opened, none merged; gates failed on review, intent and needs_review (#176) and flaky CI (#175); #173 skipped. GitHub Actions runs again. Fixed the CI flakes in PR #177 (a refused OTel body is now read before its 413; reviews: 2 Important fixed, 0 security) and #176's facets privacy finding (below `full`, only known outcomes). Owner merged #177 into `main` and #175 and #176 into the feat branch, accepting #176's 4 `needs_review` items.
- 2026-11-02: Research on the logs-to-plan idea: measured repetition on the local database (repeated real tasks are at most 8% of spend; 97% of tokens are cache reads), wrote `docs/research-prompt-insights.md` with the flow, 5 slices and risks (PR #170); no product code changed. An independent review overturned two conclusions, and the note is rewritten around 4 slices for the owner's goals (tokens, workflow, useful features). Trial runs: `/insights` works ($2.10, no token data, facets give a quality signal), `autoCompactWindow` 100000 compacts and 80000 did nothing; numbers re-run and the note is updated. Review of PR #170 (1 consistency reviewer, 3 Important and 2 Nits) and a recent-window re-check changed the plan: grouping rules written down, skill slice held, nudge on with a toast and an off switch; milestone 1 and issues #171-#174 created.
- 2026-10-28: run 01M602P6H66Q15NXYZ7FJM45GP (default) failed, 4 stage run(s): canary: stage implement needs a fresh canary pass (no canary result)
- 2026-10-26: Overview gets a Models card (PR #168: models by request count, links to the model filter, region `models`); a follow-up shows exact counts and trims Recent to 10 lines.
- 2026-10-26: Rule added: one assumptions artifact per PR, all that PR's assumptions in it (`.claude/rules/behavior.md` #5); old per-assumption files left as they are.
- 2026-10-26: Sessions: an opened session is one tinted panel (summary row and body, `--tint` plus a mark left edge, both skins and dark); PR #167, review fixes: dead open-row CSS removed, opened+picked rule.
- 2026-10-26: Sessions filter by folder with a reason chip (PR #165, review rounds 1 and 2 fixed); 640 tests pass.
- 2026-10-26: Today row alignment (owner: Today and N sessions running on one line): dots and text share one baseline (`.live-head>h2{align-items:baseline}`), `.runnow` is a grid so the note starts at the label edge for any count (measured 0.0 px at 1, 3, 12 sessions); 636 tests pass, ruff clean.
- 2026-10-26: Overview Today card: heading and "N sessions running" share one row (`.live-head`, wraps on narrow screens); review fixes: region shrinks so a long note wraps inside it, spacing only on `.live-head`, stronger test; 636 tests pass, ruff clean; screenshots in the PR.
