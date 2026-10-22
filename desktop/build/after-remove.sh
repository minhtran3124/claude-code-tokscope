#!/bin/sh
# Runs as root after the .deb is removed.
set -e
if command -v systemctl >/dev/null 2>&1; then
  systemctl --global disable tokscope.service >/dev/null 2>&1 || true
fi
rm -f /usr/lib/systemd/user/tokscope.service
