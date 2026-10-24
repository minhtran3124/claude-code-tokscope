# Error shown in the live chip

Source: issue #48 (PR 86).

## Context
Issue #48 asks to show Live.error on the dashboard.

## Decision
Reuse the header live chip text (truncated to 80 chars, full text as tooltip, hollow dot) via a new `error` field in /api/version.

## Alternatives
A new banner element.

## Impact
No layout change; small visible surface.

## How to reverse
Remove the `error` field from /api/version and the chip error branch in the dashboard script.
