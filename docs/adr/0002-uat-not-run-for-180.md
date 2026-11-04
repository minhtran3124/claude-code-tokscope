---
ticket: 180
stage: uat
status: needs-review
needs_review: true
confidence: high
decided_by: claude (ship workflow: uat)
date: 2026-11-04
---

# 0002. UAT not run for #180

## Context

The UAT stage could not check the running app: No verify config found. Neither /home/minhtran/Documents/minh.tran/projects/.ship-claude-code-tokscope/followups-180-181/t180/verify.config.json (the t180 directory does not exist) nor verify.config.json at the root of the uat-180 worktree exists. The UAT skill forbids inferring or writing a config, so the app was not started.

## Options

- n/a

## Decision

Continue without UAT; the ticket stays done and the PR body says UAT did not run.

## Why

A missing config, a start failure or an agent failure is not an acceptance failure, so no code fix is attempted.

## Consequences

The running app was not checked against the original request.

## How to reverse

Run /harness:uat 180 by hand.
