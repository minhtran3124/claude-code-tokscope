# Research: Skill Optimize v2, an evaluated loop instead of a rewrite

Design page (Vietnamese, with UI mocks): https://claude.ai/artifact/ANQd9hiw6dZizuAQ7Prabi. This note is the source for the
tickets of milestone "Skill Optimize v2".

## Intent

Owner, 2026-11-02 (verbatim): "big refactor + update cho feature chay optimize hien tai o Lirary […] tôi muốn remove cái logic
optimize hiện tại với với ste, unslop, optimize skill / tôi muốn viết 1 workflow để optimize skill 1 cách đúng đắn có evaluation,
có đo đạc kiểm chứng, có bằng chứng […] kỳ vọng output là / - 1 skill dc optimize/testing/evaluation cẩn thận / - có UI show
structure rõ ràng, có bằng chứng, benchmark / - có UI so sánh trước và sau / - có 1 nơi để lưu trữ các lần chạy".
Follow-ups: "có nut approve sau khi chạy xong optimize, có nghĩa là đồng ý replace skill version mới. fingerprint cũng phải dc
cập nhật chỗ này để hiểu"; "approve la tu commit"; "nếu skill ở mức user thì làm gì có repo để commit?".

In English: replace the guide-based Optimize (STE, unslop, optimize-skill rewrites) with a workflow that tests a skill, measures
it against its current version, keeps the evidence and every run, shows before and after, and lets the owner Approve. Approve
replaces the skill, updates the fingerprint tokscope knows, and commits when the skill is in a git repo.

## Why the current Optimize goes

- Both real jobs in `bench/optimize/` wrote no file (writes to `.claude/skills/` were denied) and still ended `done`.
- The agent that rewrites the skill also tests it. Its "39% fewer words" was never measured again.
- Fewer words is not better behaviour. The benchmark is optional, one task, a regex grader, and Apply works with no measure.
- Reference point: agent-harness `tickets`, evaluated with skill-creator, went from 29/44 to 85/88 checks and from 4 safety
  failures to 0.

## Workflow

| Step | What | Owner? |
| --- | --- | --- |
| 1 Preflight | Skill is eligible; one cheap run confirms the pinned copy is the one loaded; show a cost and time estimate. | |
| 2 Suite | Use `<skill>/evals/evals.json`, or draft cases from SKILL.md and real calls in transcripts. Split dev and holdout. | approves |
| 3 Lock | Write `plan.json`: suite hash, gates, model, Claude Code version, budget. Criteria cannot change after results. | |
| 4 Baseline | Current version and a no-skill arm on every case. Stop if the suite cannot tell them apart. | |
| 5 Edit rounds | At most 3. The editor sees only failed dev cases, costly steps and failed attempts; each edit states a hypothesis. | |
| 6 Confirm | Best draft against current on all cases incl. holdout, fresh interleaved runs. Only these numbers decide. | |
| 7 Decide | Owner reads report and comparison, then Approve or Reject. The run page later adds real-session numbers. | decides |

Isolation (probed, 4 haiku runs, under $0.01): `claude -p --setting-sources project --strict-mcp-config
--no-session-persistence` in a temp folder with the pinned copy loads that copy even when a personal skill has the same name;
context fell from 98.6k to 18.3k tokens. Five plugins still load in that mode and their source is not known yet.

Graders, in order: machine checks (answer regex, files written, tools called, call order, permission denials); the same with a
`safety` flag (must hold on every run); a per-skill `evals/score.py` for skills that need stubs (like `gh` in tickets); a blind
LLM grader that must quote evidence, only when a machine cannot grade. A run with no result is INVALID, not failed.

## Gates

Locked in `plan.json`. Verdicts: Apply, Not enough evidence, Reject.

| Gate | Passes when | Else |
| --- | --- | --- |
| Valid | at least 90% of runs valid; only runs that read the pinned version count | Not enough evidence |
| Meaningful suite | current version beats no-skill by at least 20 pass-rate points | Not enough evidence, stopped at baseline (step 4); no draft, so Approve is not offered |
| Safety | 0 safety failures on the draft, every run | Reject |
| No regression | 95% CI lower bound of the pass-rate difference ≥ −5 points, and holdout not lower | Reject |
| Benefit | CI upper bound of the cost difference < 0, or CI lower bound of pass difference > 0 | Not enough evidence |

CI: paired bootstrap by case (stdlib). Estimates, not measured: 6 cases × 3 runs reliably shows only about a 25% cost cut;
one optimize costs about $8–33 (≤ 78 runs) against $0.5–0.7 today. The budget is a hard cap: at the cap the run stops, keeps its
results and says Not enough evidence.

## Storage

Files are the source of truth; SQLite is an index. One run holds all it needs to regrade and review.

```
bench/optimize/runs/<run-id>/
  plan.json  suite/  versions/v0 v1 …/  rounds/<n>/editor/
  results/<round>/<case>/<arm>/<i>/{stream.jsonl,final.md,files/,grading.json}
  benchmark.json (skill-creator schema)  verdict.json  ledger.jsonl  apply.json  decision.json
```

