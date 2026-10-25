# Issue 56 (Context section): assumptions

## A1. Context window size is inferred
- Context: transcripts do not name the context window.
- Decision: use 200K, or 1M once any request in the session exceeded 200K.
- Alternatives: a per-model window table, which would go stale; a user-configurable window.
- Impact: a 1M-window session below 200K shows too full; a pressure percentage is approximate.

## A2. Chars-per-token calibration is limited to the new code
- Context: the issue asks for per-model-family calibration (4.7+ is about 30% denser, so 4/1.3 = 3.1 chars/token).
- Decision: use the calibrated ratio in the Context section and the Projects p95. The existing by-tool and by-MCP tables and the Projects result-token totals keep the flat 4 chars/token.
- Alternatives: change calls.est_tokens everywhere, which would shift existing numbers and tests.
- Impact: the Context section's totals can differ from the older By tool and By MCP server tables for the same calls.

## A3. Big Read hint uses a token proxy
- Context: line counts are not stored, so "Read of files > 2K lines" cannot be measured directly.
- Decision: count Read results of about 20K tokens or more as the proxy, and hint to read with offset/limit.
- Alternatives: store line counts at ingest.
- Impact: approximate; long-line files can be flagged earlier or later than 2K lines.

## A4. Compactions come from compact_boundary records
- Context: the issue says to store compaction markers if not stored yet.
- Decision: record system records with subtype compact_boundary as turn_events kind "compact". errors.py ignores that kind, so error counts are unchanged. The carry window stops at the next compaction in the same thread.
- Alternatives: detect compaction summaries from isCompactSummary user messages.
- Impact: depends on Claude Code writing compact_boundary; transcripts without it show no compactions.

## A5. tool_calls gets a model column
- Context: calibrating tokens per model needs the model that made the call.
- Decision: add tool_calls.model (privacy KEEP), filled by the PARSER_VERSION 18 re-parse and added by connect() to existing DBs.
- Alternatives: join to the nearest earlier request at query time.
- Impact: old rows have a NULL model until re-ingest and use 4 chars/token. The model filter now also applies to tool calls in the Context section.
