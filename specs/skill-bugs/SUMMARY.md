# Skill bugs #106-#110: summary

## Shipped
| Issue | PR | What |
|---|---|---|
| #106 | #111 | isMeta skill text matched by sourceToolUseID; subagent messages never attach to a main-thread command; parser bump |
| #107 | #112 | `record_load` canonicalizes the skill name: one version row, mark under `plugin:skill` |
| #109 | #114 | `$ARGUMENTS`/`$N`/`$ARGUMENTS[N]` substitute only the placeholder |
| #110 | #113 | Library usage skips bench sessions, follows range and project, counts per skill folder, frontmatter and `plugin:skill` names link |
| #108 | #115 | A typed `/cmd` is a skill only when a SKILL.md, command file or skill text backs it; else phase kept; PARSER_VERSION 20 |

Verify: `python3 -m unittest discover -s tests -q` gives `Ran 455 tests ... OK`.

## Gaps
- #110: hosted before/after screenshots missing (PNGs local only; sandbox blocked the pr-assets worktree).
- #109: a positional token that is also an ordinary word elsewhere is not disambiguated.
- Sessions ingested before parser 20 re-parse on next ingest.
