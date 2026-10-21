# Review guide

For any reviewer of a claude-code-tokscope change: `/code-review`, `/security-review`, or a person. Review only the lines the PR changes.

## Pick the reviewers first

Spend reviewers only where they can find something. Before any review (in or outside `/factory`):

1. Read the changed paths (`gh pr diff <N> --name-only`) and the PR body. Name the change type from the table below. A PR with several types takes the union of their rows.
2. Spawn only the reviewers in that row. Tell each one what this change must get right. Do not send a reviewer a check that has nothing to look at (no "trace the JS" on a docs PR).
3. One scorer per finding. No findings: no scorers. Skip the eligibility check when this session opened the PR.
4. Pick the model and effort of each reviewer, scorer and security review for this change (next section). Pass them by hand: the plugin's default is Sonnet.
5. Start the report with the type, the reviewers that you ran, and their model and effort. For example: "Docs/rules: 1 reviewer (Sonnet, medium), no security review".

| Change type | Paths (typical) | Reviewers | `/security-review` |
| --- | --- | --- | --- |
| Docs or rules only | `*.md`, `.claude/` | 1: consistency, so no contradiction or gap with `CLAUDE.md`, factory `SKILL.md`, `REVIEW.md`, and true statements about the code | No |
| Tests only | `tests/` | 1: each test can fail, and tests the claim in its name | No |
| Bug fix | `tokscope/` | 2: bugs (the fix covers the failing input and its neighbours, and a test proves it), history (it does not undo an earlier fix) | Yes, when it touches a High or Medium path |
| UI change | `tokscope/report.py`, `tokscope/dashboard.py`, `tokscope/charts.py` markup, CSS, page script | 2: bugs (each template branch and state, JS ids, escaping), comments (rules in code comments, such as textContent only) | Yes, when it renders data, adds a form or adds script |
| New feature | `tokscope/` plus tests | All 5: claude-md, bugs, history, prior-prs, comments | Yes |
| Risky path | the High row of "Risk by path" | All 5, whatever the type | Yes |

### Model and effort

Review has no fixed model or effort. The main session picks them for each agent, from how hard its check is on this diff. Use the smallest model and effort that can do the check well:

- **Mechanical check** (counts, links, frontmatter keys, "is the PR open", scoring a finding that names its file and line): Haiku, default effort.
- **Read the diff and its neighbours** (docs consistency, a small bug fix, template branches, a short UI change): Sonnet, low or medium effort.
- **Trace state across files, or a High-risk path** (writes files, runs `claude -p`, host and origin checks, a large feature, a subtle concurrency or escaping question): Opus, medium or high effort.

Go up one step when the diff is large or a cheaper run missed something on this PR. Go down when the check is narrow.

## What failure looks like here

- **The numbers lie:** wrong tokens, cost, dates, phase, skill or subagent attribution for a session, a double-counted transcript, or a session missing from the dashboard or report.
- **Quota is spent nobody asked for:** something runs `claude -p` (bench, replay, optimize) without the owner starting it, runs several in parallel, or retries in a loop.
- **It writes where it should not:** a write outside the tokscope data home (this repo's `data/`, `reports/` and `bench/` in a source checkout, else `TOKSCOPE_HOME`) and the bench/replay/optimize work folders, or to the owner's source files, `.git/` or `~/.claude/`. Ingest only reads `~/.claude/projects`.
- **It opens to the network:** the dashboard's bind address in `dashboard.py` (`serve`) stops being `127.0.0.1`, or a POST route is reachable from another origin without the host, origin and token checks in `dashboard.py`.
- **Private data leaks:** Claude session contents (prompts, paths, titles), `privacy.key`, or a token is logged, sent to a third party, written into a `--privacy redacted` or `numbers` output, or rendered without escaping.

## Risk by path

| Risk | Paths |
| --- | --- |
| High | code that writes files or runs `claude -p` (`tokscope/bench.py`, `replay.py`, `optimize.py`), `bin/tokscope`, `setup.sh`, the `host`/`port` handling and the POST handlers in `tokscope/dashboard.py`, `tokscope/privacy.py` |
| Medium | the rest of `tokscope/` (`ingest.py`, `charts.py`, `report.py`, `cli.py`, parsing, markup) |
| Low | docs, `*.md`, `.claude/`, tests only |

A PR takes the highest risk of any path it changes.

## Do not report

- Style a formatter would fix.
- Generated files: `build/`, `*.egg-info/`, `__pycache__/`.
- Problems in code the PR does not change. Those go to the PR's Follow-ups as pre-existing.

## How to report

- Every finding gives `file:line` and the concrete input that goes wrong.
- Tag each one **Important** (must fix before merge) or **Nit** (at most 5; never blocks).
- Start the summary with the count, for example "2 Important, 1 Nit". With nothing to fix, say "0 findings" and stop.
