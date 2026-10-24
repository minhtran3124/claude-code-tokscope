# Merge order and parallel calls

## Context

Merging #81 and #79 ran in parallel. #81 was rejected for conflicts and #79 merged.

## Decision

Resolved #81 by merging fix/bug-issues into its branch, which already held #78, #77, #80 and #79. Then merged #81.

## Alternatives

Resolve the conflicts on fix/bug-issues in a follow-up commit.

## Impact

All five PRs are merged. Final order on fix/bug-issues is 78, 77, 80, 79, 81.

## How to reverse

Revert the merge commit of #81 on fix/bug-issues, then redo the conflict fix in a follow-up commit.

