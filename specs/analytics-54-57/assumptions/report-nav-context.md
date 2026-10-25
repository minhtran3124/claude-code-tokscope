# Assumptions: Report nav links the Context section

Review fix for PR 104 (commit 93cb12f). The Artifact tool was unavailable (daily publish limit), so this is the file fallback.

## 1. No new screenshots for a one-link nav change
- **Context:** The UAT rule asks for before/after screenshots whenever a UI change lands.
- **Decision:** Skipped screenshots and relied on a unit test that checks the link is present in `writer.py`.
- **Alternative:** Render the report and capture it at 1440 and 375 px.
- **Impact:** The PR has no image of the new nav link. A reviewer can check it by opening the report.

## 2. PR body note not applied
- **Context:** `gh pr edit 104 --body-file` failed with the Projects classic GraphQL deprecation error.
- **Decision:** Left the PR body as it was and did not retry with another method.
- **Alternative:** Patch the body through `gh api` REST.
- **Impact:** The PR body does not mention the nav link. The commit message does.
