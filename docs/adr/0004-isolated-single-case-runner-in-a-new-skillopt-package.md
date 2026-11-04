---
ticket: 187
stage: design
status: needs-review
needs_review: true
confidence: high
decided_by: claude (ship workflow: design)
date: 2026-11-04
---

# 0004. Isolated single-case runner in a new skillopt package

## Context

Ticket #187 needs one eval case run against one skill version in an isolated claude -p session and graded by machine; the old optimize.py job runner lacks isolation flags and is deleted in slice 7.

## Options

- New tokscope/experiments/skillopt/ (sandbox.py, grade.py) with its own argv, pinning copy and claude lookup, plus `tokscope optimize case`
- Extend optimize.py (_cmd/_run) and add skills.pin(check=False)
- Use --dangerously-skip-permissions for writes

## Decision

Option 1: sandbox.py builds a temp sandbox (fixtures + fingerprint-file-set copy of the skill under .claude/skills/<skill>), runs claude with --setting-sources project --strict-mcp-config --no-session-persistence --output-format stream-json --verbose --permission-mode acceptEdits --add-dir <sandbox>, and saves stream.jsonl, final.md, plugins.json, run.json, files/ and grading.json under paths.home()/bench/skillopt/runs/<skill>/<case>/<ts>/; grade.py evaluates the six check types with quoted evidence and marks a run without a result event INVALID.

## Why

Matches the probed isolation mode and the owner-confirmed permission flags, keeps core APIs and the old path untouched, and gives a pure argv function for asserting AC3/AC5.

## Consequences

New public CLI subcommand and evals.json checks contract that later slices build on; small duplication with optimize.py until slice 7.

## How to reverse

Delete tokscope/experiments/skillopt/ and tests/test_skillopt_runner.py, remove the optimize parser from cli.py, revert PRODUCT.md.
