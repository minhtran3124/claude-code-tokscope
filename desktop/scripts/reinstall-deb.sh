#!/bin/sh
# Rebuild the .deb and install it over the current one. Run: sh desktop/scripts/reinstall-deb.sh
set -eu
cd "$(dirname "$(readlink -f "$0")")/.."
[ -d node_modules ] || npm install --no-audit --no-fund
npm run dist
sudo apt install -y --reinstall ./dist/tokscope_*_amd64.deb
# the background service keeps the old code in memory; restart it (only when it is running) so the new build shows
systemctl --user try-restart tokscope.service 2>/dev/null || true
