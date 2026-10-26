# OTel leftovers: #157 then #158

Branch `feat/otel-leftovers` (from `github/main`). Two PRs, in this order; they touch disjoint files, so #158 rebases cleanly.

## 1. #157 Receiver hardening (effort S)
Files: `tokscope/integrations/otel_receiver.py`, `tokscope/cli.py` (only if flags change), `tests/test_otel_receiver.py`, `README.md`.
- Deep JSON: catch `RecursionError` around the parse, answer 400, write nothing.
- `--host ::1`: bind IPv6 (server class with `address_family = AF_INET6`) when the host is an IPv6 address.
- Privacy: data dir 0700, JSONL files 0600 (POSIX only; no-op on Windows).
- Chunked: decode `Transfer-Encoding: chunked` with the same caps before and after gzip; oversized chunked body refused.
Acceptance: tests for nested JSON, `::1` bind, file mode, chunked body, oversized chunked body (fail before, pass after).
`python3 -m unittest tests.test_otel_receiver -q`, then the full suite.

## 2. #158 Ingest dedupe, scale, prompt.id join (effort M)
Files: `tokscope/core/otel.py`, `tokscope/core/cache.py`, `tokscope/core/ingest.py` (schema, PARSER_VERSION, migration), `tokscope/core/privacy.py`, `tokscope/cli.py` (statusline), `tests/test_otel.py`, `tests/test_cache.py`, `tests/test_ingest.py`, `tests/test_privacy.py` as needed.
- Dedupe: stable key (session, prompt id, ts, model, token counts) with a unique index on `otel_requests`; migrate existing DBs (dedupe rows, then index).
- `match()`: sort by ts, bucket by model, two-pointer; no quadratic scan.
- Reader: stream lines from the stored offset instead of loading the tail.
- `statusline_snapshots.prompt_id` column (ids only; privacy map KEEP), written by `cache.record_snapshot` from stdin `prompt_id`; join in `cache.official_by` / Cost check when an OTel event has a matching prompt id, else old behaviour.
Acceptance: same export ingested twice adds nothing, migration on an old DB; `match()` on 50k events in a few seconds; bounded-memory read; prompt_id snapshot joins, missing ids fall back.
Layout: `core` must not import `features`/`web` (`tests/test_layout.py`).

## Checks
`python3 -m unittest discover -s tests -q` (baseline: 623 tests, 1 pre-existing failure `test_report.FindingTest.test_week_finding_compares_with_the_week_before`).
No UI files change, so no screenshots.
