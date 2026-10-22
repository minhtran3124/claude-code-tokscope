#!/bin/sh
# Install the desktop app: npm install, then a launcher in the app menu (pin it from there).
# Safe to run again. Undo with: desktop/install.sh --uninstall
set -eu

HERE=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ENTRY="$APPS/tokscope.desktop"

if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$ENTRY"
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" 2>/dev/null || true
  echo "removed $ENTRY"
  exit 0
fi

command -v npm >/dev/null 2>&1 || { echo "error: npm (Node.js) is required" >&2; exit 1; }
(cd "$HERE" && npm install --no-audit --no-fund)

mkdir -p "$APPS"
cat > "$ENTRY" <<DESKTOP
[Desktop Entry]
Type=Application
Name=tokscope
Comment=Token usage per skill, subagent and phase for Claude Code
Exec=$HERE/node_modules/.bin/electron $HERE
Icon=$HERE/icon.svg
Terminal=false
Categories=Development;Utility;
StartupWMClass=tokscope-desktop
DESKTOP
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" 2>/dev/null || true
echo "installed $ENTRY: open tokscope from the app menu, then right-click its icon and choose Add to Favorites"
