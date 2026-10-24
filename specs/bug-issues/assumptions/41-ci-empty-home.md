# CI empty HOME (issue 41)

- Context: The smoke step needs an empty home.
- Decision: Set HOME=/tmp/empty-home on the ingest command only.
- Alternatives: Export HOME for the whole step.
- Impact: None.
- How to reverse: Drop the HOME prefix or export it for the step.
