---
ticket: 181
stage: uat
status: needs-review
needs_review: true
confidence: high
decided_by: claude (ship workflow: uat)
date: 2026-11-04
---

# 0003. UAT not run for #181

## Context

The UAT stage could not check the running app: verify.config.json is missing at both allowed paths: .../followups-180-181/t181/verify.config.json (the directory t181 does not exist) and the root of the uat-181 worktree. UAT rules forbid inferring, writing or committing a config, so the app was not started.

## Options

- n/a

## Decision

Continue without UAT; the ticket stays done and the PR body says UAT did not run.

## Why

A missing config, a start failure or an agent failure is not an acceptance failure, so no code fix is attempted.

## Consequences

The running app was not checked against the original request.

## How to reverse

Run /harness:uat 181 by hand.
