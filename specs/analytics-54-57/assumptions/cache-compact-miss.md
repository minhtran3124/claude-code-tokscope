# Assumptions: prompt-cache miss check sees compactions

Review fix for PR 104. Every /compact or auto-compact was counted as a prompt-cache miss, because the check never looked at compactions. Fixed in `1f36f22`.

## A1. Compact matched on the same thread

- **Context:** the finding suggested matching session and agent_id.
- **Decision:** match `COALESCE(agent_id,'')` equal to the request thread's agent id, so a main-thread compact does not mask subagent misses.
- **Alternative not taken:** match on session only. It also hides subagent misses after a main compact.
- **Impact:** a `compact_boundary` recorded with an agent_id different from the request thread does not suppress a miss.

## A2. Test inserts the turn_events row directly

- **Context:** the finding suggested ingesting a transcript with `compact_boundary`.
- **Decision:** insert the row that ingest writes. The existing fixture is DB-level.
- **Alternative not taken:** a full transcript ingest test.
- **Impact:** ingest-to-`turn_events` is not covered by this test, but ingest already emits the row.

Note: the Artifact tool hit its daily publish limit (429), so this page is a committed file instead of an artifact.
