# Snapshot detection tightened

Issue 43, PR 80.

- **Context:** Adding claude-opus-4 made claude-opus-4-9 resolve to Opus 4 via the old isdigit check
- **Decision:** Require an 8-digit suffix
- **Alternatives:** Keep isdigit
- **Impact:** Unknown minor versions are reported as unpriced instead of mispriced
- **How to reverse:** Restore the isdigit check in the snapshot helper.
