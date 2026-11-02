# Research: from logs to an enhancement plan

The idea (owner, 2026-11-02): give the logs to an LLM, set a target, compare by session and by prompt, suggest a plan;
when the owner approves, analyze and generate the plan. Example: prompts that repeat become a suggestion for a skill.

The owner's goals (2026-11-02): fewer tokens, a better workflow, more useful features. Quota limits are not the goal.

**Verdict: build a small version.** One free CLI command finds patterns, and one skill gives them to a normal Claude Code
session, which writes the plan. There is no dashboard page, job runner or target for now. The model default, which the owner
already changed, was the largest lever, and it needed no build. Auto compact is a trial that needs no build either.

An independent review changed this note from a first draft with five slices. That draft said a prompt's cost mostly
measures its session position, and that skills save little. Both claims failed; see below.

## What the data says

Source: read-only queries on the local database, 2026-09-21 to 2026-11-02, about $6.8K API-eq. There is one user and no
quality measure in tokscope, and task groups come from hand-written rules. Read the numbers as sizes. They cannot prove that a change
saves tokens without a loss in quality.

1. **The history has two periods, so measure only the recent one.** The owner changed the default model to Sonnet.

   | | 09-21 to 10-18 | 10-26 to 11-02 |
   | --- | --- | --- |
   | Spend | $5,598 | $308 |
   | $ per prompt | $2.28 | $0.44 |
   | Sonnet share of spend | 4% | 84% |

   Prompts per day stayed about the same. The task mix also changed, and the recent window is small (66 sessions).
2. **Cost follows the work in a prompt, not its place in the session.** The number of steps explains log prompt cost far
   better than the context at the start (R² 0.63 against 0.17; partly mechanical). In dollars, 28.5% of spend is reads of
   context inherited at the start of a prompt, 31.8% is subagents and 39.7% is made inside the prompt. "97% of tokens are
   cache reads" is true for tokens only; in dollars cache reads are 44%. One "ok, commit + push code" prompt cost $40.63 and
   another with the same text $0.23: the first ran 114 main steps, 185 subagent requests and 3 skills.
3. **Workflow runs were half of spend and are a quarter now.** Over the whole history, about half of spend is in prompts that
   load a skill, and prompts under 25 characters that load a skill hold 22%. From 10-26 to 11-02 these shares are 26% and 10%.
   These are workflow runs, not repeated typed tasks.
4. **The data cannot say if skills save tokens.** For the same task, runs with a skill cost 3.9x and take 2.4x the steps
   (n=311, 31 with a skill). They probably do more work, and no outcome is measured. Skills clearly change the steps after a
   prompt, so a skill can raise or lower cost.
5. **Repeated typed tasks are a small share.** 4.5% to 8% of spend, by method. Exact repetition mostly finds "ok" and
   "approve". The prompts have a median of 29 characters, so a skill saves almost no typing there.
6. **Long sessions are a real but smaller lever.** Replaying the logs with a reset at 300K context saves 17-19% of spend, as
   an upper limit that assumes no re-reading. After 35 compactions, context 30 requests later was close to that of a fresh
   session (133K against 137K). 79% of main-thread spend above 300K is in prompts that started above 300K, so the owner had
   a moment to decide. Cheap prompts that started above 300K are only 4.7% of spend. From 10-26 to 11-02, requests at 300K
   or more are 43% of main-thread spend, in 6 of 70 sessions, so the lever is still there but sits in a few sessions.
7. **Reports go unused.** The `changes` table has 0 rows, no `budgets.json` exists, and Optimize, bench and replay all ran on
   one or two days only. A new report page has a poor chance. Advice must arrive in the session, at the moment of a choice.
8. **Exact repeated tool calls are not a lever:** 787 of about 89K calls, 0.3% of result size.

## Plan

### Trial runs (2026-11-02)

- **`/insights` (Claude Code 2.1.316): keep it, and build what it does not cover.** A headless run cost $2.10 and analyzed 50
  of 77 sessions from the last two weeks. It is strong on workflow: goals, repeated friction and setup gaps. The report does not
  have the word "token", so cost per pattern is the gap that tokscope fills.
