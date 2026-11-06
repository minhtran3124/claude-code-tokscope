#!/bin/sh
# Runs as root after the .deb is installed: the systemd user service file for `tokscope serve` on 127.0.0.1:8770.
set -e
install -d /usr/lib/systemd/user
/opt/tokscope/resources/bin/tokscope service install --unit-file /usr/lib/systemd/user/tokscope.service \
  --exe /opt/tokscope/resources/bin/tokscope >/dev/null
# Not enabled here: another user on a shared machine could then reach this user's dashboard on the fixed port.
# The app turns it on for its user at the first launch (desktop/autostart.js); by hand: systemctl --user enable --now tokscope
# the setuid sandbox helper: electron-builder's own script does this too, repeated so the .deb never depends on it
chmod 4755 /opt/tokscope/chrome-sandbox 2>/dev/null || true
