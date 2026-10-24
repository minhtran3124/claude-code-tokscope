# Report downloads are built from embedded rows in the browser

**Context:** The report has no server, so download links cannot call the endpoint.

**Decision:** The report embeds all four groupings as data-rows JSON on hidden panes. JS builds CSV and JSON Blobs for the visible grouping, and chips switch panes client-side.

**Alternatives:** One grouping only, or a single embedded JSON block.

**Impact:** The report grows by four small tables. Group-by in the report is not kept in the URL, since it is a static file.

**How to reverse:** Embed one grouping or a single JSON block.
