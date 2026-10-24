# /api/summary keeps its totals response without by/format

**Context:** The endpoint /api/summary already existed and returns the Overview totals JSON; an existing test covers it.

**Decision:** The new rows response applies only when `by` or `format` is in the query. Without them the old totals JSON is returned unchanged.

**Alternatives:** Move the totals to /api/totals and give /api/summary only the rows (breaking for anything calling the old path).

**Impact:** Existing callers keep working. A bare /api/summary does not return rows.

**How to reverse:** Move the totals to another path and update callers and the test.
