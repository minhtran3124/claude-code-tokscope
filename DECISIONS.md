# Decisions

## 2026-10-24 · A request copied into a fork is kept by one session (issue #46)

| Decision | Why | Rejected |
| --- | --- | --- |
| `claude -p --resume <id> --fork-session` writes a new transcript that repeats the earlier assistant lines with the same `requestId`, `message.id` and `uuid` (confirmed 2026-10-24; plain `--resume` appends to the same file). Ingest keeps a shared request on the session that sorts first by `(first_ts, session_id)`, whichever file is parsed first. `PARSER_VERSION` 14. | Counting it in both files doubled its tokens and cost. A fork's `first_ts` is copied from the original, so the id breaks the tie: the owner can be the fork, which then shows the copied history. Only `first_ts` and the id are used because both stay fixed; `last_ts` moves when a session is resumed and made the owner depend on ingest order. Totals are right either way; copied skill loads and subagents still appear on both sessions. | Per-session keys only (the bug); a `copied_from` column (totals would need a filter everywhere); a fork marker (the file has none). |

## 2026-10-22 · Desktop app is an optional Electron window

| Decision | Why | Rejected |
| --- | --- | --- |
| `desktop/` holds an Electron shell that starts `tokscope serve` on a free loopback port and shows it in a window. It is optional, installed by `desktop/install.sh`, and is not in the Python package. The CLI keeps no dependencies. | The owner wants a clickable app that can be pinned. The dashboard already is a local web page, so a window around it adds no second UI to keep in step. | Rewriting the dashboard as an Electron renderer (a second UI); a Chrome `--app` window (needs Chrome, no own icon or process); making Electron a dependency of the CLI. |
| The launcher runs the Electron binary with `--no-sandbox`. The server runs under an `sh` that stops it when Electron's process is gone. | The downloaded `chrome-sandbox` is not setuid and Ubuntu 24.04 blocks the fallback, so Electron aborts at launch. The window loads only the loopback dashboard, whose text is escaped; other links open in the browser. Signals and SIGKILL left the server running without the guard. | Setuid `chrome-sandbox` (needs root); stopping the server only in a quit handler. |
| `desktop/install.sh` installs a systemd user service that runs `tokscope serve` on 127.0.0.1:8770 from login. The window uses it when the page there is a tokscope dashboard, and starts its own server otherwise. (Owner, 2026-10-22.) | The owner wants the server running without a manual start, so the data is fresh and the window opens at once. | An Electron autostart with a tray icon (the server would live only as long as the app); always starting a new server per window (slow first open, no data while closed). |
| The window opens only `http:` and `https:` links in the browser and blocks redirects off the dashboard. (PR #61 security review.) | The port is fixed, so any local process can answer on it while the service is down, and the window runs with `--no-sandbox`. A page there must not reach `file:`, `smb:` or app schemes. The "tokscope" text check does not prove who answers; the service itself only listens on loopback. | Trusting the text check alone. |
| The desktop app ships as a `.deb` built by electron-builder (`npm run dist` in `desktop/`). It bundles Electron plus `bin/` and `tokscope/` under `/opt/tokscope/resources`, depends on `python3 (>= 3.10)`, installs the setuid `chrome-sandbox` (so no `--no-sandbox`), and `postinst` writes the user service file but does not enable it: each user runs `systemctl --user enable --now tokscope`. (Enabling it with `--global` would let another local user reach the dashboard on the shared loopback port; PR #62 security review.) It has no `pyproject.toml`, so the CLI keeps its data in `~/.local/share/tokscope`. (Owner, 2026-10-22; target: Ubuntu 22.04 x86_64.) | The owner wants to install it on another machine with one command. Ubuntu 22.04 ships Python 3.10. | AppImage (no service, no setuid sandbox); Flatpak or Snap (their sandbox blocks `~/.claude`); a user building from a clone on each machine. |

## 2026-10-21 · Keep Classic next to Ink

| Decision | Why | Rejected |
| --- | --- | --- |
| The Classic design stays as a second skin with a Classic/Ink button (key `s`), not only for a comparison. | The owner wants both designs and a button to switch between them. | Removing Classic after v1 merged (done in #17, then reverted here). |
| Classic is a token set and a look block (`tokscope/web/theme/classic.py`), not a frozen copy. Both skins load one layout stylesheet (`tokscope/web/theme/layout.py`, `<style id="layout">`) for grid, sizes, spacing and structure. New markup gets its layout rules there, so Classic shows it without a copy. (Owner, 2026-10-22, issue #23, option A.) | The copies drifted: about 35 Ink selectors had no Classic match, and each redesign step would have doubled the CSS work. | Copying rules into Classic in each PR; waiting until Classic looks broken. |
| A skin is its tokens plus a short look block. Every rule both skins have, even with other values, is written once in the layout sheet and reads per-skin tokens (`--line-w`, `--line-c`, `--r-*`, `--lab-*`, `--num-font` ...; list in `layout.py`). The look block keeps what differs in kind: the answer-card emphasis (Ink flat 10 px 12 px navy shadow, Classic blue-tinted outline), the hero glow and gradient text, hover and pressed looks, delta chips. (#23, step 0 part 2.) | About 330 rules per skin held only values. A new rule needed a copy in each skin, and a forgotten copy left Classic unstyled. | Leaving the value-only rules in each skin (drifts again); one token per property (a long list nobody reads). |
| A rule moves into the layout sheet only when both skins have it word for word and no earlier skin rule sets the same property on the same element. | The skin sheets load after the layout sheet. A rule that came later in a skin sheet would lose to the skin rule it used to beat. | Moving every identical rule (changed the phone nav, the Today bars and the reduced-motion fallback). |

## 2026-10-22 · Motion system (issue #23, step 1)

| Decision | Why | Rejected |
| --- | --- | --- |
| Three duration tokens (`--t-fast` 120 ms, `--t-state` 200 ms, `--t-layout` 320 ms) and `--ease-exit` live in the layout sheet. Entrances play on the first paint only (`html.settled`). A live value changes at once and shows a delta chip. | The 2 s poll swaps regions, so every entrance, blur-in and count-up replayed on each update. About 30 durations made the motion uneven. | Keeping the count-up for live values; a duration per rule. |
| Reduced motion: the entrance, chip, ring and toast keyframes have an opacity-only twin in the layout sheet; the spinner, run bar and Classic hero glow are switched off by their own rule; there is no global `animation:none`. | An update must still show for a person who asks for less motion. A global off switch hid it. | `*{animation:none!important}` (what it was). |

## 2026-10-22 · Overview answers "is today normal?" (issue #23, step 2)

| Decision | Why | Rejected |
| --- | --- | --- |
| A typical day is the median of the last 14 active days (a day with at least one request), cumulative to the same local time, shown with a p25 to p75 band only when more than 7 days are active. (Chosen by the owner, 2026-10-22.) | Days off would pull a calendar-day median down and make every working day read as "above typical". | All calendar days; the same weekday only (needs about 4 weeks of history). |
| A change chip shows only with more than 7 days of history, counted as elapsed time from the first request, and when the window before the range holds at least one full day. It compares the average per day in the range with the average per day in the window before it, over the elapsed time that window has data. A sentence under the strip says so once. Sessions and runs count once per day they appear. From cache is the exception: its chip is the relative change of its share of all tokens, and the same sentence says so. | A 30-day range with 10 days before it must not read as -67%. | "History starts ... too short to compare" on every tile. |

## 2026-10-21 · Headless child sessions keep their own totals

| Decision | Why | Rejected |
| --- | --- | --- |
| Child tokens stay on the child row. The parent's totals do not change. | A parent's totals stay comparable with sessions that ran no `claude -p`. Children are shown nested under the parent, so their cost is still visible. | Adding the child tokens to the parent. |

## 2026-10-25 · The request that calls Skill pays for the load (issue #117)

| Decision | Why | Rejected |
| --- | --- | --- |
| A request that contains a `Skill` tool call is charged to the skill it loads, with its tool calls and the subagents it spawns, wherever the Skill block sits in the message. Several Skill calls in one request: the last one. Later requests keep the last skill, as before. Totals per session do not change, only the split. `PARSER_VERSION` is 21. | The request's output is the cost of making the load. A subagent in the same message already got the new skill, so its parent must agree. | Charging the previous skill (what it was); splitting a request between skills. |
