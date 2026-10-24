# The filter bar's Apply drops the group-by

**Context:** The group-by lives in `?by=` in the URL, and the filter bar is a plain GET form.

**Decision:** Pressing Apply keeps the filters but resets the group-by to phase. Clicking a chip keeps all filters.

**Alternatives:** Add a hidden `by` input to the filter form, or add `by` to the shared Filters class.

**Impact:** A small papercut. The URL still keeps the group-by on every chip click, which is what the issue requires.

**How to reverse:** Add a hidden `by` input to the filter form.
