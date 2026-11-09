# Rust port plan

**Status:** approved — owner resolved the open questions 2026-11-09 · **Owner:** Minh Tran · **Updated:** 2026-11-09

## 1. Goal and scope

Rewrite the `tokscope` Python system (CLI, ingest, web dashboard, HTML report, benchmarks/replays/optimize,
OTel receiver) as a single Rust binary, and replace the Electron desktop shell with a Tauri app. The result is a
drop-in replacement: same `tokscope` command, same SQLite database, same on-disk formats, same Claude Code mod.

**In scope**

- The Python package `tokscope/` (~16.2k LOC) → one Rust workspace.
- The Electron desktop app `desktop/` → a Tauri app.
- The `setup.sh` installer and the `.deb` / macOS `.dmg` packaging.

**Out of scope (unchanged)**

- `mod/` — the Claude Code plugin. Claude Code loads only TypeScript/JavaScript plugins, so this stays TS. It already
  finds the CLI by `TOKSCOPE_CLI` → `PATH` → `~/.local/bin/tokscope`; as long as the binary is still named `tokscope`
  and keeps its stdout/stderr/exit-code contract, the mod works with no change.
- Feature behavior. This is a port, not a redesign. Every existing rule in `PRODUCT.md`, `DECISIONS.md` and the test
  suite carries over verbatim unless a decision below says otherwise.

## 2. Decisions

| Decision | Choice |
| --- | --- |
| Sequencing | **Big-bang**: build the whole system in one Rust tree, then cut over once. The Python tree and its tests stay in the repo as the reference oracle until the cut-over PR. |
| Desktop | **Tauri**, not Electron. |
| Compatibility | **Drop-in**: keep the exact SQLite schema, and every on-disk format (`marks/`, `reports/`, `bench/`, `data/skills/`, `privacy.key`, `pricing.json`, `budgets.json`, `data/otel/`). |
| Plan form | This document. |

These should be copied into `DECISIONS.md` as an ADR when the cut-over lands.

## 3. Current state

| Piece | Files | LOC | Notes |
| --- | --- | --- | --- |
| `tokscope/` (Python, stdlib only) | ~75 `.py` | 16,189 | `core/` (transcripts→SQLite), `features/`, `integrations/`, `experiments/`, `web/` (dashboard + report), `cli.py` |
| `tests/` | ~60 `.py` | 11,772 | unit + golden tests; the de-facto spec |
| Web strings (CSS/JS/HTML embedded in Python) | in `web/` | ~6,720 | theme/layout/styles/scripts + page builders |
| `mod/` | TS | — | stays |
| `desktop/` | Electron + JS | — | → Tauri |

Layering rule (enforced by `tests/test_layout.py`): `core` never imports the others; only `cli` and `web` import
`web`. The Rust workspace must preserve this.

### The hot paths (what a Rust port buys)

1. **Ingest parser** (`core/ingest.py`, `core/skills.py`) — reads every line of every transcript JSONL, decodes JSON,
   runs regexes over commands, SHA-hashes tool inputs, and writes to SQLite. This is the single biggest CPU cost and
   the clearest win: `serde_json` + the `regex` crate are typically 10–50× faster than `json`/`re` here, and Rust
   removes the per-object allocation overhead of the `SessionParser` dicts.
2. **OTel ingest + matching** (`core/otel.py`) — same JSON-line profile, plus a bucketed match.
3. **Dashboard server** (`web/dashboard/server.py`) — stdlib `ThreadingHTTPServer` with per-request connection open →
   an async `axum` server with a connection pool.
4. **Report generation** (`web/report/`) — large string building; faster but secondary (queries dominate).
5. **Startup** — `tokscope summary` / `statusline` / `session` pay a Python interpreter startup on every call; the
   statusline runs every turn, so a near-instant Rust binary is a real win for the Claude Code experience.

**Honest caveat:** single-user dashboard latency and report time are dominated by SQLite queries and data volume, not
by Python interpreter overhead. The measurable wins are ingest throughput, server concurrency, resident memory of the
long-running `serve` process, and cold-start latency. Targets are in §8.

## 4. Target architecture

One Cargo workspace at the **repo root** (owner decision, §13), two library crates plus the desktop app:

