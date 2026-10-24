# Unresolved subagent spawn forces a full parse

Issue #49. Artifact was unavailable (daily limit), so this is the file form.

- **Context:** A subagent file can appear before the main file records the tool call that spawned it.
- **Decision:** Mark such a file unresolved and do a full parse next time.
- **Alternatives:** Keep the stale null attribution.
- **Impact:** Rare extra full parses.
- **How to reverse:** Remove the unresolved mark. Attribution may stay null until a manual re-ingest.
