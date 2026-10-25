# Assumptions: bad budgets.json exit code (PR #104 review fix)

The artifact could not be published (daily publish limit reached), so this file stands in.

## 1. Finding already resolved upstream
- Context: the finding was written against an earlier diff. The branch head already contains `5aca13b`, which makes a bad budgets.json exit 2.
- Decision: checked the code, docstring, README line 153 and the test, ran the full suite, added no duplicate commit.
- Alternative: a no-op or cosmetic commit. Rejected: noise for no gain.
- Impact: no new code change. The PR is unchanged.

## 2. SUMMARY.md not found
- Context: the finding says SUMMARY.md also states exit 2. grep found no SUMMARY.md in the PR worktree.
- Decision: no change. The code now exits 2, so any document that says 2 is correct.
- Alternative: search for the file elsewhere.
- Impact: none.
