# Duplicate session id across dirs

Issue #47, PR #85.

- **Context:** A session lives in one dir, but the same id could appear twice.
- **Decision:** First dir wins; the later copy is skipped.
- **Alternatives:** Newest signature wins.
- **Impact:** No duplicate rows.
- **How to reverse:** Change the skip to a signature comparison in the dir scan.