```
<repo root>/
├─ Cargo.toml                 workspace
├─ rust-toolchain.toml        pinned toolchain
├─ crates/
│  ├─ tokscope-core/          the `core/` layer, no subprocess or network
│  │  └─ src/{paths,schema,ingest,skills,otel,pricing,privacy,tz,summary,
│  │         budgets,cache,calls,context,errors,markdown}.rs
│  └─ tokscope/               the binary: cli + features + integrations + experiments + web
│     └─ src/
│        ├─ main.rs, cli/
│        ├─ features/{changes,library,live,patterns,postship,projects,service}.rs
│        ├─ integrations/{managed,registry,otel_receiver}.rs
│        ├─ experiments/{bench,replay,optimize,skillopt/}.rs
│        └─ web/{dashboard,report,theme}/…
├─ desktop/                   Tauri app (replaces Electron desktop/)
├─ mod/                       unchanged (TypeScript)
└─ tokscope/, bin/, tests/    the Python tree, kept as the oracle until M7
```

The `core`/`web` split enforces the existing layering rule with the compiler (`tokscope-core` has no dependency on the
web crate), so `tests/test_layout.py` becomes a non-issue.

### Tech stack

| Concern | Crate | Replaces | Notes |
| --- | --- | --- | --- |
| CLI | `clap` (derive) | `argparse` | reproduce exact flags, `--help` text, and exit codes 0/1/2/10/11/30 |
| SQLite | `rusqlite` (`bundled`) | stdlib `sqlite3` | bundled SQLite = no system dep, matches "no deps" ethos; WAL + `busy_timeout` + `synchronous=NORMAL` as today |
| SQL scalar fns | `rusqlite` `functions` feature | `create_function` | port `localday` (tz), `tk_name`/`tk_text`/`tk_project`/`tk_cwd` (privacy) |
| Backup (redacted copy) | `rusqlite` `backup` feature | `sqlite3.backup` | `privacy.redacted_copy` |
| JSON | `serde` + `serde_json` | stdlib `json` | big ingest/otel win; see §6 for serialization-exactness rules |
| Regex | `regex` | stdlib `re` | linear-time, no catastrophic backtracking; re-express each `re.compile` |
| Hashing | `sha1`, `sha2`, `hmac` (RustCrypto) | `hashlib`/`hmac` | `sha2` confirmed (no `blake3`); must match Python byte-for-byte, see §6 |
| Time | `chrono` + `chrono-tz` | `zoneinfo` | `local_day`, `midnight`, `utc_bound`; DST handled by `chrono-tz` |
| HTTP server | `axum` (tokio) | `http.server` | async; **single writer + an `r2d2_sqlite` reader pool** (owner decision, §13), SQLite calls via `spawn_blocking` |
| HTTP client | `ureq` | `urllib` | MCP Registry search; blocking, minimal |
| gzip | `flate2` | `gzip` | OTel receiver decompress |
| Subprocess | `std::process::Command` | `subprocess` | `claude`, `git`, `ant`, `xcode-select` |
| File walking | `walkdir` | `rglob` | transcript discovery, skill folder hashing |
| Errors | `thiserror` (lib) + `anyhow` (bin) | exceptions | map `BudgetError`/`Refused`/`ValueError` to exit codes |
| Logging | `tracing` + `tracing-subscriber` | `print`/`log=` | keep the current quiet-by-default output contract |
| Desktop | Tauri 2.x | Electron | §11 |

The web layer (report + dashboard HTML/CSS/JS) is currently giant Python f-strings and string-building functions. Port
those **as Rust string constants and `format!`/`write!` builders**, not via a template engine. The CSS/JS are already
isolated constants (`theme/layout.py`, `styles.py`, `scripts.py`); moving them to `include_str!`/`const &str` is
mechanical and avoids restructuring 6.7k LOC of markup. A template engine is a possible later cleanup, not part of the
port.

## 5. Module mapping

