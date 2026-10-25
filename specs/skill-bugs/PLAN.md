# Plan: skill bugs #106-#110 (branch fix/skill-bugs)

Remote `github`; issue bodies cite old paths, real ones below. Core never imports features/web.
Sub-PRs do not edit STATUS.md. Test command for all: `python3 -m unittest discover -s tests -q` (baseline: 452 pass).

## Order
1. #106 text steal (ingest). First: #108 touches the same code.
2. #107 mod mark canonical name (independent).
3. #109 $ARGUMENTS hash (independent; core/skills.py only).
4. #110 library numbers (UI PR: screenshots at 1440 and 375 px, before=main, pass/fail table; see .claude/skills/factory/references/uat.md).
5. #108 unlisted built-in command, after #106 (same ingest code; rebase on it).

Parallel-safe: #107, #109, #110. Serial: #106 then #108. Both ingest PRs bump PARSER_VERSION (`core/ingest.py:107`, now 18); merge #106 first, then rebase #108 and bump to the next number.

## Real locations
| Issue | Files | Tests |
|---|---|---|
| #106 | `tokscope/core/ingest.py` `_on_command_skill_text` (~429), caller ~366, `_load_skill` ~474 | `tests/test_ingest.py` |
| #107 | `tokscope/cli.py` ~124-133 calls `core/skills.py` `record_load` (~211); `canonical_name` (~147) | `tests/test_skills.py` |
| #108 | `tokscope/core/ingest.py` `BUILTIN_COMMANDS` (~53), command branch ~418, `_load_skill` | `tests/test_ingest.py` |
| #109 | `tokscope/core/skills.py` ~63-73 (hash candidates) and ~433-437 (text rebuild) | `tests/test_skills.py` |
| #110 | `tokscope/features/library.py` `usage()` (~135); callers `web/dashboard/server.py:58`, `web/dashboard/pages/library.py` (~432, cards ~24-32); `web/dashboard/pages/overview.py` ~338 (ids keyed by `k["dir"]`) | `tests/test_library.py`, `tests/test_dashboard.py` |

## Acceptance commands
- All: `python3 -m unittest discover -s tests -q` ends with OK.
- #106: new test in test_ingest: typed `/mycmd` then `Skill(foo)` fixture gives each load its own text_hash; isMeta matched by sourceToolUseID; subagent isMeta does not attach to a main-thread command. `grep -n "PARSER_VERSION =" tokscope/core/ingest.py` shows a bump.
- #107: test: bare plugin skill mark gives ONE skill_versions row, load recorded under `plugin:skill`.
- #108: test: prompt 1 `review`, prompt 2 `/rename x`, prompt 3 plain gives phase `review` on prompt 3, no skill for rename; real command file/skill still loads; PARSER_VERSION bumped.
- #109: test: body `Run $ARGUMENTS on the config; the end`, args `the` hashes to a candidate; check `$1` / `$ARGUMENTS[0]` against Claude Code docs, handle or note.
- #110: tests: usage excludes bench sessions (as `skills.versions()`), honors date range and project; same-named personal/project skills show own counts; frontmatter name differing from folder matches; overview links `plugin:skill`. Screenshots and table in PR.
