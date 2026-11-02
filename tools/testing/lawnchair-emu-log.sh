#!/usr/bin/env bash
# Restart the installed Lawnchair on the emulator and print any crash from its startup.
G="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"; A="$G/sdk/platform-tools/adb"
"$A" logcat -c
"$A" shell am force-stop app.lawnchair.debug
"$A" shell am start -a android.intent.action.MAIN -c android.intent.category.HOME >/dev/null 2>&1
"$A" shell sleep "${1:-10}"
L="$G/logs/lawnchair-emu.log"; "$A" logcat -d -v brief > "$L"
grep -E 'FATAL EXCEPTION' -A3 "$L" | head -4 | cut -c1-170
grep -E 'Caused by' "$L" | awk '!s[$0]++' | head -6 | cut -c1-210
grep -E 'E/AndroidRuntime.*\bat (com\.android\.(launcher3|quickstep|systemui|wm)|app\.lawnchair)' "$L" | head -"${2:-14}" | cut -c1-150
echo "top: $("$A" shell dumpsys activity activities | grep -m1 topResumedActivity | cut -c1-110)"
echo "pid: $("$A" shell pidof app.lawnchair.debug)"
