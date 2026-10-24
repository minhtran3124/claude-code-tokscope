# #45 sequenced after #43

- **Context:** Both issues rewrite pricing.
- **Decision:** #43 first, #45 builds on it.
- **Alternatives:** Run in parallel and resolve conflicts.
- **Impact:** Longer wall-clock time, fewer conflicts.
- **How to reverse:** Rebase #45 onto main and drop the dependency on #43. Expect conflicts in the pricing files.