| Python | Rust |
| --- | --- |
| `cli.py` | `tokscope/src/main.rs` + `tokscope/src/cli/*.rs` |
| `paths.py` | `tokscope-core/src/paths.rs` |
| `core/ingest.py` | `tokscope-core/src/ingest.rs` (+ `schema.rs`, `parser.rs`, `store.rs`) |
| `core/skills.py` | `tokscope-core/src/skills.rs` |
| `core/otel.py` | `tokscope-core/src/otel.rs` |
| `core/pricing.py` | `tokscope-core/src/pricing.rs` |
| `core/privacy.py` | `tokscope-core/src/privacy.rs` |
| `core/tz.py` | `tokscope-core/src/tz.rs` |
| `core/summary.py`, `errors.py` | `tokscope-core/src/summary.rs`, `errors.rs` |
| `core/budgets.py`, `cache.py`, `calls.py`, `context.py`, `markdown.py` | same-named `tokscope-core` modules |
| `features/{changes,library,live,patterns,postship,projects,service}.py` | `tokscope/src/features/*` |
| `integrations/{managed,registry,otel_receiver}.py` | `tokscope/src/integrations/*` |
| `experiments/{bench,replay,optimize,skillopt/*}.py` | `tokscope/src/experiments/*` |
| `web/theme/*`, `web/report/*`, `web/dashboard/*` | `tokscope/src/web/*` |
| `tests/` | `tests/` (Rust) + golden fixtures, §9 |
| `desktop/` | `desktop/` (Tauri), §11 |

## 6. Drop-in compatibility contract

This is the make-or-break section for a big-bang port. Split into "must match byte-for-byte", "must match
semantically", and "needs only internal determinism".

### 6.1 Must match byte-for-byte (persisted or compared against stored values)

| Value | Where | Algorithm to reproduce exactly |
| --- | --- | --- |
| Skill version | `skill_versions.version`, `skills.fingerprint` | first 12 hex of SHA-256 over every *sorted* file's `relative_path.as_posix() + "\0" + bytes + "\0"`, where text files (no NUL in first 8 KiB) have CRLF→LF; skip hidden/`__pycache__`/`node_modules`/`.pyc` at any depth, and `eval|evals|tests|test|fixtures|results` only as a top-level folder; skip files > 1 MB. |
| `body_hash` | `skill_versions.body_hash` | SHA-256 of SKILL.md body (frontmatter block dropped, then `.strip()`), first 12 hex. |
| `text_hash` | `skill_calls.text_hash` | space-joined `sha256[:12]` hashes from `loaded_text_hash` (body, then each `$ARGUMENTS` placeholder form). Must port `_placeholder_forms` and the `\n\n\nARGUMENTS: ` split exactly. |
| Privacy alias | `numbers`-level reports | `hmac_sha256(key = privacy.key bytes, msg = "{kind}\0{value}")` hex, first 6 chars, prefixed `"{kind}-"`. Same `BUILTIN_AGENTS`/`BUILTIN_TOOLS`/phase/`mcp__` special cases as `privacy.name`. |
| Session signature | `sessions.signature` | `f"v{PARSER_VERSION}:{n_files}:{sum_sizes}:{max_mtime_ns}"` — the approved bump in §6.4 (24 → 25) re-parses every session once at cut-over. |

Getting any of the first three wrong silently forks the skill-version system: a Rust build would treat every existing
skill as "changed", duplicate version rows, and break `optimize`/`bench` pinning and the report's versions card. These
are the highest-risk items and get dedicated golden tests (§9).

### 6.2 Must match semantically (compared by consumers, not by hash)

- **JSON output shapes**: `summary`, `session --json`, `patterns`, `skills`, `/api/*`, `check --json`. Same field names,
  order, number formatting (`round(x, 2)`, `round(x, 6)`), and `None`-vs-omitted handling. `serde_json` with
  `preserve_order` (or structs with fixed field order) reproduces Python's insertion order.
- **CSV output**: same columns, same `safe_cell` quoting, `lineterminator="\n"`.
- **stdout/stderr contract**: with `--format json|csv` stdout holds only the rows and notes go to stderr; table mode
  prints notes to stdout. The mod and downstream scripts rely on this.
- **Exit codes**: `0` ok, `1` failed/INVALID, `2` load/lock/bad-file, `10` near, `11` over, `30` no data (budgets).
- **`local_day`**: same local-day bucketing, including DST edges. `chrono-tz` matches `zoneinfo` for IANA names.
- **HTML report/dashboard**: byte-identical is unrealistic (timestamps, data counts) — target *structural* identity via
  golden-file diffs with dynamic values normalized (§9).

### 6.3 Needs only internal determinism

- **`_input_hash`** (SHA-1 of `json.dumps(inp, sort_keys=True, default=str)`): only sets `tool_calls.repeat` within a
  parse run; it is not persisted as a hash. Rust just needs a deterministic, sorted-key serialization of the parsed
  input. No cross-version match required.
