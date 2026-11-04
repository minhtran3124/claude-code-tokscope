---
ticket: 187
stage: merge
status: needs-review
needs_review: true
confidence: high
decided_by: claude (ship workflow: merge)
date: 2026-11-04
---

# 0008. Merge PR 199 by hand for #187: gate review, needs_review failed

## Context

The merge gate for #187 did not pass. review: 0 not fixed, 2 left at score 50 or more. needs_review: 4 (evals.json check shape and INVALID outcome; Isolated single-case runner in a new skillopt package; Where the checks key lives in evals.json; Cap each case run with --max-budget-usd 2.0).

## Options

- n/a

## Decision

The workflow does not merge this PR into feat/skill-optimize-v2. After you have checked the failed gates, run: gh pr merge 199 --repo minhtran3124/claude-code-tokscope --merge

## Why

Only a ticket PR that passes CI, review, intent review and has no open needs_review decision is merged by the workflow.

## Consequences

Ticket #187 is missing from the final PR and the tickets that depend on it are skipped until the PR is merged.

## How to reverse

Do not run the command; close the PR instead.
