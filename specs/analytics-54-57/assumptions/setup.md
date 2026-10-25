# Setup assumptions (issues #54, #55, #56, #57)

Artifact publish hit the daily limit (429), so this is the fallback file.

## A1. Statusline snapshot storage does not exist (scope)
- Context: #54 and #56 mention statusline snapshots. `grep -rniE 'statusline|status_line|prompt_cache|rate_limits'` over the repo (excluding .git and node_modules) found no statusline command, module or snapshot table. Only hits: a slash-command name list in core/ingest.py and BUILTIN_AGENTS in core/privacy.py.
- Decision: #54 builds the transcript-derived analytics fully and shows official miss_causes only if a snapshot table exists (nothing shown otherwise). #56 treats quota-% budgets as "no data" without snapshots and defers the statusline flag.
- Alternatives: build a statusline snapshot writer and store as a prerequisite PR. Rejected as scope creep; neither issue's acceptance criteria require it.
- Impact: snapshot-dependent bullets of #54 and #56 are partial. Transcript-based criteria and the exit codes are fully covered.

## A2. Order: #57 and #55 first, then #54 and #56
- Context: the task prescribes this order. #57 and #55 both may edit core/ingest.py (PARSER_VERSION is 16).
- Decision: #57 goes first, then #55 rebases on it. Each PR bumps PARSER_VERSION at most once.
- Alternatives: run #57 and #55 in parallel and resolve conflicts at integration.
- Impact: avoids PARSER_VERSION and ingest.py merge conflicts.

## A3. Two phases with a merge between
- Context: the issues overlap in ingest, dashboard Breakdowns and the report.
- Decision: two phases (#57,#55 then #54,#56) with a merge between, to keep conflicts small.
- Alternatives: all four in parallel.
- Impact: slower but fewer conflicts.

## A4. Base is main
- Context: current branch is main; /autopilot says use the current branch.
- Decision: integration branch feat/analytics-54-57 from main; the final PR targets main and is not merged.
- Alternatives: target v1.
- Impact: retarget the PR if wanted.

## A5. Issue file paths re-mapped
- Context: the issues name pre-refactor paths.
- Decision: agents locate the equivalent files in core, features and web.
- Alternatives: none. Impact: none.

## A6. Plan committed with split git commands
- Context: compound git commands were refused by the worktree guard.
- Decision: used separate plain commands and the Write tool for PLAN.md.
- Alternatives: none needed. Impact: none.
