# Query-time pricing via refresh on connect

## Context
The issue proposes computing cost at query time, but about 30 queries read the cost_usd column.

## Decision
Keep the column and recompute it in connect() when a fingerprint of the rates, multipliers and pricing.json differs from the one in the new meta table.

## Alternatives
A SQL function registered with create_function, or a prices table joined on model, would mean rewriting every cost query.

## Impact
Totals change on the next connect after a rate or pricing.json edit, with no re-parse. The first connect after a change does one UPDATE over all requests.

## How to reverse
Remove the fingerprint check in connect() and drop the meta row. Costs then stay as last written.
