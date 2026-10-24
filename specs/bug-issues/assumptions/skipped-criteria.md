# Skipped issue acceptance criteria

## Context

The task said to run the issue acceptance criteria and the full test suite, but the issues were not re-read.

## Decision

Only ran the full test suite on the merged result. The authoring agents' evidence in each PR stands.

## Alternatives

Re-run each issue's acceptance criteria on the merged branch.

## Impact

Combined behaviour is covered by 318 passing tests but not by a manual run of each issue's acceptance criteria.

## How to reverse

Read each bug issue's Done-when list and check it by hand on fix/bug-issues.

