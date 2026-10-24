# #49 sequenced after #47 and #48

- **Context:** All three issues edit ingest.py (paths loop, connect, SessionParser/store).
- **Decision:** #47 and #48 run first in parallel. #49 runs on the merged result.
- **Alternatives:** Run all three in parallel and resolve conflicts.
- **Impact:** Longer wall-clock time, fewer merge conflicts.
- **How to reverse:** Rebase #49 onto main and merge in any order, resolving conflicts by hand.
