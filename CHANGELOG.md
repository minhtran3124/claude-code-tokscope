# Changelog

Versions follow [semver](https://semver.org). Before 1.0 a minor bump may break things; each break is listed.
The version lives in `tokscope/__init__.py`; `mod/.claude-plugin/plugin.json` must carry the same number.

## 0.1.0 - 2026-10-21

First public release.

Install:
- The package is `claude-code-tokscope`; the command and the module are `tokscope`. Install with `pipx install`,
  `uv tool install` or `uvx --from`. An installed CLI keeps its data in `$TOKSCOPE_HOME` or `~/.local/share/tokscope`;
  a clone uses its own `data/`.
- `tokscope --version`.

Token accounting:
- Tokens per skill, subagent and phase from Claude Code transcripts. By skill shows main-thread and subagent tokens
  apart; By owner shows the subagent part.
- By phase splits each phase into direct (its skill ran in that prompt) and carried (a later prompt with no skill kept
  the last phase). `summary --by phase` has a carried column.
- Every dollar figure is labelled API-eq: an estimate at API list prices, not a bill on a Pro, Max, Team or Enterprise
  plan, where the limits are the 5-hour session limit and the weekly limit.
- `phases.json` ships in the package; a `phases.json` in the data folder overrides it.

Skill versions:
- A content hash per skill folder, recorded at each Skill call and typed /command and at ingest. Each version's files
  are kept for a diff, and versions are dated by the kept SKILL.md text or the git history.
- `tokscope skills` lists each skill with its versions, loads and median tokens per load. `tokscope skills import`
  rebuilds older versions from the SKILL.md text kept in transcripts.
- The skill version shows in report turn rows, `tokscope session` and the pane's By skill list.

Report:
- `tokscope report`: a single HTML file with sessions, breakdowns and a chart for each, "Week over week" (skills by the
  last 7 days against the 7 before) and "Skill versions" (a card and diff per changed skill).
- `--privacy redacted|numbers` builds a report safe to share from a redacted copy of the database.

Dashboard (`tokscope serve`):
- A live dashboard on 127.0.0.1: Overview, Sessions, Skills, Projects, Library, Benchmarks and Breakdowns, with one
  filter bar (range, project, model, skill) kept in the URL. New transcripts are ingested in the background.
  /api/summary, /api/sessions, /api/projects, /api/library and /api/version return JSON. Requests with another Host
  name are refused; writes need the dashboard's origin, a page token and a JSON body.
- Projects: each project from your sessions (worktrees and subfolders folded into their repository) with sessions,
  tokens, cost and its MCP servers: source, transport, shadowing, calls, result tokens and a "never used here" flag.
  Check health runs `claude mcp list`. Env and header values are never read out.
- Add and remove MCP servers from a project page through `claude mcp add-json` and `claude mcp remove`, so Claude Code
  writes its own files. Literal values in project scope ask first; no value is shown again or logged.
- Find a server in the official MCP Registry (npm, PyPI, OCI or a remote URL) and fill the add-server form from it.
  Only the search words leave the machine.
- Library: the skills you wrote (personal and per project), each file rendered or as source, with the version, loads
  and a token estimate. Installed skills are hidden by default; `library.json` corrects a wrong guess.
- STE check: STE100 findings per Markdown file by line, from the installed asd-ste100 skill's `ste-lint.py` (or
  `$TOKSCOPE_STE_LINT`).
- Optimize a skill: `claude -p` rewrites a copy with the guide skills you pick, within a spending cap and with writes
  limited to the job folder. The run shows its steps live and can be cancelled. The result compares each file side by
  side, as a diff and rendered, with words, tokens and STE findings before and after. Approve and apply, Reject, or
  Benchmark first; Apply is refused if the skill changed meanwhile.
- Benchmark a draft against the current skill: pass rate, median cost, tokens and time. A skill with no task gets a
  form to make one. Personal skills cannot be benchmarked; the page says why.

Benchmarks and replay:
- `tokscope bench` and `tokscope replay` run a task or a real session per variant and compare cost and tokens. Variants
  flip order each round. `--skill <name> --skill-versions a,b` runs one variant per pinned skill version.
- Config changes are recorded with their before/after impact.

Claude Code mod:
- `/tokscope` with the same words as the CLI: `/tokscope open`, `/tokscope session <id>`, `/tokscope skills [name]`,
  `/tokscope pane on|off`.
- A live pane with count-up totals, a NEW badge with the delta, a trend sparkline, and `r` refresh and `o` open report
  keys.
- Marks for Skill and Agent calls, and ingest when a session ends.
- The mod finds the CLI on `PATH` or in `~/.local/bin`, and says how to install it when there is none.

Project:
- Apache-2.0 license. CI runs the Python tests, the mod tests and the package build.
