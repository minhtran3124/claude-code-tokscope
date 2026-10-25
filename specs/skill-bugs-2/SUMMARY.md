# Skill bugs #117-#123 - summary

## Shipped (sub-PRs merged into fix/skill-bugs-2)
| Issue | PR | What |
| --- | --- | --- |
| #117 | 125 | The request that calls Skill is charged to that skill (last one if several); rule in DECISIONS.md; PARSER_VERSION 21 |
| #118 | 127 | Frontmatter = block between a first line that is exactly `---` and the next such line; CRLF handled; hashes of ordinary skills pinned |
| #119 | 124 | `canonical_name` cache follows plugin folder mtimes; project/personal names are not claimed by a plugin; same bare name in two plugins stays bare |
| #120 | 130 | `skill_load_versions` re-keyed on rename; split bare/plugin rows merged |
| #121 | 126 | One timestamp normalizer for every compare in skills.py |
| #122 | 129 | Fingerprint is portable (CRLF = LF); ignore list only for top-level bench folders; PARSER_VERSION 22 |
| #123 | 128 | Snapshot copied via temp folder and renamed; partial snapshot repaired on next scan |

## Verify
`python3 -m unittest discover -s tests -q`: Ran 479 tests, OK.

## Gaps
- None found against the acceptance criteria. No UI files changed (no screenshots needed).
- One-time version change for CRLF skills (#122) and re-parse of transcripts (PARSER_VERSION 22) are expected.
