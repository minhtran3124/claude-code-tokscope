# Decisions

## 2026-11-12 · The Indigo look replaces Ink (issue #257)

| Decision | Why | Rejected |
| --- | --- | --- |
| The look changes from Ink (warm paper, ink outlines, mono labels) to Indigo: cool white surfaces, one indigo accent, a left menu with line icons. Step 1 changes the token values, the fonts, the menu and the shared controls; the token names (`--page`, `--ink`, `--mark` ...) stay until the pages are done (step 5 of #257). | The owner approved a prototype of the new look for every main page. Keeping the token names lets one PR recolour every page without touching 1100 layout rules. | A second skin beside Ink (two looks to keep in step, see 2026-11-05); renaming the tokens first (a large diff with no visible change). |
| Fonts: Hanken Grotesk (a variable font, one file per subset) for the interface and for numbers, with `tabular-nums`; DM Mono for ids, paths and code. DM Mono has no Vietnamese letters, so the IBM Plex Mono vietnamese subset stays as its fallback for that range. All files ship in `tokscope/assets/fonts/`. | The pages must work offline, and session titles and paths can hold Vietnamese text. The font files went from 195 KB to 84 KB. | Loading the fonts from a font service (needs the network); mono text without Vietnamese letters (a system font would show in the middle of a word). |
| Main thread is the accent (indigo), subagents are teal, the 7-day average is amber. Warnings read `--warn` (amber), not the subagent colour. | Under Ink the subagent colour was amber, so warnings shared it. With teal subagents a warning in teal would read as "ok". | One colour for subagents and warnings. |
| Step 5: the light `--ok-bg` and `--warn-bg` fills are a little lighter so status text on them passes WCAG AA (4.5:1). The token names (`--ink`, `--mark`, `--page` ...) stay: they now name roles (text, accent, page), not Ink colours, and the comments that called the look sheet "Ink" or spoke of two skins are rewritten. `docs/design-prompt.md` describes the Indigo style. | Measured contrast on the step 2 fills was 4.45 and 4.46. A rename would touch about 1100 rules with no visible change. Indigo against teal stays easy to tell apart in a colour-blindness simulation (CIELAB ΔE 74 deutan, 78 protan, 29 tritan in light mode; the two also differ in lightness). | Darker status text (it would no longer match the series colours); renaming every token. |

## 2026-11-05 · The guide-based Optimize is removed (issue #193)

| Decision | Why | Rejected |
| --- | --- | --- |
| The Library's guide Optimize is deleted: the `optimize-skill`, `asd-ste100` and `unslop` guide rewrite of a copy, its job page, its benchmark add-on and the `api/optimize` routes. The evaluated loop (`/optimize`, `tokscope optimize run`) is the only way to change a skill. `tokscope bench` and the STE check tab stay. Old job folders under `bench/optimize/` stay on disk, hidden. | The guide rewrite changed a skill with no measure of whether it got better. The loop measures a draft against an approved eval suite, with gates and evidence, before anyone can approve it. | Keeping it beside the loop: two ways to change a skill, one of them unmeasured. Leaving the old job routes as dead code. |

## 2026-11-05 · The background service turns on by itself on Linux

| Decision | Why | Rejected |
| --- | --- | --- |
| `./setup.sh` runs `tokscope service install` (skip with `--no-service` or `TOKSCOPE_NO_SERVICE=1`, `--uninstall` removes it). The Linux desktop app does the same at its first launch, once per user (marker `service-autostart` in its user-data folder, so a user who turns it off is not switched back on), and waits for the service before it shows the window. macOS: `setup.sh` also installs it, but the app's "Start at login" stays opt-in (2026-10-25). (Owner, 2026-11-05: "no question, start in the background".) | The owner wants the server running after an install, with no extra step. A `.deb` postinst runs as root outside the user's session, so it cannot enable a user service. | `systemctl --global enable` in the `.deb` postinst (every user would run the unit on the fixed port 8770: the second user's service fails, and others can reach the first user's dashboard; PR #62 review); asking before the first start. |

## 2026-11-05 · Classic is retired; Ink is the only look

| Decision | Why | Rejected |
| --- | --- | --- |
| The Classic skin, its Design button, its Settings row and the `s` shortcut are removed (`tokscope/web/theme/classic.py` is deleted). Ink is the only look; the layout sheet and the Ink tokens stay as they are. Supersedes "Keep Classic next to Ink" (2026-10-21). | The owner chose the new direction (graphite console) for the redesign and does not want two looks to keep in step. One look halves the screens to test. | Keeping Classic behind a setting: every new screen would need a Classic check. A stale `tokscope-skin` value in a browser is harmless and is ignored. |

## 2026-11-02 · The OTel receiver reads a refused body before it answers

| Decision | Why | Rejected |
| --- | --- | --- |
| A body over `--max-body` is read and dropped, up to 8 MiB more, then gets its 413. This changes the immediate refusal of the size caps (#50): the cap on what is kept is the same, and nothing dropped stays in memory. | Closing while the client is still sending gave it a broken pipe, not the 413, so an exporter could not tell a refused body from a network fault, and the test failed CI at random. | Changing only the test, which hides the fault. A 64 MiB drain, which reads 8x the cap for no known exporter. |

## 2026-10-25 · macOS app is a personal arm64 build with bundled Python (issue #147)

| Decision | Why | Rejected |
| --- | --- | --- |
| `npm run dist:mac` builds an arm64 `.dmg` and `.zip` with electron-builder. `scripts/fetch-python.sh` downloads a pinned python-build-standalone (3.12.15, sha256 checked) into `desktop/python/`, which becomes `Resources/python`. On darwin `main.js` runs `python/bin/python3 -s -m tokscope.cli serve` with `PYTHONPATH`, `PYTHONNOUSERSITE=1`, `TOKSCOPE_HOME` (the env value, else an existing `~/.local/share/tokscope`, else Application Support) and a PATH that adds Homebrew and `~/.local/bin`. No signing, notarization, auto-update, Mac CI or Homebrew tap; the background server is opt-in. (Owner, 2026-10-25.) | Personal use on an M2. Finder gives an app a minimal PATH and Apple's `python3` is 3.9, below `requires-python`. | Relying on the system Python; universal or x64 builds; a signed, notarized release; a Mac CI job (Actions billing is blocked). |

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

## 2026-10-21 · Keep Classic next to Ink (superseded 2026-11-05: Classic is retired)

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
| Reduced motion: the entrance, chip, ring and toast keyframes have an opacity-only twin in the layout sheet; the spinner and run bar are switched off by their own rule; there is no global `animation:none`. | An update must still show for a person who asks for less motion. A global off switch hid it. | `*{animation:none!important}` (what it was). |

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

## 2026-10-25 · A failed skill load is not a load (issue #134)

| Decision | Why | Rejected |
| --- | --- | --- |
| A `Skill` tool call whose result has `is_error` or starts with `Unknown skill` is a failed load: `skill_calls.failed` is 1, and it gives back the skill and phase it took, so its own request, its tool calls and later requests keep the skill that was active before (unless a later Skill call in the same turn already replaced it). Failed loads are left out of loads, versions, scan and library use; they show per skill in the Versions card and in `summary --by skill --errors` (`failed_loads`). Per-session totals do not change, only the split. `PARSER_VERSION` is 24. | An unknown skill loads nothing, so charging later work to it hides the real skill's cost and counts a load that never happened. | Dropping the failed row (loses the count); keeping the failed skill active (what it was). |

## 2026-10-25 · Mac behaviour of the desktop app (issue #148)

| Decision | Why | Rejected |
| --- | --- | --- |
| The Mac logic lives in `desktop/mac-integration.js` (no Electron import): wrapper text, `service` command, CLI install, About options, Dock rule. `main.js` only wires it. Start at login and Install command line tool are File-menu items shown on macOS only; the service stays opt-in. The wrapper sets `TOKSCOPE_HOME` by the same rule as the app: the env value, else an existing `~/.local/share/tokscope`, else Application Support. A wrapper not written by tokscope is replaced only after a confirm. | Tests run on Linux with a fake platform; only the wiring needs the Mac. The terminal and the hook must read the app's database. | Logic inline in `main.js` (untestable); always overwriting `~/.local/bin/tokscope`; a service on by default. |
