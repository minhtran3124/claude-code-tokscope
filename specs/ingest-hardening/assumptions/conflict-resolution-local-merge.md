# Conflict resolution by local merge

- **Context:** #86 conflicted with #85 after #85 merged.
- **Decision:** Merged the base branch into the PR branch locally, resolved the conflict, pushed, then ran `gh pr merge`.
- **Alternatives:** Rebase the PR branch.
- **Impact:** Adds one merge commit on `feat/ingest-48`.
- **How to reverse:** Revert that merge commit on `feat/ingest-48`, or rebuild the branch with a rebase and force-push it.
