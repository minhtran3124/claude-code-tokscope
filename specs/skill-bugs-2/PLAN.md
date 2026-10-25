# skill-bugs-2 plan (issues #117-#123)

Integration branch: `fix/skill-bugs-2` (from `github/main`). Tests: `python3 -m unittest discover -s tests -q` (baseline: 467 OK).
No UI files are touched by any issue, so no screenshots needed. Do not edit STATUS.md in sub-PRs.

## Order
1. #117, #118, #119, #121 (independent; any order)
2. #120 (needs #119), #122, #123 (after the first group; all in `core/skills.py`, expect rebases)

## Per issue (real files)
- #117 attribution of the Skill-calling request: `tokscope/core/ingest.py` (`_on_assistant` ~L498, `tool_ctx` L252/519, `PARSER_VERSION` L112, bump it). Check consumers in `core/summary.py`, `core/calls.py`, `features/` budgets/cache. Rule goes in `DECISIONS.md`. Tests: `tests/test_ingest.py`.
  Accept: `python3 -m unittest tests.test_ingest -q`; session token totals unchanged; subagent and parent agree.
- #118 frontmatter parse: `tokscope/core/skills.py` `_body` (L53), `label` (L137-140), also the same `split("---", 2)` in `import_from_transcripts` (~L579). Tests: `tests/test_skills.py` (`a --- b`, leading rule, CRLF, pinned hash).
  Accept: `python3 -m unittest tests.test_skills -q`.
- #119 `canonical_name` cache: `core/skills.py` L181 (`lru_cache`), `_plugin_skill`/`_installed_skill`/`_installed_plugin_of` (L145-180), `command_known` (L194). Invalidate by plugin-folder mtime key; check project/personal commands and skills; same bare name in two plugins stays bare (test).
  Accept: `python3 -m unittest tests.test_skills -q`.
- #120 (after #119) stale `skill_load_versions`: `core/skills.py` `_evidence`/`scan` (L289-327), `load_versions` (L327), `versions` (L363-405). Re-key or join by tool_use_id with name from `skill_calls`; one-time migration merging bare vs `plugin:skill` rows (see `_ensure` L111). Test: relabel then `versions()` keeps load count.
  Accept: `python3 -m unittest tests.test_skills -q`.
- #121 mixed timestamps: `core/skills.py` `_iso` (L236), `_utc` (L285), `record_load` (L262), `load_versions`, `_evidence`, `record` min/max. One normalizer to aware UTC datetime. Test: load 10:00:05.400Z vs version first seen 10:00:05+00:00. Caller of `record_load` in the mod: grep `record_load` under `tokscope/` (location not verified).
  Accept: `python3 -m unittest tests.test_skills -q`.
- #122 fingerprint: `core/skills.py` `_skipped` (L117), `_files` (L121), `fingerprint` (L126). CRLF to LF for text files only; ignore list only for top-level eval/test dirs (assumption), documented in docstring.
  Accept: `python3 -m unittest tests.test_skills -q`; note the one-time version change for CRLF skills.
- #123 partial snapshot: `core/skills.py` `_snapshot` (L228) and `record` (L240). Copy to temp sibling then atomic rename; verify fingerprint and recopy on mismatch. Test: partial snapshot repaired on next `scan`.
  Accept: `python3 -m unittest tests.test_skills -q`.

## Final gate
`python3 -m unittest discover -s tests -q` all OK; `tests/test_layout.py` passes (core imports no features/web).
