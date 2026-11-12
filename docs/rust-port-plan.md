# Rust port plan

**Status:** approved 2026-11-09; checked against the code 2026-11-12, which found corrections and four new open
questions (§14) · **Owner:** Minh Tran · **Updated:** 2026-11-12

## 1. Goal and scope

Rewrite the `tokscope` Python system (CLI, ingest, web dashboard, HTML report, benchmarks/replays/optimize,
OTel receiver) as a single Rust binary, and replace the Electron desktop shell with a Tauri app. The result is a
drop-in replacement: same `tokscope` command, same SQLite database, same on-disk formats, same Claude Code mod.

**In scope**

- The Python package `tokscope/` (~16.2k LOC) → one Rust workspace, with the bundled assets (`assets/phases.json`,
  `assets/fonts/*.woff2`) compiled into the binary.
- The Electron desktop app `desktop/` → a Tauri app.
- The `setup.sh` installer and the `.deb` / macOS `.dmg` packaging.
- The CI workflow (`.github/workflows/ci.yml`: unit tests on Python 3.10–3.13, `ruff`, the wheel `package` job).

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

These are recorded in `DECISIONS.md` (2026-11-09). The cut-over PR adds a second, short entry: the date, the
`PARSER_VERSION` bump and anything that changed on the way.

## 3. Current state

| Piece | Files | LOC | Notes |
| --- | --- | --- | --- |
| `tokscope/` (Python, stdlib only) | 81 `.py` | 16,221 | `core/` (transcripts→SQLite), `features/`, `integrations/`, `experiments/`, `web/` (dashboard + report), `cli.py` |
| `tests/` | 45 `.py` | 11,808 | unit + golden tests; the de-facto spec |
| Web strings (CSS/JS/HTML embedded in Python) | in `web/` | 6,749 | theme/layout/styles/scripts + page builders |
| `mod/` | TS | — | stays |
| `desktop/` | Electron + JS | 464 (JS) | → Tauri |

Counted on `main` on 2026-11-12 (`find … -name '*.py' \| xargs cat \| wc -l`). Size by area, which is the best
available measure of the work per milestone:

| Area | LOC | Milestone |
| --- | --- | --- |
| `core/` + `paths.py` | 3,542 | M1 |
| `cli.py` | 712 | M2 |
| `features/` | 1,339 | M2 (read-only parts), M4 (`live`, `service`) |
| `web/` (`theme` 1,219 · `report` 1,503 · `dashboard` 3,788 · `charts.py` 238) | 6,749 | M3, M4 |
| `integrations/` | 497 | M4 |
| `experiments/` | 3,378 | M5 |
| `tests/` | 11,808 | ported with the code each one covers |

