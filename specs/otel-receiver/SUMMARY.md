# OTel receiver (#50): summary

Branch `feat/otel-receiver`, commit b3da0eb plus this summary. 590 tests pass (`python3 -m unittest discover -s tests -q`). No change under `tokscope/web/`, so no UI screenshots.

## Shipped

- `collector/otlp_receiver.py` moved to `tokscope/integrations/otel_receiver.py` (in the package; `packages.find include tokscope*` ships it) and exposed as `tokscope otel-receiver`.
- Writes `data/otel/<signal>-YYYY-MM-DD.jsonl` under `paths.home()` (`TOKSCOPE_DATA_DIR` overrides).
- Hardening: body cap 8 MiB (`--max-body`), 413 for oversize and gzip bombs, 400 for bad Content-Length or gzip, 415 for non-JSON, 404 for other paths, loopback-only bind unless `--allow-remote`.
- README says it only collects data and no view reads it yet (reading is #58), with the Claude Code env vars.
- `tests/test_otel_receiver.py`: happy path (one JSONL line), gzip, oversize, bomb, bad gzip, bad length, non-JSON, 404, bind rule.

## Checked here

- Live run in a temp `TOKSCOPE_HOME`: POST to `/v1/logs` gave `{} 200` and one line in `data/otel/logs-2026-10-25.jsonl`; a 20 MB POST gave 413 and wrote nothing; `--host 0.0.0.0` was refused. `ruff check .` passes.

## Gaps

- No wheel was built and installed; packaging checked by config only.
- No real Claude Code session was pointed at the receiver; the env vars come from the issue and were not re-checked against the docs.
