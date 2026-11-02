# Research: from logs to an enhancement plan

The idea (owner, 2026-11-02): give the logs to an LLM, set a target, compare by session and by prompt, suggest a plan;
when the owner approves, analyze and generate the plan. Example: prompts that repeat become a suggestion for a skill.

**Verdict: build it, with two changes.** The free detection comes first and the LLM runs only after a click. The tool
also must not rank by the cost of a prompt, and must not promise that a skill saves tokens. The measurements below show
why. tokscope has most of the parts already; the new work is detection, a target, and the link between them.

## What the data says

A throwaway script ran on the local database (read only): 2026-09-21 to 2026-11-02, 4,342 prompts, about $6.8K API-eq.
The rules were tuned by hand on this one history, so read the numbers as sizes, not as a method.

| Prompt class | Prompts | Share of spend |
| --- | --- | --- |
| Real text | 3,230 | 72% |
| Follow-up ("ok", "yes", "approve") | 281 | 14% |
| Machine text (pasted worker templates, compaction summaries, review bots) | 435 | 11% |
| Typed `/command` | 131 | 3% |
| Headless `claude -p` | 265 | 0.5% |

1. **Plain repetition finds the wrong things.** With exact matches after normalizing, the costliest groups are "approve",
   "ok" and "yes". Their cost is the work that follows, not the prompt, so a skill cannot replace them.
2. **Repeated tasks are a small share.** Without those classes, 44 groups repeat in 3 or more sessions: 458 prompts, $538,
   8% of spend. That is an upper limit. About half of the top 30 groups are real tasks (open a PR, merge main, read a CI
   failure, check an error tracker issue); the rest are follow-ups in other words.
3. **The cost of a prompt mostly measures where it sits in the session.** 97% of all tokens are cache reads. In the
   repeated groups only 0-16% of tokens are fresh. "Open PR" costs $0.23 at the median and $40.63 at most, for the same
   words. A skill changes little of that carried context, and so a "saves $X" figure from a prompt's cost is false.
4. **Session shape is the larger lever.** The median session costs $0.42, the p90 $12.10, and the top 10% of sessions hold
   84% of spend. Requests with more than 300K tokens of context are 37% of spend.
5. **Repeated tool calls are not a lever.** Exact repeats inside a prompt are 787 of 89,664 calls, 0.3% of result size.
6. **Word overlap splits one task.** The same task appears as several groups, in English and in Vietnamese. This is the
   part where an LLM adds value: naming and merging groups, not counting them.
7. **The before/after tool is unused.** The `changes` table has 0 rows, and `optimize.apply` does not write to it
   (`tokscope/experiments/optimize.py:307`). An improvement that you apply today leaves no measured result.

A skill also has a cost: its description goes into the skills list of every session start. The net effect of a new skill
on tokens is unknown until it is measured. The clear gains of a skill are consistency and less typing.

## What is there already

| The idea needs | Exists | Gap |
| --- | --- | --- |
| Logs | `prompts`, `requests`, `tool_calls` tables; privacy levels | Nothing groups prompts across sessions |
| Target | `budgets.json`, `tokscope check` (limits per day, skill, agent) | A limit warns; a target has a baseline, a goal and a date |
| Compare by session | Sessions tick 2 to 4, `core/context.py` findings | You pick the rows by hand |
| Compare by prompt | Per-prompt rows inside a session | No view across sessions |
| LLM run, then approve | Optimize: `claude -p` in `bench/optimize/<job>/`, budget cap, steps page, diff, Approve and apply | Starts from a skill, not from a finding; cannot create a skill |
| Verify | `tokscope change`, bench, replay | `change` is manual; replay has read-only tools, so it cannot run a task that pushes or merges |

## Proposed flow

```text
Target ──> Detect (free) ──> Suggestions ──Approve──> Analyze (paid, capped) ──> Plan ──Approve──> Apply ──> Measure
  ^                                                                                                          │
  └──────────────────────────────────────── progress against the target ─────────────────────────────────────┘
```

- **Target.** A `targets` key in `budgets.json`, so it shares the loader and `tokscope check`. Example:
  `{"metric": "session_cost_p90", "goal": 8, "by": "2026-12-01", "project": "x"}`. The baseline is frozen when the target is
  created. First metrics: session cost p90, share of spend above 300K context, session start tokens. These are the levers
  from the data above.
