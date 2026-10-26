# Behavior

Rules a capable model does not reliably follow on its own. Always loaded (no `paths:`). Adapted from agent-harness `rules/behavior.md`.

1. **Absence claims need a cited search.** Before writing "there is no X" (no caller, no test, no handler), name the paths or commands you searched. If you cannot, write "unknown".
2. **Name the ambiguity.** When a task can be read in two materially different ways, say which readings exist and which one you picked, in the reply.
3. **Check an interface before relying on it.** Before you use a flag, subcommand or path you have not seen in this session, check it (`--help`, `ls`, or the file).
4. **Deliver the whole ask.** Do not quietly narrow, widen or change the task. If you think the ask is wrong, say so in one sentence and continue as asked. If part cannot be finished, finish the rest and say what is missing and why.
5. **One assumptions artifact per PR.** Do not publish one artifact (or one file) per assumption. Keep one artifact for the PR (`specs/<slug>/assumptions/pr-<n>.md`, or the published artifact for that PR) and add every assumption for that PR to it as a numbered section (Context, Decision, Alternative, Impact). A later round, review fix or follow-up on the same PR edits that artifact, never a new one.
