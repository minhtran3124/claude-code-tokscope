# Baseline range uses the first request time

**Context:** The filter bar range applies to requests, and the baseline is a per-session figure.

**Decision:** A session counts in a range when its first main-thread request falls in it. The 30-day trend ignores the range and uses all of the project's sessions.

**Alternatives:** Count a session when any of its requests are in range.

**Impact:** A long-running session that started before the range is excluded.

**If wrong / how to reverse:** Change the session filter from first request time to any request in range.
