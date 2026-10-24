# Experiments use connect()

Source: issue #48 (PR 86).

## Context
Issue #48 allowed `connect()` or a lighter `open_db()`.

## Decision
bench, replay and optimize call `connect()` (schema script included); privacy calls `open_db()`.

## Alternatives
`open_db()` everywhere.

## Impact
Schema creation runs on those opens; harmless and idempotent.

## How to reverse
Swap `connect()` for `open_db()` in bench, replay and optimize.
