# Base is main; integration branch feat/summary-export-baseline

Assumption for PR #93 (autopilot run, 2026-10-24).

## Context
The skill says base = current branch; CLAUDE.md says PRs target main. No redesign work is involved, so the v1 rule does not apply.

## Decision
Sub-PRs target feat/summary-export-baseline; one final PR (#93) goes from that branch to main for the owner to merge.

## Alternatives
Open the two PRs straight to main.

## Impact if wrong
Retarget the final PR if another base is wanted.

## How to reverse
Change the base of PR #93 on GitHub, or reopen the sub-PRs against main.

