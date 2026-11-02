#!/usr/bin/env bash
# Push the emulator build's partitions (default: system_ext) and soft-restart Android.
# Starts the emulator (with a window) first if it isn't running. Every wait has a timeout,
# so a closed emulator makes this fail instead of hanging.
set -uo pipefail
G="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"; A="$G/sdk/platform-tools/adb"
BOOT_TIMEOUT=${BOOT_TIMEOUT:-420}
# A connected phone must not make adb ambiguous, or get pushed to by mistake
export ANDROID_SERIAL=${EMU_SERIAL:-emulator-5554}

emu_online() { "$A" devices 2>/dev/null | grep -qE '^emulator-[0-9]+\s+device$'; }
booted() { [[ $(timeout 10 "$A" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r') == 1 ]]; }
wait_booted() {
    local end=$((SECONDS + BOOT_TIMEOUT))
    while ((SECONDS < end)); do
        emu_online && booted && return 0
        pgrep -f '^[^ ]*qemu-system-x86_64' >/dev/null || { echo "emulator process is gone"; return 1; }
        sleep 3
    done
    echo "emulator did not finish booting within ${BOOT_TIMEOUT}s"; return 1
}

if ! pgrep -f '^[^ ]*qemu-system-x86_64' >/dev/null; then
    echo "emulator not running: starting it (window)"
    (cd "$G" && setsid nohup ./dev.sh run > "$G/logs/dev-run.log" 2>&1 < /dev/null &)
    # dev.sh loads the build environment first; qemu appears after ~10-60 s
    for _ in $(seq 60); do pgrep -f '^[^ ]*qemu-system-x86_64' >/dev/null && break; sleep 2; done
fi
wait_booted || exit 1

if [[ ${1:-} != --no-push ]]; then
    timeout 600 bash -c "cd '$G' && ./dev.sh push ${*:-system_ext}" 2>&1 | grep -E 'pushed|error|failed|remount' | cut -c1-160
    ((PIPESTATUS[0] == 0)) || { echo "push failed or timed out"; exit 1; }
    wait_booted || exit 1      # the first push may reboot to disable verity
fi
timeout 20 "$A" shell stop; timeout 20 "$A" shell start
sleep 8
wait_booted || exit 1
timeout 10 "$A" shell input keyevent WAKEUP; timeout 10 "$A" shell wm dismiss-keyguard
echo "deployed and restarted"
