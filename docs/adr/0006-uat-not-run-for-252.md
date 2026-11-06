---
ticket: 252
stage: uat
status: needs-review
needs_review: true
confidence: high
decided_by: claude (ship workflow: uat)
date: 2026-11-06
---

# 0006. UAT not run for #252

## Context

The UAT stage could not check the running app: No verify.config.json at either allowed path: .../optimize-list-needs-decision/t252/verify.config.json does not exist, and the uat-252 worktree root (detached at 4b6a3ae) has none. UAT rules forbid inferring, writing or committing a config, so the app was not started. A file exists at .../optimize-list-needs-decision/verify-base-252/verify.config.json, but it is not a path I was given, so I did not use it.

## Options

- n/a

## Decision

Continue without UAT; the ticket stays done and the PR body says UAT did not run.

## Why

A missing config, a start failure or an agent failure is not an acceptance failure, so no code fix is attempted.

## Consequences

The running app was not checked against the original request.

## How to reverse

Run /harness:uat 252 by hand.
