# Scan in Python, not SQL

Source: issue #46

- **Context:** The issue's SQL check needs a populated database, which this worktree does not have.
- **Decision:** Ran an equivalent read-only scan of the raw ~/.claude/projects jsonl files.
- **Alternatives:** Ingest the files into a database and run the issue's SQL.
- **Impact:** Same check. It ran on the raw data, so ingest quirks do not affect it.
- **How to reverse:** Ingest the files and run the SQL from the issue. Nothing was written, so nothing needs undoing.
