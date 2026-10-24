# Synthetic data for screenshots, full privacy level

**Context:** The Projects page is hidden at the redacted level, and the uat.md default is redacted.

**Decision:** Used generated transcripts under a throwaway CLAUDE_CONFIG_DIR and HOME, with TOKSCOPE_HOME in the scratchpad, and served at full level. No real data was shown or touched.

**Alternatives:** Redacted level. It would only show the hidden-page notice.

**Impact:** The screenshots show a fake project (~/work/app).

**If wrong / how to reverse:** Re-shoot with other data. Nothing in the repo depends on the screenshots.
