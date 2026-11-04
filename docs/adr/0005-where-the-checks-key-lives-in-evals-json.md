---
ticket: 187
stage: design
status: needs-review
needs_review: true
confidence: medium
decided_by: claude (ship workflow: design)
date: 2026-11-04
---

# 0005. Where the checks key lives in evals.json

## Context

Owner confirmed a `checks` key with six types; the intent says 'top-level', but checks differ per case. Two readings: one file-level list, or a list per case.

## Options

- Per-case `checks`, plus an optional file-level `checks` applied to every case
- Only a file-level `checks` list
- Only per-case `checks`

## Decision

Read `checks` from the case object; an optional file-level `checks` list is appended to every case (useful for safety checks like no_permission_denials). Flat check objects {type, text?, safety?, per-type keys: pattern / path / path+pattern / tool(+input_contains) / tools[]}; unknown type or missing key is a load error.

## Why

Per-case is the only reading that lets different cases have different checks; adding file-level covers the literal 'top-level' reading without contradiction.

## Consequences

Slice 2 (suite loader) must accept the same shape; hand-written evals.json files follow it.

## How to reverse

Change the loader in sandbox.py and the parser in grade.py; migrate any evals.json files.
