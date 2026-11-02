#!/usr/bin/env bash
# Install and start the daily patch-validation timer as a systemd *user* unit.
# Remove again with: systemctl --user disable --now graphite-validate.timer
set -euo pipefail
G="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
d="$HOME/.config/systemd/user"
mkdir -p "$d"
cat > "$d/graphite-validate.service" <<UNIT
[Unit]
Description=Graphite: validate patches against the newest GrapheneOS release

[Service]
Type=oneshot
Nice=15
ExecStart=$G/tools/daily-validate.sh
UNIT
cat > "$d/graphite-validate.timer" <<UNIT
[Unit]
Description=Graphite: daily patch validation

[Timer]
OnCalendar=daily
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now graphite-validate.timer
systemctl --user list-timers graphite-validate.timer --no-pager