- **pricing fingerprint** (SHA-1): stored in `meta.pricing`; a mismatch only triggers a one-off cost refresh, then the
  Rust value is stored consistently. Low risk — but reproduce the same serialization anyway to avoid a spurious refresh.

### 6.4 Schema

Keep `SCHEMA` in `core/ingest.py` and the migration path in `connect()` verbatim: same table names, columns, primary
keys, indexes, and `ALTER TABLE` back-fills. **Owner decision: bump `PARSER_VERSION` 24 → 25 at cut-over**, so every
transcript is re-parsed once. This is deliberate — it catches any ingest bug the port introduced on real data instead
of leaving stale Python-parsed rows in place — and it is the *only* reason an existing install re-ingests. The schema
stays byte-compatible otherwise. Record the bump in the cut-over `DECISIONS.md` entry.

### 6.5 On-disk formats (unchanged)

`marks/marks-YYYY-MM-DD.jsonl` (append, one JSON object per line), `reports/report[-level].html`, `bench/` task JSON
and run folders, `data/skills/<skill>/<version>/` snapshots, `data/otel/<signal>-YYYY-MM-DD.jsonl`, `privacy.key`
(mode 0600), `pricing.json`, `budgets.json`, `projects.json`, `library.json`. Rust must read and write all of them in
place; `paths.rs` reimplements `paths.home()` including the `TOKSCOPE_HOME` → repo-clone → `XDG_DATA_HOME` → `.local/share` →
macOS Application Support precedence, and the `TOKSCOPE_DATA_DIR` / `CLAUDE_CONFIG_DIR` handling.

## 7. What stays the same, by construction

