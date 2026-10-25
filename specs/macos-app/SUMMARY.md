# macOS app (personal build, arm64): summary

Combined on `feat/macos-app` (sub-PRs #149-#153, all merged into it). 575 tests pass (`python3 -m unittest discover -s tests -q`). No change under `tokscope/web/`, so no UI screenshots.

## Shipped

| Issue | PR | What |
|---|---|---|
| #144 | #149 | `paths.home()` on darwin: `~/Library/Application Support/tokscope`; existing `~/.local/share/tokscope`, `TOKSCOPE_HOME`, `XDG_DATA_HOME` still win; README |
| #145 | #150 | `paths.tool(name)` (PATH plus Homebrew, ~/.local/bin, ~/bin) for git, claude, ant; darwin skips Apple's git stub when `xcode-select -p` fails |
| #146 | #151 | `tokscope service install\|uninstall\|status` (`features/service.py`): launchd plist or systemd unit; `install.sh` and `after-install.sh` call it |
| #147 | #152 | `dist:mac` electron-builder arm64 config, `fetch-python.sh` (pinned sha256, `--dry-run`), entitlements, darwin server command in `main.js`, README, PRODUCT.md, DECISIONS.md |
| #148 | #153 | Dock reopen, About panel, Start at login (opt-in), Install command line tool (`~/.local/bin/tokscope` wrapper) in `mac-integration.js` |

## Checked here

- Full suite OK; `sh -n` on the three shell scripts; `desktop/package.json` parses; `node --check` on `main.js` and `mac-integration.js`; `fetch-python.sh --dry-run` exists.

## Gaps (need the Mac)

- Nothing was built or run on macOS: `npm run dist:mac`, the real python-build-standalone download, the ad-hoc signed `.app`, `launchctl bootstrap`, the Documents-folder permission prompt and the menu items are unverified. The owner builds on the M2 and reports.
- No Mac CI job (GitHub Actions billing is blocked); `npx electron-builder` config validation was not run (no network install assumed).
