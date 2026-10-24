# Rewrite rows instead of upserting

Issue #49. Artifact was unavailable (daily limit), so this is the file form.

- **Context:** The issue proposes upserting new or changed rows.
- **Decision:** store() still deletes and reinserts the session's rows, built from the resumed parser state.
- **Alternatives:** A true upsert. It risks drift from a full parse and complicates the #84 dedup.
- **Impact:** The file read and JSON parse are saved. Write-lock time is not reduced.
- **How to reverse:** Change store() to upsert rows. Resumed parsing does not depend on it.
