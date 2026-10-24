# Issue 57 assumptions

Errors, retries and interrupts (PR #101). The Artifact page could not be published (daily publish limit, 429), so this file is the fallback.

## A1. Repeat scope is prompt + agent + tool + input hash

- Context: The issue says same name and input hash in the same prompt.
- Decision: Key is prompt_idx, agent_id, tool name and sha1 of the sorted JSON input. A subagent repeating the main thread's read is not a repeat.
- Alternative: Key by prompt only, so main and subagents share it.
- Impact: Repeat counts are slightly lower than a prompt-wide count.

## A2. Interrupts and API errors go in a new turn_events table

- Context: These are not tool calls, so tool_calls cannot hold them.
- Decision: turn_events(session_id, ts, prompt_idx, agent_id, skill, phase, kind) with kinds interrupt, api_error, retry. API errors are assistant lines with isApiErrorMessage or apiError. Retries are system lines with subtype api_error. No retry lines exist in local transcripts, so only a fixture covers that path.
- Alternative: Add columns to prompts or sessions.
- Impact: One extra table, listed in privacy COLUMNS and the TABLES clear list.

## A3. Per-version error rate counts calls made while the skill was active

- Context: Tool calls need attributing to a skill and version.
- Decision: tool_calls stores the skill and phase active at the call. A version's rate sums the calls of the prompts that loaded that version. A prompt's calls count even after a second skill loads, as with tokens.
- Alternative: Join through requests.
- Impact: Matches how tokens per version are attributed.

## A4. summary --errors groups only by skill, agent or phase

- Context: Model has no meaning for tool calls.
- Decision: `--by model --errors` exits with an error. Dashboard model filters are dropped for call counts (errors.for_calls).
- Alternative: Join requests to filter by model.
- Impact: The Errors section ignores the model filter.

## A5. Error classes come from text patterns

- Context: The transcript has only is_error and the result text.
- Decision: First match wins: mcp tool name, edit_mismatch, permission, timeout, not_found, exit_code (starts with 'Exit code N'), else other.
- Alternative: Parse structured toolUseResult.
- Impact: Heuristic, may misclassify unusual messages.

## A6. Screenshots use seeded data and the original report as the Versions source

- Context: The Library skill page needs a real skill folder.
- Decision: The Versions card was captured from the HTML report's Skill versions section, which uses the same _skill_versions renderer, on a seeded DB. Main has no Errors section or Versions columns, so only the change card has a before shot.
- Alternative: Fabricate transcripts and a skill folder.
- Impact: The Library page's Versions card uses the same code path but was not captured separately.

