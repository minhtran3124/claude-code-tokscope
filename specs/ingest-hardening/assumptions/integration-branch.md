# Integration branch feat/ingest-hardening cut from main

- **Context:** Skill rule: never merge into base automatically; issues #47-#49 are not labelled bug.
- **Decision:** Sub-PRs merge into feat/ingest-hardening. One final PR (#88) goes to main.
- **Alternatives:** Separate PRs straight to main.
- **Impact:** The owner reviews one PR instead of three.
- **How to reverse:** Retarget each sub-PR to main with `gh pr edit --base main`, then close #88.