- The SQLite schema and the multi-process safety model (WAL, `busy_timeout=10s`) — several processes (CLI, `serve`,
  the mod's `mark`/`statusline`, the SessionEnd hook) write the DB concurrently.
- The loopback-only, Host/Origin/token-checked dashboard security model (`server.py`).
- The privacy architecture: build reports from a redacted in-memory copy, never from the live DB.

## 8. Performance targets and measurement

Baseline first, then measure against the same corpus. The repo already has `bench/` and a `data/` sample.

**Measured baseline** (2026-11-09, this machine: 98 MB `tokscope.db`, 676 transcripts in `~/.claude/projects`):

| Metric | Baseline (Python) | Target (Rust) | How to measure |
| --- | --- | --- | --- |
| `ingest`, incremental (4 changed / 672 unchanged) | 0.94 s, ~29 MB | ≤0.3 s, less memory | `time tokscope ingest` on this corpus |
| `summary --by phase`, cold / warm | 0.50 s / 0.15 s, ~25 MB | <10 ms warm | `hyperfine 'tokscope summary --by phase'` |
| `statusline` (runs every turn) | 0.08 s, ~21 MB | near-instant | `hyperfine` |
| `serve` resident memory (warm) | TBD — capture before cut-over | meaningfully lower | `ps`/`/proc` after warm ingest |
| `report --privacy redacted` | **5.44 s, ~275 MB** | ≥2× faster, less memory | `time tokscope report --privacy redacted` |

**Finding — the redacted report is the worst path.** `privacy.redacted_copy` copies the entire 98 MB DB into `:memory:`
(`sqlite3.backup`) before redacting, hence 275 MB RSS and 5.4 s. This is backup + SQL bound, not Python bound, so Rust
alone will not fix it; the port should optimize the approach itself — back up to a temp file on disk instead of
`:memory:`, or redact during the copy (per-table `INSERT … SELECT` with the `tk_*` transforms applied) so the full DB
is never resident twice. Same result, lower peak memory.

Add a `Makefile` target (`make bench-port`) that runs the same benchmark against the Python and Rust binaries and
prints the table, so regressions are caught in the cut-over PR. Capture the Python baseline **before** starting.

## 9. Build plan (milestones, one cut-over at the end)

Big-bang means one release; the milestones are the internal build order. The Python tree and its test suite remain the
oracle (and keep passing in CI) until M6.

### M0 — Workspace, fixtures, and the parity harness

- Scaffold the repo-root Cargo workspace (`tokscope-core`, `tokscope`, `desktop/` stub, `rust-toolchain.toml`).
- Extract the existing `tests/` fixture transcripts and any stored expected DBs into a shared `tests/fixtures/` that
  both languages read.
- Build the **differential harness**: run `python tokscope …` and `rust tokscope …` on the same fixtures (and a real,
  redacted `~/.claude/projects` sample) and diff the resulting SQLite rows and stdout. This is the backbone of every
  later milestone.

**Done when:** `cargo test` runs; the harness can diff one `summary` output end-to-end.

### M1 — `core`, the compatibility-critical layer

- `paths.rs`, `schema.rs`, `tz.rs` (`localday` SQL function), `pricing.rs`, `privacy.rs`, `summary.rs`, `errors.rs`,
  `ingest.rs`/`parser.rs`/`store.rs`, `skills.rs`, `otel.rs`, `budgets.rs`, `cache.rs`, `calls.rs`, `context.rs`,
  `markdown.rs`.
- Port every hash/serialization in §6.1 exactly, with golden tests against values computed by the Python version.

**Done when:** `rust tokscope ingest` + `summary` + `session` reproduce the Python output on all fixtures; a
byte-level DB diff of `requests`, `sessions`, `skill_calls`, `skill_versions`, `tool_calls`, `otel_requests` is empty.

### M2 — CLI surface and the read-only commands

- `clap` subcommands for `ingest`, `summary`, `session`, `skills`, `patterns`, `change`, `check`, `statusline`,
  `mark`, `report`, `open`, `serve`, `service`, `otel-receiver`, `bench`, `replay`, `optimize`.
- Exact flags, `--help`, stdout/stderr split, exit codes.
- Read-only commands (`summary`, `session`, `patterns`, `skills`, `check`, `statusline`) fully working.

**Done when:** the `--format json|csv` outputs and exit codes match Python for the read-only set.

### M3 — Web: report generator

- Port `web/theme/*` (CSS/JS as `const`/`include_str!`), `web/report/*` section builders, `writer.rs`.
- Privacy levels `full`/`redacted`/`numbers` via the redacted-copy path from M1.

**Done when:** golden HTML diffs (with timestamps/counts normalized) match the Python report across fixtures and all
three privacy levels.

### M4 — Web: dashboard server + OTel receiver + integrations

- `axum` server porting `server.py` routes (`/api/*`, pages, POST writes with Host/Origin/token checks, `/api/version`,
  `/api/live`, fonts, favicon), the background ingest thread, and `QuietServer`'s broken-pipe silence.
- `integrations/otel_receiver.rs` (OTLP/HTTP JSON, gzip, chunked, size caps, `--allow-remote`, 0700/0600 permissions).
- `integrations/{managed,registry}.rs` (`ant` CLI, MCP Registry search).

**Done when:** `rust tokscope serve` renders every page and answers every `/api` route identically; the OTel receiver
accepts a captured export and writes the same JSONL.

### M5 — Experiments (paid `claude -p` paths)

- `experiments/{bench,replay,optimize,skillopt/*}.rs` (suite load/grade, sandbox, loop, apply, store, stats).
- These spawn real `claude -p` sessions; gate manual runs behind the same `--runs`/`--budget` cautions and test against
  dry-run/sandbox paths.

**Done when:** `bench prepare/run/diff/regrade`, `replay plan/run/diff`, `optimize case/suite/run/approve/reject/revert`
behave identically (verified with fixture and sandbox runs, and one owner-approved paid smoke run each).

### M6 — Desktop (Tauri) + installer + packaging

- §11.
- Update `setup.sh` (build via cargo, link `target/release/tokscope`), `Makefile`, and `.deb`/`.dmg` builds.

**Done when:** `make deb` / `npm`-free desktop build produces installable artifacts; the window, service
(systemd/launchd), and menu items behave as today.

### M7 — Cut-over

- One PR that replaces `bin/tokscope`/`tokscope/` with the Rust binary and removes the Python package, keeping
  `mod/` untouched.
- Add the ADR to `DECISIONS.md`, update `README.md`/`PRODUCT.md` (Python requirements → Rust toolchain), `STATUS.md`.
- Run the full benchmark table (§8) and the differential harness one final time.

**Done when:** `./setup.sh && tokscope --version && tokscope open` works on a fresh Linux and macOS machine against an
existing data dir with no re-ingest, and the mod's `/tokscope` + statusline work unchanged.

## 10. Testing and parity strategy

1. **Port the Python test suite** to Rust `#[test]`s. The 11.8k LOC of tests are the specification — attribution rules,
   fork dedupe (issue #46), failed-load semantics, OTel matching, privacy aliasing, budget exit codes. Translate
   faithfully; do not "simplify" tests away.
2. **Golden files** for hash-sensitive values: precompute the §6.1 hashes and JSON/CSV outputs with the Python version,
   commit them, assert Rust reproduces them.
3. **Differential harness** (M0) runs both binaries on the same corpus and diffs DB + stdout; the strongest guard
   against behavioral drift, kept green through cut-over.
4. **HTML golden diffs** for report/dashboard, with dynamic values (timestamps, `data-ts`, counts) normalized out.
5. **Property/invariant tests** for the parser: half-written lines, malformed JSON, CRLF, resumed parse (`ingest_state`),
   fork copies, background task notifications — the lenient-parsing cases the Python code deliberately tolerates.
6. **CI**: keep the Python tests running until M7; add `cargo test`, `cargo clippy`, and the differential harness as
   the Rust gates. `tests/test_version.py`'s three-places version agreement becomes `version` in the workspace
   `Cargo.toml` ↔ `mod/.claude-plugin/plugin.json` ↔ `CHANGELOG.md`.

## 11. Desktop: Electron → Tauri

The Electron app is a thin window around the local dashboard, plus service management. Tauri is a clean fit.

- **Window**: Tauri `WebviewWindow` loads `http://127.0.0.1:<port>` (the same loopback-only URL), preserving the
  current "window around the dashboard" design and the link/redirect restrictions.
- **Server lifecycle**: mirror `desktop/server-command.js` — spawn the `tokscope serve` binary as a child and stop it
  when the process exits; use the systemd/launchd user service on port 8770 when present, else a free port.
  (In-process `serve` via the `tokscope-core` library is a later optimization, not needed for parity.)
- **Service management** (`desktop/autostart.js`, `service.py`, `mac-integration.js`): port to the Tauri Rust backend —
  write/read the systemd unit and launchd agent, `service status`, "Start at login" checkbox, "Install command line
  tool" (writes the `~/.local/bin/tokscope` wrapper), and the About panel.
- **Packaging**: Tauri bundler produces the `.deb` (Linux) and `.app`/`.dmg` (macOS, unsigned personal build as today).
  The macOS build **no longer bundles Python** — that whole `scripts/fetch-python.sh` / `PYTHONPATH` /
  `python-build-standalone` machinery disappears, which is a notable simplification.
- Keep `desktop/package.json` version in step with the workspace version (same `tests/test_version.py` contract).

## 12. Risks and mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Hash mismatch (§6.1) forks skill versions | High — silent data divergence | Dedicated golden tests + differential DB diff before any milestone is "done" |
| `json.dumps` separators/defaults differ | Medium — wrong `otel` dedupe, spurious cost refresh | Reproduce Python's exact separators (`", "`/`": "`); serialize via sorted-key maps |
| Timezone/DST edge cases | Medium — wrong day buckets | `chrono-tz`; port `tests/test_tz.py` cases verbatim |
| Web layer drift (6.7k LOC strings) | Medium — subtle UI regressions | Structural golden HTML diffs; screenshot UAT per `CLAUDE.md` before cut-over |
| Lenient transcript parsing | Medium — crashes where Python tolerated junk | Port the `json.JSONDecodeError`/`except` skip paths; invariant tests on malformed lines |
| Big-bang: long period with no shippable state | High — schedule risk | Milestones M0–M6 each end in a green, diffed increment; cut-over is the only user-visible change |
| Tauri packaging/signing story | Medium | Personal, unsigned builds as today; document `cargo-tauri` build on the Mac |
| Existing-data upgrade surprises | Medium | §6.4 approved `PARSER_VERSION` bump forces one re-parse; pre-cut-over dry run against a copy of a real data dir, then compare row counts and totals |

## 13. Resolved decisions (owner, 2026-11-09)

| # | Question | Decision |
| --- | --- | --- |
| 1 | Workspace location | **Repo root** — `Cargo.toml` + `rust-toolchain.toml` at the root, `crates/…` beside the Python tree until M7. |
| 2 | `serve` concurrency model | **Single writer + an `r2d2_sqlite` reader pool** (the recommendation). |
| 3 | Skill folder hash crate | **`sha2`** — keep matching today; no `blake3`. |
| 4 | `PARSER_VERSION` bump | **Approved** — bump 24 → 25 at cut-over to force one full re-parse on real data. |
| 5 | Timeline / ownership | **ASAP.** Ownership of M0–M7 is the owner's unless delegated. |

With these settled there are no blocking questions; M0 can start.
