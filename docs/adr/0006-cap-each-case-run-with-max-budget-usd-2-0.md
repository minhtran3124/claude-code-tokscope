---
ticket: 187
stage: implement
status: needs-review
needs_review: true
confidence: medium
decided_by: claude (ship workflow: implement)
date: 2026-11-04
---

# 0006. Cap each case run with --max-budget-usd 2.0

## Context

The design argv had no cost cap, but bench, replay and optimize all pass --max-budget-usd. The advisor asked for one.

## Options

- No cap
- Fixed constant MAX_BUDGET_USD=2.0 in sandbox.py
- Add a --budget CLI flag now

## Decision

A fixed constant of 2.0 USD in command(), asserted in the argv test. A CLI flag can come later.

## Why

A paid run must not be unbounded, and a constant keeps the CLI surface as designed.

## Consequences

A case that needs more than 2 USD ends with is_error and its checks fail on their own evidence.

## How to reverse

Change or remove MAX_BUDGET_USD and the flag in command().
