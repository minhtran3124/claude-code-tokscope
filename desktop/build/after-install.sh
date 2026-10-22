#!/bin/sh
# Runs as root after the .deb is installed: the systemd user service file for `tokscope serve` on 127.0.0.1:8770.
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
# Not enabled here: another user on a shared machine could then reach this user's dashboard on the fixed port.
# Each person turns it on once with: systemctl --user enable --now tokscope
# the setuid sandbox helper: electron-builder's own script does this too, repeated so the .deb never depends on it
chmod 4755 /opt/tokscope/chrome-sandbox 2>/dev/null || true
