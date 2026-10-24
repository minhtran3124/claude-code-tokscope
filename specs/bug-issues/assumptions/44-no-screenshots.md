# Assumption (issue 44): No screenshots

- **Context:** UI PRs normally need before/after screenshots at 1440 and 375 px.
- **Decision:** Skipped them. The only markup change is a short note ('days in <zone>') under two chart titles, and day values move only for non-UTC users.
- **Alternatives:** Run the dashboard in a browser and capture screenshots.
- **Impact:** The reviewer must check the note text by eye.
- **How to reverse:** Capture before/after at 1440 and 375 px and add them to the PR.
