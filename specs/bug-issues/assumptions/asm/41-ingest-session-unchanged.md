# ingest_session unchanged (issue 41)

- Context: The issue asks for the guard in both functions.
- Decision: Left ingest_session alone: glob on a missing dir already returns an empty list, so it returns False.
- Alternatives: Add an explicit is_dir check.
- Impact: None.
- How to reverse: Add the is_dir check (one line).