- **Detect.** New pure module `core/patterns.py` (stdlib, no LLM). It classifies each prompt (follow-up, machine, task),
  groups tasks, and keeps a group seen in 3 or more sessions. A machine prompt is found by shape, not by a word list: the same
  long text, as the first prompt, in many sessions. Reuse `BENCH_PROJECT` so experiments do not count.
- **Compare.** A group makes the comparison automatic: "same task, different cost". Show the cheapest, median and costliest
  run, with each run's context at the start of the prompt, and open them in the existing Compare view. Rank groups by
  fresh tokens and sessions, and show total cost only as context.
- **Suggestions.** Each one has a route, so "make a skill" is one answer of several:

| Pattern | Route |
| --- | --- |
| Repeated task, no skill loaded, similar steps | Draft a new skill |
| Repeated task, a skill already loaded, wide cost range | Existing Optimize, with the group as evidence |
| Same correction or request in many sessions ("translate to Vietnamese") | A line in `CLAUDE.md` |
| Same long template in many sessions | Shorten the template at its source |
| Cheap task late in a huge session | New session or `/compact` first; a smaller model through a subagent |

- **Analyze and plan.** Approve starts a job in `experiments/insights.py`, built on the Optimize job code, under
  `bench/insights/<job>/`, so it counts as an experiment. Input is a digest file, not raw transcripts: for each group the
  stats and up to 5 trimmed examples, about 9K tokens for 40 groups by estimate. Output is a plan: what to change, why, and how to
  measure it. It says "unknown until measured" for the saving, not a dollar figure.
- **Apply and measure.** A new skill or `CLAUDE.md` line is a draft with the existing diff and Approve and apply. Apply records a
  `changes` row by itself, so the before/after card and the target progress work without a manual step.

## Slices

Each slice is one issue and one PR. Slices 1 to 3 cost nothing to run.

| # | Slice | Done when |
| --- | --- | --- |
| 1 | `core/patterns.py`, `tokscope patterns [--format json]` | On a fixture, follow-ups and machine prompts form no task group; output has no prompt text at `redacted` |
| 2 | Dashboard page Patterns (full level only): groups, routes, cheapest/median/costliest run, link to Compare | Before/after screenshots at 1440 and 375 px; ranks by fresh tokens |
| 3 | `targets` in `budgets.json`, in `tokscope check` and on Overview | A frozen baseline, a progress line, a clear "no data" state |
| 4 | `experiments/insights.py`: Approve, digest, capped job, plan page | Token-like strings are masked in the digest; the run has no Bash; a test with `TOKSCOPE_CLAUDE` as a fake runs the flow |
| 5 | Draft a skill or a `CLAUDE.md` line, apply, auto `changes` row (also in `optimize.apply`) | A new skill appears in the Library; its before/after card shows without a manual step |

Slice 1 is the test of the whole idea. If its groups do not look useful on real data, stop there.

## Risks

| Risk | Control |
| --- | --- |
| Prompts hold secrets or client text, and go into a new run | Full privacy level only. Mask token-like strings in the digest. Show the digest before Approve |
| Prompts hold pasted text with instructions | The digest is data in a file. The run has Read and Write in its job folder only; no Bash, no web |
| A plan claims savings it cannot prove | The plan format has no saving field; the result comes from the measurement step |
| The tool's own runs change the numbers | Jobs run under `bench/`, which is left out by `BENCH_PROJECT` |
| Too few prompts for a new user | Show nothing below 3 sessions, and say so |
| A list that nobody reads | Dismiss per group, stored in the data home; a dismissed group stays hidden |

## Decisions

| Decision | Why | Rejected |
| --- | --- | --- |
| Detection is free and local; the LLM runs only after Approve | The classes above need no model; a digest is cheap and capped | Sending all prompts to an LLM on a schedule (cost, privacy, a paid step nobody asked for) |
| "Logs" means the transcript tables | They have the prompt text and 42 days of data | OTel logs (2 days of files here; `otel_requests` has no prompt text) |
| Rank by fresh tokens and sessions, never by total prompt cost | Total cost mostly measures session position (point 3) | The ranking by cost that the first prototype used |
| The product of this idea is a plan with routes, and skills are one route | The biggest levers in this data are not skills | A "prompts to skills" feature only |

Source of the numbers: `prompts`, `requests`, `tool_calls` and `changes` in `data/tokscope.db`. The script was not kept.
