---
ticket: 187
stage: intent
status: needs-review
needs_review: true
confidence: medium
decided_by: claude (ship workflow: intent)
date: 2026-11-04
---

# 0007. evals.json check shape and INVALID outcome

## Context

Owner fixed the `checks` key and six types; field names inside a check are left open.

## Options

- {type, ...params, safety?: bool} with params regex/path/contains/tool/order/name
- nested params object

## Decision

Flat check objects: {type, text?, safety?} plus per-type keys: answer_regex.pattern, file_exists.path, file_contains.path+pattern, tool_called.tool(+optional input_contains), tool_order.tools[], no_permission_denials (none). grading.json also carries a top-level status of ok or INVALID and pass counts; INVALID has an empty expectations list and no counts.

## Why

Simple to write by hand and extends skill-creator's evals.json without clashing.

## Consequences

Slice 2 (suite loader) must accept this shape.

## How to reverse

Change the parser in grade.py; evals.json files would need migration.
