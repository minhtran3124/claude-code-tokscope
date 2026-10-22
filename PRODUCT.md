# tokscope: features

tokscope measures the tokens that Claude Code uses, per session, skill, subagent and phase. It reads the transcripts
in `~/.claude/projects`, keeps the numbers in a local SQLite database, and shows them in the terminal, in an HTML
report, in a live local dashboard and in a Claude Code pane. Use it to measure a skill or agent change before and after
you make it.

To install and run it, see [README.md](README.md).

## Parts

| Part | What it is |
| --- | --- |
| CLI `tokscope` | Stdlib Python. Ingests transcripts, prints tables, writes the report, serves the dashboard, runs benchmarks. |
| HTML report | One file with the summary, totals, sessions, breakdowns, skill versions and benchmarks. |
| Dashboard | A local web server on `127.0.0.1` with seven pages (below). |
| Claude Code mod (`mod/`) | The `/tokscope` command, a live pane, and marks for each Skill and Agent call. |
| Desktop app (`desktop/`) | An Electron window around the dashboard, with a systemd user service. Linux only. |
| OTel receiver (optional) | `collector/otlp_receiver.py`: OTLP/HTTP JSON on `127.0.0.1:4318`, one JSONL file per day in `data/otel/` (`TOKSCOPE_DATA_DIR` changes the folder). Not part of the package. |

## Dashboard pages

A filter bar sets the range (7, 30 or 90 days, or all time; default 30), project, model and skill for every number on
the page; the URL keeps the filters. Overview updates by itself; the other pages show a "New data · reload" button.
The dashboard answers only on `127.0.0.1` and refuses requests from other hosts or other sites.

- **Overview**: today's totals, a typical day, and what changed against the range before, for skills and subagent types.
- **Sessions**: each session with its tokens, split between the main thread and subagents. Open a row to see each
  prompt; tick 2 to 4 rows to compare them.
- **Projects** (full level only): each project with its sessions, tokens and API-equivalent cost. Worktrees, eval
  copies and subfolders count under their repository. Open a project to see and manage its MCP servers (below).
- **Library** (file contents at full level only): the skills that you wrote, with their files, the STE check and
  Optimize (below).
- **Benchmarks**: benchmark runs and answers.
- **Breakdowns**: tokens by MCP server, tool, skill, owner, phase and subagent type, each with its finding.
- **Managed** (full level only): your Claude Managed Agents, read through the `ant` CLI (below).

### Projects: MCP servers

For each server of a project, the page shows its source (`local`, `project`, `user`, a plugin or a claude.ai
connector), how it runs, the names (never the values) of its environment variables and headers, its calls and
approximate result tokens, and a **never used here** label when unused. A server hidden by one of higher precedence
is **shadowed**.

- **Check health** runs `claude mcp list` in the project folder.
- **Add a server** runs `claude mcp add-json`; **Remove** runs `claude mcp remove`. tokscope never writes
  `~/.claude.json` or `.mcp.json` itself. In `project` scope, write a secret as a reference such as `${API_KEY}`; the
  page asks before it saves a plain value.
- **Find in the MCP Registry** searches `registry.modelcontextprotocol.io` (only the search words are sent) and fills
  in the form. Nothing is installed until you click **Add server**.
- Each change is logged, without values, in `data/mcp-changes.jsonl`.

To hide a folder that is not a project, write `projects.json` in the data home: `{"ignore": ["brichan-s55-*", "~/scratch/*"]}`.

### Library: skills

The Library lists skills from `~/.claude/skills` and from each project's `.claude/skills`. It hides plugin skills and
skills that an installer added (a link into `~/.agents/skills`, an entry in a skills lock file, or an `*install.json`
file); **Show installed** shows them too. To fix a grouping, write `library.json` in the data home:
`{"mine": ["boxd-cli"], "installed": ["impeccable"]}`.

- **STE check** lists STE100 findings per Markdown file (line, rule, text). It runs `scripts/ste-lint.py` from the
  `asd-ste100` skill; `TOKSCOPE_STE_LINT` points to another linter.
- **Optimize** runs `claude -p` on a copy of the skill with one or more guide skills (`optimize-skill`, `asd-ste100`,
  `unslop`), a model and a maximum cost. The run page shows each step and the changed files; when it ends, compare
  each file (side by side, diff, before, after), optionally benchmark the draft, then **Approve and apply** or
  **Reject**. The run writes only in `bench/optimize/<job>/`; the skill changes only when you apply, and not if the
  skill changed after the run started. Only your own skills can be optimized.

### Managed: Claude Managed Agents

Managed lists the deployments, the latest 100 sessions and the agents of your Claude Developer Platform workspace,
with tokens and cost. It reads them with the `ant` CLI (`ant auth login` first) and keeps the result 60 s; **Refresh**
reads again.

- **Pause / Unpause**: an active deployment has Pause, a paused one Unpause. The page asks first. Pause stops future
  scheduled runs; a running session continues. Unpause resumes at the next scheduled time; missed runs do not run.
- **Agent configuration**: click an agent's name to see its model and effort, version, description, system prompt,
  toolsets with their permission policies, MCP servers, skills and multiagent. Read only.

## Claude Code mod

| Command | What it does |
| --- | --- |
| `/tokscope` | Shows the current session |
| `/tokscope session <id>` | Shows another session |
| `/tokscope open` | Opens the report (`/tokscope report` does the same) |
| `/tokscope skills [name]` | Lists skill versions |
| `/tokscope pane on\|off` | Shows or closes the live pane |

