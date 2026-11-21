# claude-code-tokscope

Token usage per skill, subagent and phase for Claude Code: a stdlib Python CLI, an HTML report, a local dashboard and
an Electron desktop app. Features: [PRODUCT.md](PRODUCT.md). Install and run: [README.md](README.md). Tasks: GitHub issues.

```bash
bin/tokscope serve                          # http://127.0.0.1:8765 (--port N), no install needed
```

## Run and test

- Test (all): `python3 -m unittest discover -s tests -q`
- Targeted test: `python3 -m unittest tests.test_budgets -q`
- Lint: `pipx run ruff check .`
- Full suite (CI, `.github/workflows/ci.yml`): unittest `-v`, `ruff check .`, `python -m build --wheel`

## Code layout

`tokscope/`: `cli.py` (entry), `paths.py`, `assets/`, `core/` (transcripts to SQLite), `features/`, `integrations/` (ant,
MCP Registry), `experiments/` (paid `claude -p` runs), `web/` (`dashboard/`: `pages/` one module per page, `scripts`, `shell`,
`server`; `report/`: `sections/`, `styles`, `scripts`, `widgets`, `writer`) and `web/theme/`. `core` never imports the others and
only `cli` and `web` import `web` (`tests/test_layout.py`). Why: [docs/research-package-layout.md](docs/research-package-layout.md).

## Workflow (pd-bot plugin)

Skills, agents and hooks come from the `pd-bot` plugin (`claude plugin install pd-bot@pd-bot`, then `/pd-bot:pd-setup`),
not from this repo. Skills run as `/pd-bot:<name>` (`pd-intake`, `pd-writing-plans`, `pd-implement`, `pd-review`, `pd-uat`,
`pd-autopilot`, ...). Its hooks load the behavior rules at session start, guard merges into `main`, and scan for secrets.
`.claude/settings.json` holds only the `permissions.deny` rules that `pd-setup` adds; `specs/` stays tracked here.

## Rules

- Minimize tokens. Behavior rules: the pd-bot plugin's `rules/behavior.md` (loaded by its SessionStart hook).
- **UI PRs show screenshots.** A PR that changes what the owner sees (markup, CSS or page script in `tokscope/web/report/`
  or `tokscope/web/dashboard/`) shows before (`main`) and after at 1440 and 375 px, and a pass/fail table against the
  issue's "Done when". Check the running app with `/pd-bot:pd-uat`. Fix a screenshot problem without
  asking when this PR caused it or it fails Done-when; ask about one that is also on `main`.
- **Review every PR** (unless the owner says skip): run `/code-review:code-review <PR>` (Anthropic's
  plugin) with `REVIEW.md`. First name the change type, then pick reviewers, model and effort per
  [REVIEW.md](REVIEW.md#pick-the-reviewers-first). When the type needs a security review, give an agent `gh pr diff <PR>`:
  `/security-review` needs `origin/HEAD`, and the remote here is `github`. Subagents stop at `gh pr create`, return the PR
  number and never review. Report findings; fix them only when the owner asks (the screenshot rule above is the one exception).
- Models: the `model:` and `effort:` lines in the pd-bot agents apply; review roles are chosen per review.
- More: [DECISIONS.md](DECISIONS.md) (why), [REVIEW.md](REVIEW.md) (what reviewers check),
  [docs/design-prompt.md](docs/design-prompt.md) (Indigo style).

## STATUS.md (Claude Bot Local)

Before the final response of every session, update `STATUS.md`, and commit it with the session's work:

1. Frontmatter: `updated` = today, `updated_by: claude` (`manual` only for a hand edit); adjust `state`
   (`active` | `paused` | `blocked` | `done`) and `progress` (0-100, share of the milestone's issues closed).
2. **Summary**: 1-2 sentences on the current state. **Next step**: the single most useful next action.
   **Blockers**: or `- (none)`.
3. **Recent**: `- YYYY-MM-DD: <what this session did>`; extend today's top line, else prepend. At most 10 lines.

Keep it under 40 lines and never rename or remove the frontmatter keys (a scanner parses them). If it is missing,
create it with those keys and the four sections.
