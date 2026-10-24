# Screenshots skipped

Source: issue #48 (PR 86).

## Context
UI rule needs before/after screenshots published to pr-assets.

## Decision
Not produced. The PR body says so.

## Alternatives
Run two servers and capture with Playwright.

## Impact
The reviewer must take them before merge.

## How to reverse
Start `bin/tokscope serve` on main and on the branch (two ports), capture both with Playwright at 1440 and 375 px, publish to pr-assets, add to the PR body.
