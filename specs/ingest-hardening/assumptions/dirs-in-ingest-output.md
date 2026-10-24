# Dirs shown in ingest output

Issue #47, PR #85.

- **Context:** Issue says show the dirs in --version or ingest output.
- **Decision:** ingest logs 'ingest: reading <dirs>'.
- **Alternatives:** Also show them in --version.
- **Impact:** --version is unchanged.
- **How to reverse:** Remove the log line in ingest.
