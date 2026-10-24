# Cost values are rounded to 6 decimals

**Context:** Summed floats showed noise such as 4.3607000000000005 in CSV and JSON.

**Decision:** rows() rounds cost_usd and carried_cost_usd to 6 decimals.

**Alternatives:** Keep raw floats, or round to 2 like the table.

**Impact:** Cleaner numbers in files. Table output is unchanged except for a cost within 1e-6 of a .005 boundary.

**How to reverse:** Remove the round() calls in rows().
