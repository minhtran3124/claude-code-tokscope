# macOS app plan (issues #144-#148)

Owner decisions: Apple Silicon (M2) arm64 only, personal build, no signing/notarization/auto-update/Mac CI, background
server opt-in, Electron + bundled python-build-standalone. No Mac for agents: test on Linux with faked `sys.platform`
and injected runners; the owner builds and runs the `.app`. Integration branch: `feat/macos-app` (PRs target it).
Baseline: `python3 -m unittest discover -s tests -q` = 538 tests OK on github/main a24a792.

## Order and dependencies

1. #144, #145, #146 first (independent, any order or parallel; they touch different files, except #144 and #145 both edit `tokscope/paths.py` and `tests/test_paths.py`, so merge one then rebase the other).
2. #147 after #144 + #145 (needs the Application Support home and PATH lookup).
3. #148 after #146 + #147 (uses `tokscope service` and the bundled Python launch).

## Real file locations

| Issue | Files (old names in issue -> real) |
|---|---|
| #144 | `tokscope/paths.py` `home()` (fallback branch, line ~19); tests in `tests/test_paths.py`; `README.md` |
| #145 | New `paths.tool(name)` in `tokscope/paths.py`. Call sites: git in `tokscope/core/skills.py:373` (core may import `paths`, not features/web); git in `tokscope/experiments/bench.py:49,58` and `replay.py:108,113,129,157`; claude in `experiments/bench.py:90-91`, `replay.py:142-143`, `experiments/optimize.py:54-55`; ant in `tokscope/integrations/managed.py:_ant()` (replaces the `USER_BIN` logic). `features/projects.py` has no claude/git subprocess (searched `grep -rn '"claude"' tokscope`), so nothing to change there. Tests: `tests/test_paths.py`, `test_skills.py`, `test_managed.py`. Search PATH + /opt/homebrew/bin, /usr/local/bin, ~/.local/bin, ~/bin; on darwin skip git if `xcode-select -p` fails (injected runner). |
| #146 | New `tokscope/features/service.py` (plistlib), wire `service install\|uninstall\|status` in `tokscope/cli.py`; Linux unit text must equal `desktop/install.sh` (heredoc ~line 60) and `desktop/build/after-install.sh` (`/usr/lib/systemd/user/tokscope.service`); make both scripts call the command, output identical. Tests: new `tests/test_service.py`. Respect `tests/test_layout.py`. |
| #147 | `desktop/package.json` (mac target dmg+zip arm64, extraResources python/, `dist:mac`), new `desktop/scripts/fetch-python.sh` (pinned URL+sha256, `--dry-run`), new `desktop/build/entitlements.mac.plist`, `desktop/main.js` (darwin launch of `resources/python/bin/python3 -s -m tokscope.cli serve`, PYTHONPATH, PYTHONNOUSERSITE, extended PATH, TOKSCOPE_HOME; keep SERVICE_PORT 8770 probe and loading cover), `README.md` section, `PRODUCT.md:18` ("Linux only"), `DECISIONS.md`. Put command construction in a small CommonJS module (e.g. `desktop/launch.js`) so it is node-testable. |
| #148 | `desktop/main.js` (+ pure modules, e.g. `desktop/menu.js`, `desktop/wrapper.js`): `activate` handler, About panel, "Start at login" toggle (runs `tokscope service install\|uninstall` via bundled Python), "Install command line tool" writing a `~/.local/bin/tokscope` wrapper; quit on last window close; `README.md`, `DECISIONS.md`. Node tests for wrapper content and menu logic. |

None of these change `tokscope/web/`, so no UI screenshots are required (desktop shell only).

## Acceptance commands

- All issues: `python3 -m unittest discover -s tests -q` (must stay OK).
- #144: `python3 -m unittest tests.test_paths -q`
- #145: `python3 -m unittest tests.test_paths tests.test_skills tests.test_managed -q`
- #146: `python3 -m unittest tests.test_service -q`; `bash -n desktop/install.sh desktop/build/after-install.sh`; compare generated unit text to the old heredoc.
- #147: `python3 -c "import json;json.load(open('desktop/package.json'))"`; `bash -n desktop/scripts/fetch-python.sh`; `sh desktop/scripts/fetch-python.sh --dry-run`; `node --check desktop/main.js`; `node --test desktop/` (if node tests added); `shellcheck` if installed.
- #148: `node --check desktop/main.js`; `node --test desktop/`.
- Cannot be verified without a Mac: the .app build, ad-hoc signing, Gatekeeper open, launchd bootstrap, Documents-folder prompt, Dock activate, menu behaviour. The owner checks these on the M2.
- Do not edit STATUS.md in sub-PRs; the Finish agent does.
