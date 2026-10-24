# Download links use the table's row limit (25), not all groups

**Context:** The CLI --limit defaults to 25, and the issue wants the file to match the table.

**Decision:** /api/summary applies `limit` (default 25, clamped to 1..1000). The dashboard's download links omit it, so they match the table. The report embeds the same 25 rows.

**Alternatives:** Export every group in the download.

**Impact:** A skill, agent or phase ranked below 25th by cost is missing from the files. A `limit` can be added to the URL by hand.

**How to reverse:** Pass a large `limit` in the download links.
