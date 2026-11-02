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
3. **Most spend starts from short prompts that load a skill.** About half of spend is in prompts that load a skill. Prompts
   under 25 characters that load a skill hold 22%. These are workflow runs, not repeated typed tasks.
4. **The data cannot say if skills save tokens.** For the same task, runs with a skill cost 3.9x and take 2.4x the steps
   (n=311, 31 with a skill). They probably do more work, and no outcome is measured. Skills clearly change the steps after a
   prompt, so a skill can raise or lower cost.
5. **Repeated typed tasks are a small share.** 4.5% to 8% of spend, by method. Exact repetition mostly finds "ok" and
   "approve". The prompts have a median of 29 characters, so a skill saves almost no typing there.
6. **Long sessions are a real but smaller lever.** Replaying the logs with a reset at 300K context saves 17-19% of spend, as
   an upper limit that assumes no re-reading. After 35 compactions, context 30 requests later was close to that of a fresh
   session (133K against 137K). 79% of main-thread spend above 300K is in prompts that started above 300K, so the owner had
   a moment to decide. Cheap prompts that started above 300K are only 4.7% of spend.
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
- **Still to check:** the model set per subagent. Moving Opus and Fable subagents to Sonnet is the next model lever. The size is
  unknown, because the default change already did part of this.

### Slices

Each slice is one issue and one PR. Nothing here runs a paid job by itself. Slice 2 runs in a session that the owner starts.

| # | Slice | Serves | Done when |
| --- | --- | --- | --- |
| 1 | `features/patterns.py`, `tokscope patterns [--since DATE] [--format json]` | Tokens, workflow | Follow-ups, machine prompts and bench sessions form no task group. A short prompt that loads a skill is a workflow run. Groups rank by in-prompt cost (cost minus reads of inherited context) and show steps, subagents, skills and start context. When a facets file exists for a session, its outcome is shown next to the cost, and the command works without those files. No prompt text at `redacted`. |
| 2 | A skill in `mod/` that reads the JSON and writes a plan in a normal session | Workflow | The skill text requires a route and a way to measure it for each group it keeps, and forbids a dollar saving. |
| 3 | Automatic `changes` row: `optimize.apply` calls `add_change` with the skill | Useful features | An applied Optimize change gets its before/after card with no manual step. |
| 4 | Context nudge: a context field in the CLI's session view, the same field in the mod's `SessionView`, and one line in the pane, updated after each turn | Tokens, workflow | With a fixture whose last main-thread request has 300K or more of context, the view has the field and the pane shows the line. It is off by default. |

Slice 1 is the test of the whole idea. If its groups are not useful on real data, stop there. It goes in `features/`, not
`core/`, because it uses `BENCH_PROJECT` and `core` must not import `features`.

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
| Prompts hold secrets or pasted instructions | Output has trimmed examples only, with token-like strings masked. The skill treats them as data, and the normal permission prompts stay on |
| A skill writes to `CLAUDE.md` or a skill file | The new command and skill add no writer to tokscope; a change is a normal edit that the owner approves in the session. `optimize.apply` stays the existing writer behind its own approval, and slice 3 adds only a `changes` row |
| A new skill has no "before" | Its first runs are the baseline, so compare the task group, not the skill |
| Old data gives false progress | `patterns` defaults to a recent window, and each before/after starts at its change |

## Decisions

| Decision | Why | Rejected |
| --- | --- | --- |
| A CLI command and a skill, not a page and a job runner | The tools that exist are barely used, and a session already gives the LLM, the review and the permissions | The five-slice build with `targets` and a job runner |
| Rank by in-prompt cost | It leaves out context inherited at the start, and steps explain cost better than position | Total prompt cost; fresh tokens, which miss the reads made inside a prompt |
| "Logs" means the transcript tables | They have the prompt text | OTel logs (2 days of files here; `otel_requests` has no prompt text) |
| No promised saving | Finding 4: the direction of a skill's effect is unknown without a measurement | "Saves $X" estimates |

Source of the numbers: `prompts`, `requests`, `tool_calls`, `skill_calls` and `changes` in `data/tokscope.db`. The scripts were
not kept. A later re-run will differ a little, because new sessions are added.
