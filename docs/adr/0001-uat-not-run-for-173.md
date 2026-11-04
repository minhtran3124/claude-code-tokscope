---
ticket: 173
stage: uat
status: needs-review
needs_review: true
confidence: high
decided_by: claude (ship workflow: uat)
date: 2026-11-02
---

# 0001. UAT not run for #173

## Context

The UAT stage could not check the running app: No verify.config.json exists at either allowed path: t173/verify.config.json or the root of the uat-173 worktree. The skill forbids inferring or writing one, so the app was not started.

## Options

- n/a

## Decision

Continue without UAT; the ticket stays done and the PR body says UAT did not run.

## Why

A missing config, a start failure or an agent failure is not an acceptance failure, so no code fix is attempted.

## Consequences

The running app was not checked against the original request.

## How to reverse

Run /harness:uat 173 by hand.
