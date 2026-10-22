#!/bin/sh
# Install the desktop app: npm install, then a launcher in the app menu (pin it from there).
# Safe to run again. Undo with: desktop/install.sh --uninstall
set -eu

HERE=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ENTRY="$APPS/tokscope.desktop"

if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$ENTRY"
  rm -rf "$HERE/node_modules"
  # take it off the GNOME dock too, if it was pinned there
  if command -v gsettings >/dev/null 2>&1; then
    favs=$(gsettings get org.gnome.shell favorite-apps 2>/dev/null || true)
    case "$favs" in
      *"'tokscope.desktop'"*) gsettings set org.gnome.shell favorite-apps "$(printf '%s' "$favs" | sed "s/, 'tokscope.desktop'//; s/'tokscope.desktop', //; s/'tokscope.desktop'//")" ;;
    esac
  fi
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" 2>/dev/null || true
  echo "removed $ENTRY and desktop/node_modules"
  exit 0
fi

command -v npm >/dev/null 2>&1 || { echo "error: npm (Node.js) is required" >&2; exit 1; }
(cd "$HERE" && npm install --no-audit --no-fund)

# the electron binary itself: the .bin/electron script needs `node` on the PATH, which the app menu does not give.
# --no-sandbox: the downloaded chrome-sandbox is not setuid, and Ubuntu 24.04 blocks the user-namespace fallback.
# The window only loads the loopback dashboard; every other link opens in your browser.
EXEC="$HERE/node_modules/electron/dist/electron"
[ -x "$EXEC" ] || { echo "error: $EXEC is missing; npm install did not finish" >&2; exit 1; }
case "$HERE" in *[\"\\\`\$%]*) echo "error: the folder path has a quote, backslash, backtick, dollar or percent sign; move the clone" >&2; exit 1;; esac

mkdir -p "$APPS"
cat > "$ENTRY" <<DESKTOP
[Desktop Entry]
Type=Application
Name=tokscope
Comment=Token usage per skill, subagent and phase for Claude Code
Exec="$EXEC" --no-sandbox "$HERE"
Icon=$HERE/icon.svg
Terminal=false
Categories=Development;Utility;
StartupWMClass=tokscope-desktop
DESKTOP
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" 2>/dev/null || true
echo "installed $ENTRY: open tokscope from the app menu, then right-click its icon and choose Add to Favorites"
