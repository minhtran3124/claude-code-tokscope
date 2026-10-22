# UAT for UI changes

Read this when a PR changes what the owner sees: `tokscope/web/report/` or `tokscope/web/dashboard/` markup, CSS, or page script. `CLAUDE.md` makes it apply in and outside `/factory`.

1. Use a throwaway data home, not the owner's. Make an empty folder in the scratchpad and pass it as `TOKSCOPE_HOME`, with `--privacy redacted` as the README screenshots do. `tokscope serve` has no flag for another transcripts folder: it reads `~/.claude/projects` (read only) into the throwaway database. Never touch the owner's real data home or the running dashboard for a screenshot, and never run ingest against it.
2. Start the app twice, each with its own `TOKSCOPE_HOME` and `bin/tokscope serve --no-open --port N`. Run main from a `git worktree`, and the PR branch from a checkout of that branch.
3. Take screenshots of both at 1440 and 375 px wide with the Playwright or Chrome DevTools MCP tools: the changed screen at rest, and each new state, such as an open menu, the screen after the action, or an empty state. Look at every image before posting it.
4. Judge them against the Done-when list: one row per criterion, pass or fail, with what you measured or saw.
5. Publish the PNGs under `pr-<N>/` on `pr-assets`, an orphan branch that is never merged. Work from its own worktree: run `git worktree add --detach`, then `git switch pr-assets`. The first time, use `git switch --orphan pr-assets`.
6. Add a **Screenshots** section to the PR description: a Before and After table with `main` as Before, the state shots with one line each, and the verdict table. Image URL: `https://github.com/<owner>/<repo>/blob/pr-assets/pr-<N>/<file>.png?raw=true`, with `<owner>/<repo>` from `gh repo view --json nameWithOwner -q .nameWithOwner`. This URL works in a private repo for anyone with access. `gh pr edit` fails on this repo with a classic Projects GraphQL error. Write the body with `gh api -X PATCH 'repos/{owner}/{repo}/pulls/<N>' -F body=@<file>`. `gh` fills in `{owner}` and `{repo}` from the current repo.
7. A problem found here, in or outside `/factory`. Check the cases in this order. The first match wins:
   - **It fails a Done-when criterion of this PR's issue**, also on a screen this PR did not change yet. Fix it. In `/factory`, fix it as in factory `SKILL.md` Phase 6, steps 3-5. Take the after screenshots again. Mark the row "Fixed" in the verdict table. Do not ask.
   - **This PR caused it.** The before screenshot on `main` does not show it, and no Done-when criterion names it. Fix it the same way. Add a row "Fixed: caused by this PR". Do not ask.
   - **It is out of scope.** It is also on `main`, and the issue does not name it. Do not fix it. Send the screenshot to the owner. Ask whether to fix it here or in a new issue.
