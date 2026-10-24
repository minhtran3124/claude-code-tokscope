# Unterminated last line

Issue #49. Artifact was unavailable (daily limit), so this is the file form.

- **Context:** The active writer may leave a partial last line.
- **Decision:** Consume a last line without a newline only if it is valid JSON, otherwise wait.
- **Alternatives:** Always wait for the newline. That would differ from a full parse on files that lack a final newline.
- **Impact:** Matches full-parse results.
- **How to reverse:** Always wait for the newline. Files without a final newline then lag until they grow.