- **`/insights` keeps a quality signal.** `~/.claude/usage-data/facets/` has one JSON file per analyzed session with `session_id`,
  `outcome`, `user_satisfaction_counts` and `friction_counts`. tokscope can join these to cost, to ask if a costly run went
  better. The sample is small and an LLM wrote the values, so treat them as a hint.
- **`autoCompactWindow` works from 100000.** Five throwaway files on Haiku with `claude -p`:

  | Config | Result |
  | --- | --- |
  | Default | No compaction; context reached 158K |
  | Setting 80000 | No compaction; context reached 158K; reason unknown |
  | Setting 100000 | Compacted at 80K, down to 20K |
  | `CLAUDE_CODE_AUTO_COMPACT_WINDOW=100000` | Compacted at 78K, down to 28K |

  Not tested: 300K, an interactive session, and quality after compaction. The `/config` screen strongly recommends the automatic
  window. So keep the default globally, and if it is tried, set 300000 in one project and compare before and after.
- **The subagent model lever is small now.** From 10-26 to 11-02, subagents on Opus cost $6.4 of $314, against $85.5 on Sonnet.
  Opus on the main thread cost $47, so that is the larger model lever, and it is a choice per session.

### Slices

Each slice is one issue. Nothing here runs a paid job by itself. Slice 2 runs in a session that the owner starts.

| # | Slice | Serves | Done when |
| --- | --- | --- | --- |
| 1 | `features/patterns.py`, `tokscope patterns [--since DATE] [--format table\|json] [--privacy LEVEL]` | Tokens, workflow | The grouping rules below hold, each with a test. Without `--since` it reads the last 14 days. When a facets file exists for a session, its outcome is shown next to the cost, and the command works without those files. An example is at most 80 characters with token-like strings masked, and `redacted` and `numbers` output has no prompt text. |
| 2 | A skill in `mod/skills/` that reads the JSON and writes a plan in a normal session. **Held:** no issue until the owner has seen slice 1 on real data | Workflow | The skill text requires a route and a way to measure it for each group it keeps, and forbids a dollar saving. |
| 3 | Automatic `changes` row: `optimize.apply` calls `add_change` with the skill, after the job state is written | Useful features | An applied Optimize change has one `changes` row with no manual step, so it gets its card under Config changes. A failed apply adds no row. |
| 4 | Context nudge: a `context` field in the CLI's session view, the same field in the mod's `SessionView`, one line in the pane, and one toast per session | Tokens, workflow | With a fixture whose last main-thread request has 300K or more of context, the view has the field, the pane shows the line and the toast fires once. It is on when the mod is installed, and `/tokscope nudge off` stops it. With the pane closed, the mod still reads the view after each main-thread turn. |

Slice 1 is the test of the skill. If its groups are not useful on real data, slice 2 stops there. Autopilot ships every open
ticket in a milestone to one PR, so a ticket for slice 2 would skip this check, and it has none until the owner decides. Slices 3 and 4 do not use
`patterns`, so they go ahead. Slice 1 goes in `features/`, not `core/`, because it uses `BENCH_PROJECT` and `core` must not
import `features`.

Slice 1 grouping rules (the first scripts were not kept, so these are the definition):

- **Left out of all groups:** sessions that match `BENCH_PROJECT`, requests with no `prompt_idx`, prompts whose text starts with
  `<` (machine prompts), and prompts under 25 characters that load no skill (follow-ups).
- **Workflow group:** a prompt that loads a skill, of any length, keyed by its first skill.
- **Task group:** other prompts, keyed by their first five words in lower case with digits and paths removed. A task group
  needs 3 or more prompts in 2 or more sessions.
- **In-prompt cost:** the prompt's cost with subagents, minus inherited reads. For each main-thread request, inherited reads are
  the smaller of its `cache_read` and the `cache_read` of the prompt's first main-thread request, at that model's cache-read rate.
