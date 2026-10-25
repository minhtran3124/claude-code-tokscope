# OTel ingest (#58): summary

Branch `feat/otel-ingest`. 608 tests pass (`python3 -m unittest discover -s tests -q`), including `tests/test_otel.py` and the layout test.

## Shipped

- `tokscope/core/otel.py`: reads `data/otel/logs-*.jsonl` (OTLP JSON) into `otel_requests` (session, prompt id, ts, model, tokens, `cost_usd`, duration, speed), incrementally by file and byte offset; a shrunk or replaced file is re-read without duplicates; a half-written line waits.
- Events are matched to `requests` by session, equal tokens and closest time (within 120 s); a transcript that arrives later matches old events.
- `ingest` reads OTel after the transcripts; `tokscope ingest --otel [DIR]` reads only OTel. A missing folder is a no-op.
- Cost check card (`web/report/sections/cost_check.py`) in the report and dashboard Overview: Claude Code `cost_usd` against tokscope API-eq per model, drift, unmatched events, "telemetry only" sessions. A model with no rate counts as $0, so it drifts 100%.
- README and PRODUCT.md updated.

## Checked here

- Temp `TOKSCOPE_HOME` with 18 real sessions and a generated fixture (40 matched events, 1 unmatched, 2 events of a session with no transcript, 1 model with no rate): first `ingest --otel` gave 43 new events, the second "no new OTel events".
- Card showed claude-sonnet-5-5 2% drift, claude-future-9 100% (no rate), 1 unmatched, 1 "telemetry only" session. Screenshots at 1440 and 375 px; no horizontal scroll at 375.

## Gaps

- A telemetry-only session is not a row in the Sessions table or the API-eq totals (no transcript to price); it shows on the card and in "Claude Code reported", marked "telemetry only".
- `prompt.id` is stored but not yet joined to statusline snapshots (the issue's third goal).
- Event attribute names come from the monitoring docs; no real Claude Code export was ingested.
- GitHub Actions has not run on this branch (billing blocker).
