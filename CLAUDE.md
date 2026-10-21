# claude-code-tokscope

Token usage per skill, subagent and phase for Claude Code: a stdlib Python CLI, an HTML report and a local dashboard. Tasks: the GitHub issues.

## Rules

- Minimize tokens. Model and effort per role: the Models table below.
- Agent behavior rules: [.claude/rules/behavior.md](.claude/rules/behavior.md) (always loaded).
- **Screenshots on every UI PR.** A PR that changes what the owner sees (`tokscope/report.py` or `tokscope/dashboard.py` markup, CSS, page script) shows before (`main`) and after screenshots at 1440 and 375 px in its description. It also shows a pass/fail table against the issue's "Done when". Steps: [factory UAT steps](.claude/skills/factory/references/uat.md). They apply outside `/factory` too. Fix a screenshot problem without asking when it fails the issue's Done-when or when this PR caused it. Ask the owner about a problem that is also on `main` and not in the issue. This is the one exception to "fix only when the owner asks" below.
- **Review every PR.** Outside `/factory`: after you or a subagent opens a PR, the main session runs `/code-review:code-review <PR>`. Use Anthropic's plugin, not the built-in `code-review`, and give the reviewers `REVIEW.md`. Then run `git fetch -q origin` and `/security-review`. Skip review only when the owner says so. First name the change type. Run only the reviewers and the security review that the type needs. Give each one the model and effort that its check needs: [REVIEW.md "Pick the reviewers first"](REVIEW.md#pick-the-reviewers-first). Subagent prompts end at `gh pr create` and return the PR number. Subagents never review. Report the findings. Fix them only when the owner asks. During `/factory`, this rule does not apply: its Phase 6 decides when to review and what to fix. A hook (`.claude/hooks/pr-opened.sh`) adds a reminder after each `gh pr create`.

## Models (`/factory`)

The agent files' `model:` and `effort:` lines apply on their own. Review roles have no fixed model or effort: the main session picks them per review ([REVIEW.md "Model and effort"](REVIEW.md#model-and-effort)).

| Role | Model / effort | Set by |
| --- | --- | --- |
| Discover, plan, diagnose | Opus 5.5 / high | `.claude/agents/factory-planner.md` |
| Intent review (Phase 6b) | chosen per review | main session, `REVIEW.md` |
| Implement | Sonnet 5.5 / default | `.claude/agents/factory-implementer.md` |
| Tests | Haiku 5.5 / default | `.claude/agents/factory-test-runner.md` |
| `/code-review:code-review` reviewers and scorers, `/security-review` | chosen per review | main session, `REVIEW.md` |

## Run

```bash
bin/tokscope serve       # serves http://127.0.0.1:8765; --port N for another port, no install needed
```

## Test

```bash
python3 -m unittest discover -s tests -q
```

## More

- [README.md](README.md): what tokscope does, where data lives, running.
- [DECISIONS.md](DECISIONS.md): what was chosen and why.
- [REVIEW.md](REVIEW.md): what reviewers check, risk by path, what not to report.
- [docs/design-prompt.md](docs/design-prompt.md): the prompt for designing a screen in the ink style.
- [.claude/skills/factory/SKILL.md](.claude/skills/factory/SKILL.md): the `/factory` agent workflow.

## Project status tracking (Claude Bot Local)

Before giving your final response in every session, update `STATUS.md` in the project root:

1. Set `updated` to today's date and `updated_by: claude` in the frontmatter.
2. Adjust `state` (`active` | `paused` | `blocked` | `done`) and `progress` (0-100: percent of the current milestone's issues closed) if they changed.
3. Rewrite **Summary** in 1-2 sentences reflecting the current state.
4. Rewrite **Next step** as the single most useful action for the next session.
5. Update **Blockers** — keep `- (none)` when there are none.
6. Add a line to **Recent**, even if nothing else changed: `- YYYY-MM-DD: <what this session did>`. If the top line has today's date, extend it in place; otherwise prepend a new line. Keep at most 10 lines; drop the oldest.

Rules:
- Keep STATUS.md under 40 lines; never remove or rename the frontmatter keys (the scanner parses them).
- If STATUS.md does not exist, create it with the frontmatter keys above and the four sections (there is no template in this repo).
- Set `updated_by: manual` only when a person edited the file by hand.
- When you commit, include STATUS.md in the same commit or PR as the session's work.
- Do this even for small sessions — a one-line Recent entry is enough.
