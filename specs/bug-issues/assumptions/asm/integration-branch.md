# Integration branch fix/bug-issues cut from main

- **Context:** Skill rule says never merge into the base branch. CLAUDE.md says PRs target main.
- **Decision:** Sub-PRs merge into fix/bug-issues. One final PR to main for owner review.
- **Alternatives:** Separate PRs to main.
- **Impact:** The owner reviews one PR.
- **How to reverse:** Retarget each sub-PR to main and close the final PR. No commits are lost.
