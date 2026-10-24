# No change to the /api/projects JSON

**Context:** The issue does not ask for an API field.

**Decision:** Left the API payload as is.

**Alternatives:** Add def_tokens and baseline to the API.

**Impact:** The new figures appear only in the HTML pages and the report.

**If wrong / how to reverse:** Add the two fields to the projects payload and a test. No breaking change to existing readers.
