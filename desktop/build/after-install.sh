#!/bin/sh
# Runs as root after the .deb is installed: a systemd user service that keeps `tokscope serve` on 127.0.0.1:8770.
set -e
install -d /usr/lib/systemd/user
cat > /usr/lib/systemd/user/tokscope.service <<'UNIT'
[Unit]
Description=tokscope dashboard server (127.0.0.1:8770)

[Service]
ExecStart=/opt/tokscope/resources/bin/tokscope serve --no-open --port 8770
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
UNIT
# on for every user from their next login (a session that is already open: systemctl --user start tokscope)
if command -v systemctl >/dev/null 2>&1; then
  systemctl --global enable tokscope.service >/dev/null 2>&1 || true
fi
# the setuid sandbox helper: electron-builder's own script does this too, repeated so the .deb never depends on it
chmod 4755 /opt/tokscope/chrome-sandbox 2>/dev/null || true
