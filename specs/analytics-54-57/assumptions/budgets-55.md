# Budgets and alerts (#55): assumptions

Made where the issue was silent. PR 100.

| ID | Assumption | Context | Decision | Alternatives | Impact |
|---|---|---|---|---|---|
| A1 | `tokscope statusline` did not exist; a minimal one was added | The issue says statusline.py and a statusline command. `grep -rniE statusline` over the repo found none (only a slash-command list and BUILTIN_AGENTS). | Added a small `tokscope statusline` command in cli.py that prints one coloured line (ok/near/over) and never fails. | Defer the statusline flag; build a full statusline with session data. | Users set it as Claude Code's statusLine command; no snapshot storage is added. |
| A2 | Quota percent budgets report no data | `block_pct` and `weekly_pct` need statusline snapshots, which tokscope does not store. | They load and validate (0-100), but evaluate to state `nodata` and never count toward ok/near/over. | Add a snapshot store (separate decision, per the plan). | No quota alerts until snapshots exist. |
| A3 | Exit 30 scope | The issue says 30 for no data only. | 30 when there is no budgets file, nothing measurable, or the requests table is empty. A bad file exits 2 with its message. | Exit 30 for a bad file too. | CI can tell a broken config from missing data. |
| A4 | `per_load_tokens` semantics | The issue does not define it. | The median tokens per load of the newest version of the skill that has loads, from `skills.versions()`. | Maximum or latest single load. | No data until a load exists. |
| A5 | SessionEnd line covers daily budgets only | Crossing is judged by evaluating with and without the ended session. | Only time-based budgets are compared; per-load medians are not session-scoped. Output is silent on a bad or missing file. | Include per-load. | The hook never fails because of budgets. |
| A6 | Day window is the local day | The issue says daily without defining the zone. | Local midnight (TOKSCOPE_TZ aware, `tz.midnight()`), the same day as the dashboard's Today. | UTC day or a rolling 24 h. | Matches the Today card. |