The **live pane** shows the session tokens (main thread and subagents), the last 8 turns with tokens, list price,
subagents, MCP servers and tools, and the tokens by owner and by skill. It updates after each turn; press `r` to
refresh and `o` to open the report. It is off by default and remembers your last choice.

The mod finds the CLI in `TOKSCOPE_CLI`, then on `PATH`, then in `~/.local/bin/tokscope`. It writes a mark for each
Skill and Agent call to `data/marks/` and ingests the session when it ends.

## Skill versions

A skill version is a hash of the skill folder (`SKILL.md` and the files next to it; not hidden files, caches, eval and
test folders, or files over 1 MB). tokscope keeps the files of each version in `data/skills/<skill>/<version>/`, so
you can diff two versions. A `version:` line in the frontmatter shows as a label.

- `tokscope skills [SKILL]` lists versions with first-seen dates, loads and median tokens per load.
- `tokscope skills import [SKILL]` recovers older versions from the SKILL.md text in old transcripts.
- The report and the Library show a card per changed skill. A version with fewer than 5 loads is marked "few". These
  medians come from different work; for a fair comparison, run a benchmark or a replay.

## Benchmarks and replays

CAUTION: `bench run` and `replay run` start new `claude -p` sessions, which cost money or plan usage. Set `--runs`
first; for a replay also `--budget`. A benchmark task sets `max_budget_usd` per run.

A **benchmark** runs a fixed task: a JSON file in `bench/tasks/` with a prompt, variants and a regex grader.
`{version}` and `{skill}` in the prompt are replaced. Variants alternate order each round (a, b, b, a) because the
first run fills the prompt cache.

```sh
tokscope bench prepare <task>
tokscope bench run <task> --skill xia2 --skill-versions 25e2fd,9ee5a7 --runs 3
tokscope bench diff <task>        # compare again later
tokscope bench regrade <task>     # after you edit the grader
```

A **replay** sends the prompts of a real session again, in a new git worktree at the commit where the session
started, with read-only tools only:

```sh
tokscope replay plan <session-id>
tokscope replay run <session-id> --skill xia2 --skill-versions 25e2fd,9ee5a7 --runs 4 --budget 6
tokscope replay diff <session-id>
```

After each run, a skill check compares the SKILL.md text in the transcript with the pinned version: `ok`,
`other text`, `not loaded` or `unconfirmed`. Compare variants only on `ok` runs. A plugin skill, or a skill with a copy
in `~/.claude/skills`, cannot be pinned.

## Config changes

Record a change to a subagent or skill; the report compares the sessions before and after it, as a marker on the
daily chart and a before/after card.

```sh
tokscope change "reviewer: fable -> opus" --agent reviewer
tokscope change "trim xia2 rules" --skill xia2 --at 2026-10-15T09:00 --days 14
tokscope change                   # list changes with their impact
```

## Privacy levels

The default report and the `full` dashboard contain your prompts, titles, descriptions, answers and paths. Make a
redacted report before you share one:

| Level | Contents |
| --- | --- |
| `full` | All data (default) |
| `redacted` | Numbers and names. No prompts, titles, descriptions, answers or paths. |
| `numbers` | Numbers only. Each name becomes an alias, for example `skill-3fa9c1`. |

```sh
tokscope report --privacy redacted   # reports/report-redacted.html
tokscope serve --privacy redacted
```

Aliases come from `privacy.key` (mode 600), so one skill gets the same alias in each report from one machine.
Built-in tool and agent names and phase names do not change.

## Command reference

| Command | What it does |
| --- | --- |
| `tokscope ingest [--project TEXT] [--session ID]` | Reads new transcripts into the database (incremental) |
| `tokscope session ID [--json]` | Ingests one session and shows its tokens |
| `tokscope summary [--by phase\|skill\|agent\|model] [--since DATE] [--project TEXT] [--limit N]` | Shows a table in the terminal |
| `tokscope report [--out FILE] [--privacy LEVEL] [--since DATE] [--project TEXT]` | Writes the HTML report |
| `tokscope open [same options as report]` | Ingests, writes the report and opens it |
| `tokscope serve [--port N] [--interval S] [--no-open] [--privacy LEVEL]` | Starts the live dashboard |
| `tokscope skills [SKILL]` | Lists skill versions |
| `tokscope skills import [SKILL]` | Recovers older skill versions from transcripts |
| `tokscope change [NOTE] [--agent A] [--skill S] [--at TIME] [--days N]` | Records or lists config changes |
| `tokscope bench prepare\|run\|diff\|regrade TASK [--runs N] [--variants A,B] [--skill S --skill-versions A,B]` | Runs a benchmark |
| `tokscope replay plan\|run\|diff ID [--runs N] [--budget USD] [--model M] [--skill S --skill-versions A,B]` | Replays a session |
| `tokscope mark` | Reads marks from stdin (the mod uses it) |

## How to read the numbers

- **Dollars are estimates ("API-eq")**: tokens at API list prices. On a Pro, Max, Team or Enterprise plan you do not
  pay per token; the real limits are the 5-hour and weekly limits.
- **Phases are direct or carried.** Direct: its skill ran in that prompt. Carried: a later prompt loaded no skill and
  kept the last phase. Copy `tokscope/assets/phases.json` to the data home to change the phase map.
- **By skill overlaps By owner.** Do not sum the two tables.
- **Tool tokens are estimates** (`~`): the API reports usage per request, so MCP and tool tokens come from result size
  (4 characters per token).
- **Transcripts expire** after Claude Code's `cleanupPeriodDays`; set it high (for example 365) to keep history.
  `tokscope ingest` can rebuild the database from transcripts, but not the OTel logs or the marks.
