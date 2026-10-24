# Definition tokens use the first main-thread shape

**Context:** A session can hold several shape records, and subagent files hold their own.

**Decision:** Use the first shape in the main transcript, which matches the first-request baseline. Size is the JSON length of each tool divided by 4 (an estimate).

**Alternatives:** Use the largest or latest shape, or the subagent shapes.

**Impact:** Tools added mid-session are not counted. Per project, the newest session that has a server supplies its figure.

**If wrong / how to reverse:** Change the shape picker to take max or latest. Figures are recomputed on the next page load.
