# Assumption: pool MCP p95 by project inside `server_p95`

Review fix for PR 104. Projects MCP p95 was one folder's p95, overwritten per cwd, not the project's.

- **Decision:** extend `server_p95` with an optional cwd-to-key mapping, so pooling happens in `core` and `_pct` stays private. `core` still does not import `features`.
- **Context:** the finding suggested collecting token lists per group, then taking `_pct` once on the server side.
- **Alternative not taken:** return raw sample lists and compute the percentile in `features/projects.py`. It needs the private `_pct`.
- **Impact:** minimal diff. The only caller is `features/projects.py`. Fixed in `a6f2874`, tested in `tests/test_projects.py`.

Note: the Artifact tool hit its daily publish limit (429), so this page is a committed file instead.
