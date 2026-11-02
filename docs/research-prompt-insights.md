# Research: from logs to an enhancement plan

The idea (owner, 2026-11-02): give the logs to an LLM, set a target, compare by session and by prompt, suggest a plan;
when the owner approves, analyze and generate the plan. Example: prompts that repeat become a suggestion for a skill.

The owner's goals (2026-11-02): fewer tokens, a better workflow, more useful features. Quota limits are not the goal.

**Verdict: build a small version.** One free CLI command finds patterns, and one skill gives them to a normal Claude Code
session, which writes the plan. There is no dashboard page, job runner or target for now. Two levers need no build: the
model default, which the owner already changed, and auto compact.

An independent review changed this note from a first draft with five slices. That draft said a prompt's cost mostly
measures its session position, and that skills save little. Both claims failed; see below.

## What the data says

Source: read-only queries on the local database, 2026-09-21 to 2026-11-02, about $6.8K API-eq. There is one user and no
quality measure, and task groups come from hand-written rules. Read the numbers as sizes. They cannot prove that a change
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
   cache reads" is true for tokens only; in dollars cache reads are 44%. One "open PR" prompt cost $40.63 and another with
   the same text $0.23: the first ran 114 main steps, 185 subagent requests and 3 skills.
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

### Try first, no build

- Run `/insights`, built into Claude Code 2.1.316 ("Generate a report analyzing your Claude Code sessions"). Build only what
  it does not cover. The likely gap is token cost per group. It has not been run yet.
- Try `autoCompactWindow`. The name is in the 2.1.316 binary and not in the owner's user settings; the behavior is not tested.
- Check the model set per subagent. Moving Opus and Fable subagents to Sonnet is the next model lever. The size is unknown,
  because the default change already did part of this.

### Slices

Each slice is one issue and one PR. Nothing here runs a paid job by itself.

| # | Slice | Serves | Done when |
| --- | --- | --- | --- |
| 1 | `features/patterns.py`, `tokscope patterns [--since DATE] [--format json]` | Tokens, workflow | Follow-ups, machine prompts and bench sessions form no task group. A short prompt that loads a skill is a workflow run. Groups rank by in-prompt cost (cost minus reads of inherited context) and show steps, subagents, skills and start context. No prompt text at `redacted`. |
| 2 | A skill in `mod/` that reads the JSON and writes a plan in a normal session | Workflow | A plan names a route and a way to measure it, for each group it keeps, with no dollar saving. |
| 3 | Automatic `changes` row: in `optimize.apply`, and `add_change` accepts a project scope | Useful features | An applied skill change gets its before/after card with no manual step. A `CLAUDE.md` or setting change has a project-level row. |
| 4 | Context nudge in the mod pane or a hook | Tokens, workflow | When a main thread passes a set context size, the owner sees one line before the next prompt. It is off by default. |

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
| `targets` | No quota data (`statusline_snapshots` has 0 rows) and API-eq is a poor proxy for limits. A session p90 falls when a session is split, with the same total | Quota data is stored. A target should use weekly usage |

The owner's "click approve" becomes the plan review in the session. Only the approval before a change is applied stays.

## Risks

| Risk | Control |
| --- | --- |
| A plan claims savings it cannot prove | The plan has no saving field; the result comes from the before/after measurement |
| Fewer tokens with worse results | Tokens alone do not prove a gain. Use bench with a grader where a task allows it; replay is read-only |
| Prompts hold secrets or pasted instructions | Output has trimmed examples only, with token-like strings masked. The skill treats them as data, and the normal permission prompts stay on |
| A skill writes to `CLAUDE.md` or a skill file | The change goes through the normal edit approval in the session. tokscope itself writes nothing outside its data home (`REVIEW.md`) |
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
