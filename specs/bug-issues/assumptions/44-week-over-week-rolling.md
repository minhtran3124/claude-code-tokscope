# Assumption (issue 44): Week over week stays rolling

- **Context:** The issue lists Week over week among things sharing the day boundary.
- **Decision:** Left the report's week-over-week as a rolling 7x24h window from now, since it has no day bucket.
- **Alternatives:** Align it to local midnights.
- **Impact:** Low; the figures shift by at most part of a day.
- **How to reverse:** Change the report's week-over-week window to local midnights.