**The Python tree is a moving target.** Between 2026-11-09 and 2026-11-12, `main` changed 25 files under `tokscope/`,
bumped `PARSER_VERSION` to 25 and merged step 1 of the Indigo redesign (#257; steps 2–5 are not started). Every change
that lands in Python after the port starts must be ported too. See the freeze rule in §9 and question 8 in §14.

Layering rule (enforced by `tests/test_layout.py`): `core` never imports the others; only `cli` and `web` import
`web`. The Rust workspace must preserve this (§4 says how far the compiler does it).

### The hot paths (what a Rust port buys)

1. **Ingest parser** (`core/ingest.py`, `core/skills.py`) — reads every line of every transcript JSONL, decodes JSON,
   runs regexes over commands, SHA-hashes tool inputs, and writes to SQLite. This is the single biggest CPU cost and
   the clearest win: `serde_json` + the `regex` crate are usually much faster than `json`/`re` here, and Rust
   removes the per-object allocation overhead of the `SessionParser` dicts. How much faster is not measured yet: the
   baseline in §8 has no full-ingest number, and three of the ingest patterns cannot use the `regex` crate (§4).
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
│  │         budgets,cache,calls,context,errors,markdown,baseline}.rs
│  │     assets/{phases.json,fonts/*.woff2}   embedded with include_str!/include_bytes!
│  └─ tokscope/               the binary: cli + features + integrations + experiments + web
│     └─ src/
│        ├─ main.rs, cli/
│        ├─ features/{changes,library,live,patterns,postship,projects,service}.rs
│        ├─ integrations/{managed,registry,otel_receiver}.rs
│        ├─ experiments/{bench,replay,optimize,skillopt/}.rs
│        └─ web/{dashboard,report,theme}/…, web/charts.rs
├─ desktop/                   Tauri app (replaces Electron desktop/)
├─ mod/                       unchanged (TypeScript)
└─ tokscope/, bin/, tests/    the Python tree, kept as the oracle until M7
```

The crate split enforces half of the layering rule with the compiler: `tokscope-core` cannot import anything else.
The other half ("only `cli` and `web` import `web`") is **not** enforced, because `features`, `integrations`,
`experiments` and `web` are modules of one crate and can import each other freely. Keep that half as a test: port
`tests/test_layout.py` to a Rust test that greps `use crate::web` outside `cli/` and `web/`. (A third crate for `web`
would enforce it with the compiler, at the price of more workspace plumbing.)

### Tech stack

| Concern | Crate | Replaces | Notes |
| --- | --- | --- | --- |
| CLI | `clap` (derive) | `argparse` | reproduce exact flags, `--help` text, and exit codes 0/1/2/10/11/30 |
| SQLite | `rusqlite` (`bundled`) | stdlib `sqlite3` | bundled SQLite = no system dep, matches "no deps" ethos; WAL + `busy_timeout=10000` + `synchronous=NORMAL` as today (`core/ingest.py` `connect()`). Python's `sqlite3` opens transactions implicitly before writes; `rusqlite` does not, so wrap each ingest batch in an explicit transaction or ingest gets slower, not faster. |
| SQL scalar fns | `rusqlite` `functions` feature | `create_function` | port `localday` (tz), `tk_name`/`tk_text`/`tk_project`/`tk_cwd` (privacy) |
| Backup (redacted copy) | `rusqlite` `backup` feature | `sqlite3.backup` | `privacy.redacted_copy` |
| JSON | `serde` + `serde_json` | stdlib `json` | big ingest/otel win; see §6 for serialization-exactness rules |
| Regex | `regex`, plus `fancy-regex` where needed | stdlib `re` | The `regex` crate has **no look-around and no backreferences**. The Python code uses them in 17 patterns: `HEADLESS_RE`, `HEREDOC_RE` (`\2`, `\3`), `TASK_DONE_RE` and one `re.sub` in `core/ingest.py`; `RULE`, `BOLD`, `ITALIC` in `core/markdown.py`; 10 secret patterns in `features/patterns.py`. Use `fancy-regex` (backtracking, supports both) for those, or rewrite each by hand, and keep `regex` for the rest (73 `re.*` call sites in total). Also check per pattern: `re.match` anchors at the start, `re.S`/`re.M`/`re.I` flags, and `\w`/`\d`/`\s` are Unicode in both. |
| Hashing | `sha1`, `sha2`, `hmac` (RustCrypto) | `hashlib`/`hmac` | `sha2` confirmed (no `blake3`); must match Python byte-for-byte, see §6 |
| Time | `chrono` (`Local`) + `chrono-tz` | `zoneinfo`, `astimezone()` | `local_day`, `midnight`, `utc_bound`. Two cases, as in `core/tz.py`: with no `TOKSCOPE_TZ`/`--timezone` the **system zone** is used (`chrono::Local`, which reads `/etc/localtime`), not an IANA name; a named zone uses `chrono-tz`. `chrono-tz` ships its own tz database and `zoneinfo` reads the system's, so the two can differ after a recent rule change; accept that and say so in the cut-over notes. Keep the per-minute cache of `_day_of_minute`: the SQL function runs once per request row. |
| Shell split | `shlex` | `shlex.split` | used by `_placeholder_forms` (§6.1); check its quoting rules against Python's on the golden cases |
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
| `core/budgets.py`, `baseline.py`, `cache.py`, `calls.py`, `context.py`, `markdown.py` | same-named `tokscope-core` modules |
| `assets/phases.json`, `assets/fonts/*.woff2` (6 files) | embedded in `tokscope-core` / the binary; a `phases.json` in the data home still overrides the built-in one |
| `features/{changes,library,live,patterns,postship,projects,service}.py` | `tokscope/src/features/*` |
| `integrations/{managed,registry,otel_receiver}.py` | `tokscope/src/integrations/*` |
| `experiments/{bench,replay,optimize}.py`, `skillopt/{apply,grade,loop,sandbox,stats,store,suite,suite_gen,trigger}.py` | `tokscope/src/experiments/*` |
| `web/theme/{brand,fonts,layout}.py`, `web/charts.py`, `web/report/*` | `tokscope/src/web/*` |
| `web/dashboard/{server,shell,scripts,common}.py` and `pages/` (10 page modules: overview, breakdowns, sessions, projects, library, optimize, benchmarks, managed, settings, `_flat`) | `tokscope/src/web/dashboard/*`, one module per page as today |
| `tests/` | `tests/` (Rust) + golden fixtures, §9 |
| `desktop/` | `desktop/` (Tauri), §11 |

## 6. Drop-in compatibility contract

This is the make-or-break section for a big-bang port. Split into "must match byte-for-byte", "must match
semantically", and "needs only internal determinism".

### 6.1 Must match byte-for-byte (persisted or compared against stored values)

| Value | Where | Algorithm to reproduce exactly |
| --- | --- | --- |
| Skill version | `skill_versions.version`, `skills.fingerprint` | first 12 hex of SHA-256 over every *sorted* file's `relative_path.as_posix() + "\0" + bytes + "\0"`, where text files (no NUL in the first 8,192 bytes) have CRLF→LF; skip any path with a part that starts with `.`, is `__pycache__` or `node_modules`, or ends with `.pyc`; skip `eval|evals|tests|test|fixtures|results` only as the first folder under the skill; skip files over **1,000,000 bytes** (`MAX_BYTES`, not 1 MiB; a file of exactly 1,000,000 bytes is kept). `None` when there is no `SKILL.md`. See the three traps below. |
| `body_hash` | `skill_versions.body_hash` | SHA-256 of SKILL.md body (frontmatter block dropped, then `.strip()`), first 12 hex. The file is read with `read_text(errors="replace")`. |
| `text_hash` | `skill_calls.text_hash` | space-joined `sha256[:12]` hashes from `loaded_text_hash` (body, then each `$ARGUMENTS` placeholder form). Must port `_placeholder_forms` and the `\n\n\nARGUMENTS: ` split exactly. |
| Privacy alias | `numbers`-level reports | `hmac_sha256(key = privacy.key bytes, msg = "{kind}\0{value}")` hex, first 6 chars, prefixed `"{kind}-"`. Same `BUILTIN_AGENTS`/`BUILTIN_TOOLS`/phase/`mcp__` special cases as `privacy.name`. |
| Session signature | `sessions.signature` | `f"v{PARSER_VERSION}:{n_files}:{sum_sizes}:{max_mtime_ns}"` — the approved bump in §6.4 re-parses every session once at cut-over. |
| OTel dedupe key | `otel_requests.dedupe` (unique index `idx_otel_dedupe`) | SHA-1 hex (all 40 chars) of `json.dumps(ev, separators=(",", ":"))`, where `ev` is the 11-value list (session id, prompt id, ts, model, four integers, cost, duration, speed). **Not covered by the parser bump**: OTel rows are not rebuilt from transcripts. A different key means a re-sent export, or a file that is read again after it was replaced, is stored twice. Reproduce `json.dumps` exactly: compact separators, `null` for `None`, non-ASCII escaped as `\uXXXX` (`ensure_ascii`), and floats in Python `repr` form (cost and duration are floats or `null`: `12.0`, `0.0125`, `1.2e-05`; `serde_json` prints the last one differently). Write a small formatter for this one list; do not rely on `serde_json` output. |

**Three traps in the skill version and the body hashes** (each one changes a hash only for some skills, so a small
fixture set will not catch it; put one golden case per trap in §10):

1. *Sort order.* `_files` sorts `Path` objects, and Python compares paths part by part, not as one string. `a/b.md`
   sorts before `a-b.md` in Python (`"a" < "a-b"`), but after it as a plain string (`-` is 0x2D, `/` is 0x2F). In Rust,
   sort by the vector of path components.
2. *Text semantics.* `str.strip()` and `str.splitlines()` are wider than Rust's `trim()` and `lines()`: Python also
   strips `\x1c`–`\x1f`, and also splits lines at `\x0b`, `\x0c`, `\x1c`–`\x1e`, `\x85`, U+2028 and U+2029. Port both as
   small helpers with Python's character sets. `errors="replace"` and `String::from_utf8_lossy` can produce a different
   number of U+FFFD for the same invalid bytes; test one invalid-UTF-8 SKILL.md and match Python.
3. *Symlinks.* `rglob` + `is_file()` hashes the target of a file symlink. Whether `rglob` walks into a symlinked
   folder was not checked in this review and may differ between Python versions; test it on 3.10 and 3.13, then set
   `walkdir`'s `follow_links` to match.

`_placeholder_forms` also needs care: it works on code points (private-use characters from U+E000 as markers), tries
every subset of up to 6 argument positions, and uses `shlex.split`.

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
- **`local_day`**: same local-day bucketing, including DST edges, for both the system zone and a named zone (§4).
- **Redacted text labels**: `tk_text` writes `[label · N chars]` where N is `len(value)`, a count of code points. Use
  `.chars().count()`, not `.len()` (bytes), or every non-ASCII prompt gets a different number.
- **Numbers**: Python `round(x, 2)` rounds half to even on the binary value and prints the shortest form. Write one
  `round_py` helper and one float printer and use them everywhere; do not mix `format!("{:.2}")` in.
- **Stored costs**: `requests.cost_usd` is a float. A different order of additions changes the last bits, so the
  "byte-level DB diff" of M1 needs either the same operation order as `pricing.py` or a tolerance of 1e-9 on `REAL`
  columns. Decide in M0 and write it in the harness.
- **HTML report/dashboard**: byte-identical is unrealistic (timestamps, data counts) — target *structural* identity via
  golden-file diffs with dynamic values normalized (§9).

### 6.3 Needs only internal determinism

- **`_input_hash`** (SHA-1 of `json.dumps(inp, sort_keys=True, default=str)`, first 12 hex): sets
  `tool_calls.repeat`. It **is** persisted, inside the resume state: `seen_calls` is one of `STATE_KEYS`, stored as JSON
  in `ingest_state.state`. No cross-version match is required only because the state carries `"v": PARSER_VERSION` and
  the cut-over bump (§6.4) throws every old state away. So this item depends on the bump: without it, a session resumed
  by the Rust binary would miss repeats of calls the Python binary saw. The same holds for the whole `ingest_state`
  JSON: after the bump its layout is Rust's own business.
- **pricing fingerprint** (SHA-1 of `json.dumps([...], sort_keys=True)`, default separators `", "` and `": "`): stored
  in `meta.pricing`; a mismatch only triggers a one-off cost refresh, then the Rust value is stored consistently. Low
  risk, and the cut-over re-parse recomputes costs anyway, so an exact match is optional.

### 6.4 Schema

Keep `SCHEMA` in `core/ingest.py` and the migration path in `connect()` verbatim: same table names, columns, primary
keys, indexes, and `ALTER TABLE` back-fills. **Owner decision: bump `PARSER_VERSION` by one at cut-over**, so every
transcript is re-parsed once. (The decision said 24 → 25, but `main` reached 25 on 2026-11-12 for an unrelated parser
fix. The number is whatever `main` has at cut-over, plus one. Until then the Rust parser carries the **same** number
as Python, so the differential harness can compare `sessions.signature`.) This is deliberate — it catches any ingest bug the port introduced on real data instead
of leaving stale Python-parsed rows in place — and it is the *only* reason an existing install re-ingests. The schema
stays byte-compatible otherwise. Record the bump in the cut-over `DECISIONS.md` entry.

### 6.5 On-disk formats (unchanged)

`marks/marks-YYYY-MM-DD.jsonl` (append, one JSON object per line), `reports/report[-level].html`, `bench/` task JSON
and run folders, `data/skills/<skill>/<version>/` snapshots, `data/otel/<signal>-YYYY-MM-DD.jsonl`, `privacy.key`
(mode 0600), `pricing.json`, `budgets.json`, `projects.json`, `library.json`. Rust must read and write all of them in
place; `paths.rs` reimplements `paths.home()` including the `TOKSCOPE_HOME` → repo-clone → `XDG_DATA_HOME` → `.local/share` →
macOS Application Support precedence, and the `TOKSCOPE_DATA_DIR` / `CLAUDE_CONFIG_DIR` handling (a comma-separated list;
without it every existing `~/.config/claude/projects` and `~/.claude/projects`). Also port `paths.tool()`: the extra
tool folders, `claude` looked up in `~/.local/bin` first, and the macOS `git` stub check with `xcode-select -p`.

**Gap: the repo-clone rule cannot be ported as it is.** Python decides "I run from a clone" when `pyproject.toml` and
`bin/tokscope` exist next to the source file, and then keeps all data in the clone (`data/`, `reports/`, `bench/`). This
is the normal install (`./setup.sh`). A compiled binary has no source file, and M7 deletes both marker files. With no
new rule, the Rust binary of a clone install looks in `~/.local/share/tokscope`, finds nothing and shows an empty
dashboard: the data is not lost, but the upgrade is not drop-in. Proposed rule (question 6 in §14): resolve
`current_exe()` through symlinks; if it is `<root>/target/release/tokscope` (or `<root>/bin/tokscope`) and `<root>`
holds `Cargo.toml` and `crates/tokscope`, the home is `<root>`. `setup.sh` keeps linking `~/.local/bin/tokscope` to the
binary inside the clone, so the rule holds after an upgrade. Test it in the M7 dry run on a real clone install.

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
| `ingest`, full (empty DB, all 676 transcripts) | **not measured** | set after the baseline; this is the run the ingest claim rests on, and every user pays it once at cut-over (§6.4) | `time env TOKSCOPE_HOME=$(mktemp -d) tokscope ingest` |
| `summary --by phase`, cold / warm | 0.50 s / 0.15 s, ~25 MB | <10 ms warm | `hyperfine 'tokscope summary --by phase'` |
| `statusline` (runs every turn) | 0.08 s, ~21 MB | ≤10 ms (proposed number) | `hyperfine` |
| `serve` resident memory (warm) | **not measured** — capture in M0 | at most half of the baseline (proposed number) | `ps`/`/proc` after warm ingest |
| `serve`, one page (`/` and `/api/live`) | **not measured** — capture in M0 | not slower | `hyperfine 'curl -s …'` against a warm server |
| `report --privacy redacted` | **5.44 s, ~275 MB** | ≥2× faster, less memory | `time tokscope report --privacy redacted` |

**Finding — the redacted report is the worst path.** `privacy.redacted_copy` copies the entire 98 MB DB into `:memory:`
(`sqlite3.backup`) before redacting, hence 275 MB RSS and 5.4 s. This is backup + SQL bound, not Python bound, so Rust
alone will not fix it; the port should optimize the approach itself — back up to a temp file on disk instead of
`:memory:`, or redact during the copy (per-table `INSERT … SELECT` with the `tk_*` transforms applied) so the full DB
is never resident twice. Same result, lower peak memory.

**What the baseline says about the benefit.** Three of the five measured paths are already fast for one user:
`statusline` 0.08 s, warm `summary` 0.15 s, incremental `ingest` 0.94 s. The slow one (the report) is SQLite-bound.
The two numbers that would justify the port, full ingest and `serve` memory, are not measured. So the baseline is
not complete, and the "5–50×" in the first version of the ADR had no measurement behind it. Capture the two missing
numbers in M0, before any Rust code, and use the M1 gate in §9.

Add a `Makefile` target (`make bench-port`) that runs the same benchmark against the Python and Rust binaries and
prints the table, so regressions are caught in the cut-over PR. Capture the Python baseline **before** starting.

## 9. Build plan (milestones, one cut-over at the end)

Big-bang means one release; the milestones are the internal build order. The Python tree and its test suite remain the
oracle (and keep passing in CI) until M7.

**Freeze rule (proposed, question 8 in §14).** From the start of M1, a Python change that touches behavior needs a
line in a `docs/rust-port-drift.md` list (PR number, files, ported yes/no). A milestone is not done while its area has
an unported line. Bug fixes continue; new features and the rest of the Indigo redesign (#257, steps 2–5) should land
**before** M3 starts, or wait until after M7. Otherwise the web layer is ported twice.

**Where the Rust code lives until M7.** Milestones merge to `main` behind nothing: the workspace sits beside the
Python tree and no user runs it. Each milestone is one or more normal PRs with its "Done when" as the pass/fail table.

### M0 — Workspace, fixtures, and the parity harness

- Scaffold the repo-root Cargo workspace (`tokscope-core`, `tokscope`, `desktop/` stub, `rust-toolchain.toml`).
- Extract the existing `tests/` fixture transcripts and any stored expected DBs into a shared `tests/fixtures/` that
  both languages read.
- Build the **differential harness**: run `python tokscope …` and `rust tokscope …` on the same fixtures (and a real,
  redacted `~/.claude/projects` sample) and diff the resulting SQLite rows and stdout. This is the backbone of every
  later milestone. Rules: each binary gets its own `TOKSCOPE_HOME` (never the same DB, never the owner's real DB);
  `TOKSCOPE_TZ` and the pricing file are fixed; `REAL` columns follow the rule chosen in §6.2; the diff lists the
  first differing row per table.
- Write the golden files for §6.1 with the Python version now, including one case per trap (sort order, wide
  whitespace, invalid UTF-8, a file symlink, a 1,000,000-byte file, an OTel event with a small float cost).
- Capture the missing baselines (§8): full ingest, `serve` memory, one page request.
- Add the Rust jobs to CI (`cargo fmt --check`, `cargo clippy`, `cargo test`) next to the Python jobs.
- Spike the two risky building blocks for one day each before M1: `fancy-regex` on the three ingest patterns, and the
  Python-exact float printer.

**Done when:** `cargo test` runs in CI; the harness can diff one `summary` output end-to-end; the golden files and
the three missing baseline numbers are committed.

### M1 — `core`, the compatibility-critical layer

- `paths.rs`, `schema.rs`, `tz.rs` (`localday` SQL function), `pricing.rs`, `privacy.rs`, `summary.rs`, `errors.rs`,
  `ingest.rs`/`parser.rs`/`store.rs`, `skills.rs`, `otel.rs`, `budgets.rs`, `cache.rs`, `calls.rs`, `context.rs`,
  `markdown.rs`.
- Port every hash/serialization in §6.1 exactly, with golden tests against values computed by the Python version.

**Done when:** `rust tokscope ingest` + `summary` + `session` reproduce the Python output on all fixtures and on the
real sample; a DB diff of `requests`, `sessions`, `skill_calls`, `skill_versions`, `skill_load_versions`,
`tool_calls`, `subagents`, `prompts`, `turn_events`, `headless_calls`, `mcp_defs`, `otel_requests` is empty (`REAL`
columns per §6.2); every §6.1 golden case passes.

**Go/no-go gate after M1 (proposed, question 9 in §14).** M1 is about 22% of the Python code and holds the whole
ingest win. Run `make bench-port` here. If full ingest and incremental ingest do not meet their §8 targets, stop and
decide again before M2–M7 (78% of the work) are spent. This is the one cheap exit a big-bang plan has.

### M2 — CLI surface and the read-only commands

- `clap` subcommands for `ingest`, `summary`, `session`, `skills`, `patterns`, `change`, `check`, `statusline`,
  `mark`, `report`, `open`, `serve`, `service`, `otel-receiver`, `bench`, `replay`, `optimize` (with its eight
  subcommands: `case`, `suite`, `run`, `resume`, `regrade`, `approve`, `reject`, `revert`), and `--version`
  (prints `tokscope <version>`).
- Error text: Python exits with `sys.exit("tokscope: …")`, which prints to stderr and exits 1. `clap` exits 2 on a
  usage error, as `argparse` does; check both on the golden cases.
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
- `setup.sh` edits `settings.json` with an inline `python3` script and refuses to run without Python 3.10. Move that
  edit into the binary (for example `tokscope setup --add-mod <path>` / `--remove-mod`), or the installer still needs
  Python after the port.
- Decide how users get the binary (question 7 in §14). "Build via cargo" means every user needs a Rust toolchain and
  waits minutes for the first build; today a clone needs nothing but Python. The `.deb` no longer needs `apt` Python.
- Replace the CI `package` job (builds the wheel, installs it outside the repo, runs it on an empty data folder) with
  the same check on the release binary. `pipx install .` / `uv tool install .` from the README stop working; say what
  replaces them.

**Done when:** `make deb` / `npm`-free desktop build produces installable artifacts; the window, service
(systemd/launchd), and menu items behave as today.

### M7 — Cut-over

- One PR that replaces `bin/tokscope`/`tokscope/` with the Rust binary and removes the Python package, keeping
  `mod/` untouched.
- Add the cut-over entry to `DECISIONS.md`, update `README.md`/`PRODUCT.md` (Python requirements → Rust toolchain),
  `CLAUDE.md` (code layout, test command), `REVIEW.md` (risk paths), `.claude/` rules and factory agents that name
  Python paths, and `STATUS.md`.
- Rollback: tag the last Python commit (`python-final`); the first run of the Rust binary copies `tokscope.db` to
  `tokscope.db.pre-rust` before the re-parse. Going back is then: check out the tag, restore the copy.
- Run the full benchmark table (§8) and the differential harness one final time.

**Done when:** `./setup.sh && tokscope --version && tokscope open` works on a fresh Linux and macOS machine, and on an
existing clone install with real data: the data is found in the same place (§6.5), exactly one automatic full re-parse
runs (§6.4), the totals per day and per skill before and after are equal, no `skill_versions` row is added, and the
mod's `/tokscope` + statusline work unchanged. (The first version said "with no re-ingest"; that contradicted the
approved bump.)

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
6. **CI**: keep the Python tests, `ruff` and the `package` job running until M7; add `cargo fmt --check`,
   `cargo test`, `cargo clippy`, and the differential harness as the Rust gates. The `mod` job stays as it is. (On this
   PR all seven jobs failed within 3 seconds, and the one log requested was not available. The cause is unknown here
   and should be fixed before M0, because the plan leans on CI as the oracle.) `tests/test_version.py`'s three-places version agreement becomes `version` in the workspace
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
| `json.dumps` output differs | Medium — duplicate OTel rows (compact separators, float `repr`, `ensure_ascii`; §6.1), spurious cost refresh (default separators, sorted keys; §6.3) | One Python-exact printer for each; golden cases with a small float and a non-ASCII model name |
| Patterns the `regex` crate cannot express (§4) | High — three of them decide ingest results (headless sessions, heredocs, task notifications) | `fancy-regex` or hand-written matchers; a golden case per pattern from `tests/` |
| Python keeps changing during the port (§3) | High — work is done twice, the oracle moves | Freeze rule and drift list (§9); finish #257 before M3 |
| Clone installs lose sight of their data (§6.5) | High — the dashboard looks empty after the upgrade | New home rule; M7 dry run on a real clone install |
| Users now need a Rust toolchain (§9 M6) | Medium — install gets harder than today | Prebuilt binaries, or accept it and document it (question 7) |
| No measured need for the two main benefits (§8) | Medium — the port may not pay back | Missing baselines in M0; go/no-go gate after M1 |
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
| 4 | `PARSER_VERSION` bump | **Approved** — bump by one at cut-over to force one full re-parse on real data (the number was 24 → 25 on 2026-11-09; `main` is at 25 since 2026-11-12, see §6.4). |
| 5 | Timeline / ownership | **ASAP.** Ownership of M0–M7 is the owner's unless delegated. |

M0 can start with these settled. The review in §14 adds four questions; 6 and 7 block M6/M7, 8 blocks M3, 9 is a
choice about risk.

## 14. Review against the code (2026-11-12)

The plan was checked against `main` on 2026-11-12. What was read: `core/skills.py`, `core/privacy.py`, `core/otel.py`,
`core/tz.py`, `core/pricing.py`, `paths.py`, the hash and state code in `core/ingest.py`, the parser of `cli.py`, the
handler of `web/dashboard/server.py`, `setup.sh`, `ci.yml`, `README.md`, and a search for look-around and
backreferences in every `re` pattern under `tokscope/`. Not checked: the JSON/CSV output shapes of §6.2, the experiment
code behind M5, the desktop code behind §11, and every number in §8 (measured on the owner's machine).

### Corrections made in this revision

| # | Was | Is | Section |
| --- | --- | --- | --- |
| 1 | "`regex` crate, re-express each pattern" | 17 patterns use look-around or backreferences, which the crate does not have | §4, §12 |
| 2 | OTel dedupe listed only as a separator risk, with the wrong separators | A persisted, unique key that the parser bump does not rebuild; must match byte for byte | §6.1, §12 |
| 3 | "`_input_hash` is not persisted" | It is, in `ingest_state`; harmless only because of the bump | §6.3 |
| 4 | "bump 24 → 25" | `main` is already at 25; the rule is "plus one at cut-over" | §6.1, §6.4, §13 |
| 5 | M7 done "with no re-ingest" | Exactly one re-parse, which the bump requires | §9 |
| 6 | Skill version: "sorted", "> 1 MB" | Sorted by path parts; 1,000,000 bytes; symlink and text-semantics traps | §6.1 |
| 7 | "`chrono-tz` for time" | System zone by default, IANA zone only when named | §4 |
| 8 | "`tests/test_layout.py` becomes a non-issue" | Only the `core` half is compiler-enforced | §4 |
| 9 | ~75 files, ~60 test files; module map without `baseline.py`, `charts.py`, assets, `optimize resume/regrade/suite` | 81 and 45; map completed | §3, §5, §9 |
| 10 | "copy the ADR at cut-over"; "oracle until M6" | The ADR exists; oracle until M7 | §2, §9 |

### New open questions (owner)

| # | Question | Proposal | Blocks |
| --- | --- | --- | --- |
| 6 | How does the binary of a clone install find its data home (§6.5)? | `current_exe()` under a root with `Cargo.toml` + `crates/tokscope` | M1 (`paths.rs`), M7 |
| 7 | How do users get the binary: build from source with `cargo`, or prebuilt binaries per platform (GitHub Releases)? | Prebuilt for Linux x86_64 and macOS arm64; `setup.sh` builds only when no binary fits | M6 |
| 8 | Freeze rule: do the Indigo redesign steps 2–5 (#257) and Skill Optimize v2 (PR #221) land before the web and experiments milestones? | Yes: finish both before M3; bug fixes only after that, tracked in the drift list | M3, M5 |
| 9 | Is there a go/no-go gate after M1, and what result stops the port? | Yes; stop and decide again when full or incremental ingest misses its §8 target | M2 onwards |

### Not changed, but worth a second look

- **Big-bang vs. incremental.** The decision stands. The review only adds the M1 gate, because M1 is the smallest
  piece that can prove or disprove the benefit.
- **Timeline "ASAP".** There is still no estimate. The size table in §3 is the input for one: 16.2k lines of Python
  and 11.8k lines of tests to translate, plus the Tauri app. An estimate should come after M0, from the measured speed
  of M0 and the two spikes, not before.
- **The redacted report** (§8) can be fixed in Python today, without the port (the two options in §8 do not need Rust). If the 5.4 s report is a
  real pain now, do that first; it also makes the Rust comparison fair.
