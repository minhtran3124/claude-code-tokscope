#!/bin/sh
# One-step setup from a clone: link the CLI into ~/.local/bin and register the mod in Claude Code.
# It also keeps the dashboard server running in the background from login (systemd or launchd). Skip that with
# --no-service or TOKSCOPE_NO_SERVICE=1. Safe to run again. Undo with: ./setup.sh --uninstall
set -eu

ROOT=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
BIN_DIR="$HOME/.local/bin"
SETTINGS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"

command -v python3 >/dev/null 2>&1 || { echo "error: python3 (3.10 or later) is required" >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "error: Python 3.10 or later is required" >&2; exit 1; }

# add or remove the mod folder in the CLAUDE_CODE_PLUGIN_DIRS entry of settings.json (a path list)
edit_settings() {
  python3 -I - "$SETTINGS" "$ROOT/mod" "$1" <<'PY'
import json, os, shutil, sys

path, mod, action = sys.argv[1:4]
data = {}
if os.path.exists(path):
    with open(path) as f:
        data = json.load(f)
env = data.setdefault("env", {})
dirs = [d for d in env.get("CLAUDE_CODE_PLUGIN_DIRS", "").split(os.pathsep) if d]
want = list(dirs)
if action == "add" and mod not in want:
    want.append(mod)
elif action == "remove":
    want = [d for d in want if d != mod]
if want == dirs:
    print("mod: settings.json already up to date")
    sys.exit(0)
if os.path.exists(path):
    shutil.copy2(path, path + ".bak")
if want:
    env["CLAUDE_CODE_PLUGIN_DIRS"] = os.pathsep.join(want)
else:
    env.pop("CLAUDE_CODE_PLUGIN_DIRS", None)
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print("mod: %s %s (backup: %s.bak)" % ("added to" if action == "add" else "removed from", path, path))
PY
}

# the background service (tokscope service install|uninstall); best effort, never stops the setup
service() {
  "$ROOT/bin/tokscope" service "$1" --exe "$ROOT/bin/tokscope" --quote-exe
}

if [ "${1:-}" = "--uninstall" ]; then
  service uninstall >/dev/null 2>&1 || true
  [ "$(readlink -f "$BIN_DIR/tokscope" 2>/dev/null)" = "$ROOT/bin/tokscope" ] && rm "$BIN_DIR/tokscope" && echo "cli: removed $BIN_DIR/tokscope"
  edit_settings remove
  echo "Your data stays in $ROOT/data. Delete it yourself if you want it gone."
  exit 0
fi

mkdir -p "$BIN_DIR"
ln -sfn "$ROOT/bin/tokscope" "$BIN_DIR/tokscope"
echo "cli: linked $BIN_DIR/tokscope -> $ROOT/bin/tokscope"
edit_settings add
if [ "${1:-}" = "--no-service" ] || [ -n "${TOKSCOPE_NO_SERVICE:-}" ]; then
  echo "service: skipped (turn it on with: tokscope service install)"
elif service install >/dev/null 2>&1; then
  echo "service: tokscope serve runs in the background from login (http://127.0.0.1:8770, stop it with: tokscope service uninstall)"
else
  echo "service: not started (needs systemd --user or launchd); run 'tokscope serve' by hand"
fi

"$BIN_DIR/tokscope" --version
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "note: $BIN_DIR is not on your PATH. Add it to run 'tokscope' from any folder." ;;
esac
echo "Done. Start a new Claude Code session to load the mod, then run: tokscope ingest"
