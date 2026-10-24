# No dedup without confirmation

Source: issue #46

- **Context:** The issue says to implement dedup only if copies are confirmed. Local data showed none.
- **Decision:** Documented the finding and added a guard test only.
- **Alternatives:** Add a global (message.id, requestId) key anyway. That would hide real requests for no observed benefit.
- **Impact:** Fork and rewind copies stay unverified. Rerun the scan if such files show up.
- **How to reverse:** Delete the guard test and add the dedup key later if copies are found. No data or schema was changed.
