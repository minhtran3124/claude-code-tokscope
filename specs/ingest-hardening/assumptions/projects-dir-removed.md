# PROJECTS_DIR removed

Issue #47, PR #85.

- **Context:** Constant was imported by cli, server and replay.
- **Decision:** Removed. projects_dir=None means the default dirs; a path or list is also accepted.
- **Alternatives:** Keep a constant.
- **Impact:** Existing callers and tests that pass a path still work.
- **How to reverse:** Restore the constant and point the default at it.
