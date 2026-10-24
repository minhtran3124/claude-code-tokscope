# gh issue view needs --json

Assumption for PR #93 (autopilot run, 2026-10-24).

## Context
Plain `gh issue view` failed with the Projects (classic) GraphQL deprecation error.

## Decision
Read the issues with `--json number,title,body,labels`.

## Alternatives
Use `gh api` to fetch the issues.

## Impact if wrong
None; the issue text was read in full.

## How to reverse
Nothing to reverse. It only changed how the issues were read.

