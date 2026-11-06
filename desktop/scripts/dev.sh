#!/bin/sh
# Development only: run the desktop app from this clone, no .deb and no sudo. Run: sh desktop/scripts/dev.sh
# Edit tokscope/, close the window, run it again to see the change.
# The installed background service (port 8770) would serve the old code, so it is stopped first; with it stopped the
# app starts its own server from this clone and stops it when the window closes. Put it back afterwards with:
#   systemctl --user start tokscope.service
set -eu
cd "$(dirname "$(readlink -f "$0")")/.."
[ -d node_modules ] || npm install --no-audit --no-fund
systemctl --user stop tokscope.service 2>/dev/null || true
# --no-sandbox: same reason as install.sh (the downloaded chrome-sandbox is not setuid)
exec ./node_modules/electron/dist/electron --no-sandbox .
