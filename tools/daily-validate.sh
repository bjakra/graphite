#!/usr/bin/env bash
# Daily check: do Graphite's patches still apply to the newest GrapheneOS release?
# Runs './update.sh validate' (read-only, safe during builds), keeps the log in logs/, and shows a
# desktop notification when a patch breaks. Installed as a systemd user timer by
# tools/systemd/install-daily-validate.sh.
G="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
log="$G/logs/daily-validate-$(date +%Y%m%d).log"
cd "$G" || exit 1
./update.sh validate > "$log" 2>&1
rc=$?
case $rc in
    0) msg="All Graphite patches apply to the newest GrapheneOS release." ;;
    3) msg="Only optional Graphite patches broke on the newest GrapheneOS release. See $log" ;;
    *) msg="Graphite patch validation failed (exit $rc). See $log and reports/." ;;
esac
echo "$msg" >> "$log"
if ((rc != 0)) && command -v notify-send >/dev/null; then
    notify-send -a Graphite "Graphite update check" "$msg" || true
fi
exit $rc