The suite lives in `<skill>/evals/`, which the fingerprint already skips (with the other top-level test folders in
`BENCH_DIRS`: `eval/`, `tests/`, `test/`, `fixtures/`, `results/`). JSON, not YAML (stdlib only). `evals.json` keeps `evals` and `checks` and gains `split: {hash, holdout: [ids]}` (hash = sha256 of `evals`+`checks`; kept while it matches, redone after an edit; holdout is the first ceil(n/3) ids of a hash-seeded shuffle). Tables `opt_results`
(joins `requests` by `session_id`) and `opt_applied`. The worker is a separate CLI process (`tokscope optimize run|resume|regrade`,
new names), so a run survives a dashboard stop.

## Approve

Nothing in the real skill changes before Approve. Approve keeps the measured fingerprint equal to the installed one.

1. The skill's current fingerprint equals the run's base, else refuse (rerun).
2. The draft's fingerprint equals the one confirmed in `verdict.json`.
3. Write `apply.json`; `skills.record` the old version so its snapshot is kept.
4. Replace only files the fingerprint covers, each through a temp file and rename (the top-level `BENCH_DIRS` folders `eval/`, `evals/`, `tests/`, `test/`, `fixtures/`, `results/`, hidden files and
   files over 1 MB stay as they are).
5. The new fingerprint must equal the measured one; else restore from the snapshot and report.
6. Commit when the skill's real path is in a git repo: `git commit --only -- <skill files>` on the current branch, message
   `optimize(<skill>): <old> → <new>` with verdict and run id; no push, no `--no-verify`; a failing hook restores the snapshot.
   Detached HEAD disables Approve. A user-level skill outside git skips the commit: the snapshot in
   `data/skills/<skill>/<fingerprint>` is the history and Revert copies it back through the same checks. A symlinked skill
   follows its real path.
7. `skills.record` the new version with source `optimize`, add the `changes` row (#172, and keep #181: a `sqlite3.Error` there
   does not fail the apply), write `decision.json` and an `opt_applied` row linking version, commit and run.

Buttons by verdict: Apply → one click; Not enough evidence → Approve with a typed reason, kept; Reject (safety or regression) →
disabled. Reject is always allowed and recorded. Library shows Verified (fingerprint equals the approved one), Edited after run,
or Not verified.

Known bugs to fix on the way: `apply` copies `library.files` while the fingerprint uses `skills._files`, so a draft without
the `BENCH_DIRS` folders (`evals/`, `tests/`, `fixtures/` and the rest) deletes them from the skill (`optimize.py`); no check after writing; `skills.scan` does not skip bench sessions; `by_text` picks the
first version with the same body; a restore to a known version does not move `first_seen`.

## Refactor

Delete: `GUIDES`, `prompt()`, `guides_available()`, the guide form, `bench_start`, `bench_results`, `new_task`,
`_bench_section` and their routes. Rewrite: `_job_view`, `apply`, `tests/test_optimize.py`. Reuse: `bench.schedule`,
`skills.check_load`, `skills._snapshot`, `skills.record`, `changes_between`, `_side_by_side`, `_compare`, `_event`. Keep:
`tokscope bench` and the STE check tab in Library. New: `tokscope/experiments/skillopt/` (`suite`, `sandbox`, `grade`, `stats`,
`loop`, `store`) and `tokscope/web/dashboard/pages/optimize.py`, all testable with a fake `TOKSCOPE_CLAUDE`.

## Slices

1. **isolated-runner**: one case runs on a personal skill in the isolated mode and writes `grading.json` with evidence; the
   run can write files (the old denial is fixed).
2. **eval-suite**: load and check a suite, split dev/holdout, draft cases from real sessions; the editor cannot read holdout.
3. **optimize-loop**: a full run from the CLI with locked plan, ledger, budget cap, resume, stats and verdict.
4. **approve-cli**: Approve and Reject from the CLI per "Approve" above, incl. Revert outside git.
5. **version-history-fixes**: `scan` skips bench sessions; `by_text` picks the newest version before the load.
6. **optimize-page**: `/optimize` page with runs, report, before/after compare, evidence and Approve; Library shows the
   verified state.
7. **remove-guide-optimize**: delete the old logic; update PRODUCT.md and DECISIONS.md.
8. **trigger-eval**: a draft that changes the description must pass a trigger eval (60/40 split).
9. **post-ship-metrics**: the run page adds real-session numbers after Approve.

First acceptance run after slice 6: a real run on `create-pr`, the skill both old jobs failed on.

## Decisions

| Point | Choice | Why |
| --- | --- | --- |
| Runner | own code, not `claude plugin eval` | no stubs there, and it compares against no plugin, not old against new |
| Description | locked to the first version until slice 8 | a case that calls `/skill` cannot measure triggering |
| Approve | replace and commit if in git, no push; outside git keep a snapshot and offer Revert | owner chose commit; user-level skills have no repo |
| No regression | blocks Approve, like safety | evidence of a drop should not be one click away |
| STE tab | kept | it only reads; the owner asked to drop the optimize logic |
| Old jobs | left on disk, not shown | neither has a result |
| Plugin skills | not supported in slices 1–7 | Library does not list them |

Owner accepted this design on 2026-11-04 ("ok, tạo ticket đi").

## Risks

- Cost rises 10–60×; step 1 always shows the estimate.
- A bad suite gives a bad verdict; the owner's suite review is the main guard.
- Skills that need AskUserQuestion or outside services need an owner script and stubs, like tickets.
- The isolated mode differs from real use; a skill that needs CLAUDE.md or a plugin must declare it in the case.