- **Each group shows:** prompts, sessions, in-prompt cost, its lowest, median and highest cost per prompt, median steps, subagent
  requests, skills, median start context, facets outcomes and one example.
- **At `redacted` and `numbers`:** the command reads `privacy.redacted_copy`, which has no prompt text, so only workflow groups appear.
  Facets files are read too, by session id, and only a fixed list of outcome values is shown.
- **Facets:** read only, from `usage-data/facets/` under `$CLAUDE_CONFIG_DIR`, else `~/.claude`.

| Pattern | Route |
| --- | --- |
| Workflow run with a wide cost range | Optimize the skill or its subagent models |
| Repeated task, no skill loaded, similar steps | Draft a new skill |
| Same request in many sessions ("translate to Vietnamese") | A line in `CLAUDE.md` |
| Same long template in many sessions | Shorten the template at its source |
| Long session with work still to do | Compact or a new session; show this as the nudge |

### Not now

| Part | Why | Build it when |
| --- | --- | --- |
| Patterns dashboard page | Slice 2 gives the same content where the owner works | The skill is used and a list is needed |
| Paid job runner, first Approve click | A digest costs cents, and a normal session already has a plan review and edit permissions | A run must work without a session |
| `targets` | tokscope has no quota source (`statusline_snapshots` stores prompt cache state only), and API-eq is a poor proxy for limits. A session p90 falls when a session is split, with the same total | Quota is stored (issue #52). A target should use weekly usage |
| Project-level `changes` row | `changes` has only agent and skill columns, and each before/after counts skill loads or subagent runs. A `CLAUDE.md` line needs a schema migration and a new unit, and its edit happens in a session, so no code can record it by itself | The first plan needs it. Then record it by hand with `tokscope change` |

The owner's "click approve" becomes the plan review in the session. Only the approval before a change is applied stays.

## Risks

| Risk | Control |
| --- | --- |
| A plan claims savings it cannot prove | The plan has no saving field; the result comes from the before/after measurement |
| Fewer tokens with worse results | Tokens alone do not prove a gain. Use bench with a grader where a task allows it; replay is read-only |
| Facets belong to Claude Code and can change | Read them as optional input; a missing file or field shows nothing |
| Prompts hold secrets or pasted instructions | Slice 1: output has trimmed examples only, with token-like strings masked. Slice 2: the skill treats them as data, and the normal permission prompts stay on |
| A skill writes to `CLAUDE.md` or a skill file | The new command and skill add no writer to tokscope; a change is a normal edit that the owner approves in the session. `optimize.apply` stays the existing writer behind its own approval, and slice 3 adds only a `changes` row |
| A new skill has no "before" | Its first runs are the baseline, so compare the task group, not the skill |
| Old data gives false progress | `patterns` defaults to the last 14 days, and each before/after starts at its change |
| A nudge becomes noise | One toast per session, a fixed 300K threshold and `/tokscope nudge off` |

## Decisions

| Decision | Why | Rejected |
| --- | --- | --- |
| A CLI command and a skill, not a page and a job runner | The tools that exist are barely used, and a session already gives the LLM, the review and the permissions | The five-slice build with `targets` and a job runner |
| Rank by in-prompt cost | It leaves out context inherited at the start, and steps explain cost better than position | Total prompt cost; fresh tokens, which miss the reads made inside a prompt |
| "Logs" means the transcript tables | They have the prompt text | OTel logs (2 days of files here; `otel_requests` has no prompt text) |
| No promised saving | Finding 4: the direction of a skill's effect is unknown without a measurement | "Saves $X" estimates |
| Hold slice 2 until slice 1 has run on real data (owner, 2026-11-02) | One PR for a milestone has no stop between slices | A ticket for all four slices |
| The nudge is on, with a toast and an off switch (owner, 2026-11-02) | Finding 7: a tool that must be turned on goes unused | Off by default; a pane line only |

Source of the numbers: `prompts`, `requests`, `tool_calls`, `skill_calls` and `changes` in `data/tokscope.db`. The scripts were
not kept. A later re-run will differ a little, because new sessions are added.
