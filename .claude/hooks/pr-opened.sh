#!/usr/bin/env bash
# PostToolUse hook for `gh pr create` (see .claude/settings.json). A hook cannot start a skill,
# so it adds a reminder next to the tool result; the CLAUDE.md "Review" rule says what to do.
# Inside a subagent (agent_id is set) the reminder says to hand the PR back instead.
# The settings `if` filter is best-effort, so the script also checks the command itself.
exec python3 -c '
import json, re, sys
try:
    data = json.load(sys.stdin)
except ValueError:
    sys.exit(0)  # never block the session over a bad payload
ti = data.get("tool_input") if isinstance(data, dict) else None
cmd = ti.get("command", "") if isinstance(ti, dict) else ""
if not re.search(r"\bgh\s+pr\s+create\b", str(cmd)):
    sys.exit(0)  # not a `gh pr create` call: no reminder
m = re.search(r"https://github\.com/[^\s\"]+/pull/(\d+)", json.dumps(data.get("tool_response", "")))
pr = m.group(1) if m else "<number>"
if data.get("agent_id"):
    text = f"PR #{pr} was opened from a subagent. Per CLAUDE.md, subagents do not review: return the PR number to the main session."
else:
    text = (f"PR #{pr} was opened. Per the CLAUDE.md Review rule, the main session now runs "
            f"/code-review:code-review {pr} (Anthropic plugin, with REVIEW.md; first pick the reviewers, their model and effort for this change type: REVIEW.md), "
            f"then git fetch -q origin and /security-review when the type needs it, unless the owner said to skip review. "
            f"During /factory, ignore this: Phase 6 reviews after Phase 5b.")
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}))
'
