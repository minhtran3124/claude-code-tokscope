---
ticket: 191
stage: uat
status: needs-review
needs_review: true
confidence: high
decided_by: claude (ship workflow: uat)
date: 2026-11-04
---

# 0009. UAT not run for #191

## Context

The UAT stage could not check the running app: verify.config.json is missing at both allowed paths: .../skill-optimize-v2/t191/verify.config.json (that directory exists but has no such file) and the root of the uat-191 worktree (not tracked on github/feat/skill-optimize-v2). The UAT rules say never to infer or write a config, so the run stopped.

## Options

- n/a

## Decision

Continue without UAT; the ticket stays done and the PR body says UAT did not run.

## Why

A missing config, a start failure or an agent failure is not an acceptance failure, so no code fix is attempted.

## Consequences

The running app was not checked against the original request.

## How to reverse

Run /harness:uat 191 by hand.
