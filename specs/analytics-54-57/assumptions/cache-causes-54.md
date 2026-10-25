# Assumptions: prompt-cache miss causes (issue 54)

The Artifact tool hit its daily publish limit (429), so this page is a committed file instead.

## 1. Statusline snapshot storage does not exist yet
- **Context:** no statusline snapshot table or code exists in the repo (grep of `tokscope` and `tests` for snapshot/prompt_cache found nothing relevant).
- **Decision:** `cache.official()` reads an optional table `statusline_snapshots(session_id, ts, prompt_cache JSON)`, takes each session's latest snapshot and sums `misses`, `miss_recache_tokens` and `miss_causes`. It returns `None` when the table is absent.
- **Alternatives:** build the statusline snapshot feature here, or skip official causes.
- **Impact:** official causes appear only once the statusline issue creates that table; its schema may need aligning.

## 2. Tools change reported as prefix_changed
- **Context:** transcripts cannot tell whether tools or the system prompt changed.
- **Decision:** a `cache_read` drop with an idle gap under 5 min is labelled `prefix_changed`, with a hint about stable MCP tool lists.
- **Alternatives:** correlate with `mcp_defs` per session to name `tools_changed`.
- **Impact:** less specific than the official `tools_changed` cause; the official block covers that when available.

## 3. Official causes are per session, not per skill/phase
- **Context:** the issue asks to group official `miss_causes` by skill/phase, but snapshots carry no skill attribution.
- **Decision:** official miss causes are summed per session set matching the filters.
- **Alternatives:** attribute each snapshot to the session's last skill.
- **Impact:** no skill/phase grouping of official causes.
