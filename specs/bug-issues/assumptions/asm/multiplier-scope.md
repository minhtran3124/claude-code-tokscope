# Multiplier scope

## Context
The pricing page says fast mode is $8/$40 for Opus 5.5 and $10/$50 for Opus 5 and 4.8. US-only inference is 1.1x on 4.6+ models.

## Decision
Fast is 2x on all token categories for those three models. US 1.1x applies to every model except Opus 4.5 and older, Sonnet 4.5 and older, and Haiku 4.5 or older. Web fetch is not charged and is only stored.

## Alternatives
Fixed fast-mode rate tuples per model.

## Impact
Cache read and write costs follow the 2x multiplier. Models not on the fast list are not fast-priced even if a transcript says speed=fast.

## How to reverse
Edit the multiplier table in the pricing module; the fingerprint triggers a recompute on the next connect.
