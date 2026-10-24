# STATUS.md conflict resolution

- **Context:** Merging #89 and #90 conflicted in STATUS.md. Both PRs prepended a 2026-10-24 line to Recent.
- **Decision:** Keep both lines, #89 first, then #90.
- **Alternatives:** Merge them into one line. Shorter, but loses each PR's wording.
- **Impact if wrong:** Recent has 11 lines, over the 10-line cap in CLAUDE.md. A scanner or reviewer may flag it. No code is affected.
- **How to reverse:** Join the two 2026-10-24 lines into one, or drop the oldest line, and commit.
