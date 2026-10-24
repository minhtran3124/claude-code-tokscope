# Sub-PRs merged without the per-PR /code-review

Assumption for PR #93 (autopilot run, 2026-10-24).

## Context
CLAUDE.md asks for a review of every PR; the no-HITL run merges sub-PRs into the feature branch only.

## Decision
The final PR gets the review after the run; sub-PRs are not reviewed separately.

## Alternatives
Review each sub-PR before merging.

## Impact if wrong
Findings appear on the final PR, not on the sub-PRs.

## How to reverse
Run /code-review on #91 and #92 now; fix findings on the feature branch.

