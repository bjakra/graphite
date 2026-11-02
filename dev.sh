#!/usr/bin/env bash
# Graphite development loop: rebuild single components and push them into a
# running emulator (default) or a userdebug phone (--device), instead of
# rebuilding/reflashing the whole OS.
#
#   ./dev.sh build              full build of the emulator target (first time: hours)
#   ./dev.sh run                start the emulator in the background (writable /system)
#   ./dev.sh quick Settings     m Settings → adb sync → restart Android
#   ./dev.sh shell              bash with envsetup + lunch done (use m/mm/mmm freely)
#   ./dev.sh --device quick SystemUI   same against a USB-connected husky userdebug build
#
# Run './dev.sh help' for everything.

set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/tools/lib/common.sh"

MODE=emu
if [[ ${1:-} == --device ]]; then MODE=device; shift; fi
if [[ $MODE == emu ]]; then
    TARGET=$(emu_lunch) OUTDIR=$EMU_OUT_DIR ADB_SEL=(-e)
else
    TARGET="${DEVICE}-${RELEASE_CONFIG}-userdebug" OUTDIR=$DEVICE_OUT_DIR ADB_SEL=(-d)
fi
[[ -n ${ANDROID_SERIAL:-} ]] && ADB_SEL=(-s "$ANDROID_SERIAL")
OUT_ABS=$([[ $OUTDIR = /* ]] && echo "$OUTDIR" || echo "$SRC_DIR/$OUTDIR")

usage() {
    cat <<EOF
Usage: $0 [--device] COMMAND [args]

Target: $TARGET   out: $OUT_ABS
(--device switches to ${DEVICE}-${RELEASE_CONFIG}-userdebug and a USB-connected phone)

Commands:
  build [MODULE...]      no args: full build (needed once). With args: m MODULE...
  run [--fg] [--wipe] [--headless]
                         start the emulator (background by default, waits for boot)
  stop                   kill the emulator
  push [PARTITION...]    adb root/remount + adb sync (default: system system_ext product vendor)
  quick MODULE...        build MODULE(s), push, soft-restart Android
  restart                soft restart (stop/start zygote) — enough for framework/app changes
  reboot                 full reboot of the target
  install APK|MODULE     adb install -r (for non-system apps)
  shell [CMD...]         interactive bash in the build env, or run CMD there
  adb ARGS...            adb against the selected target
  logcat [ARGS...]       adb logcat
  flash [--wipe]         (--device) fastboot flashall the dev build (unlocked bootloader!)
  status                 what's built / running
  modules PATH           list module names defined under a source path

Patch workflow: edit code in src/<project>, 'git commit' there, test with 'quick',
then 'tools/patchctl export <patch-id> --project <project> --new'. See AGENTS.md.
EOF
}

product_out() {
    if [[ $MODE == device ]]; then echo "$OUT_ABS/target/product/$DEVICE"; return; fi
    local d
    d=$(ls -1td "$OUT_ABS"/target/product/*/ 2>/dev/null | head -n1)
    echo "${d%/}"
}
adb_bin() {
    if [[ -x $OUT_ABS/host/linux-x86/bin/adb ]]; then echo "$OUT_ABS/host/linux-x86/bin/adb"
    else command -v adb || die "adb not found"; fi
}
ADB() { "$(adb_bin)" "${ADB_SEL[@]}" "$@"; }

wait_boot() {
    log "waiting for boot"
    ADB wait-for-device
    local i
    for i in $(seq 1 180); do
        [[ $(ADB shell getprop sys.boot_completed 2>/dev/null | tr -d '\r') == 1 ]] && { ok "booted"; return; }
        sleep 2
    done
    die "target did not finish booting"
}

ensure_root_remount() {
    ADB root >/dev/null 2>&1 || true
    ADB wait-for-device
    local out
    out=$(ADB remount 2>&1 || true)
    if grep -qiE 'reboot|verity' <<<"$out" && ! grep -qi 'remount succeeded' <<<"$out"; then
        log "first remount: disabling verity needs a reboot"
        ADB reboot
        wait_boot
        ADB root >/dev/null 2>&1 || true
        ADB wait-for-device
        out=$(ADB remount 2>&1) || die "adb remount failed: $out"
    fi
    grep -qi 'succeeded\|remounted' <<<"$out" || { echo "$out"; warn "remount output unexpected (see above)"; }
}

cmd_build() {
    local jobs; jobs=$(auto_jobs)
    if (( $# == 0 )); then
        check_memory
        [[ $MODE == device && ! -d $SRC_DIR/vendor/google_devices/$DEVICE ]] && die "run ./build.sh --only vendor first"
        log "full build of $TARGET into $OUT_ABS (first one takes hours)"
        in_build_env "$TARGET" "$OUTDIR" "$(nice_cmd) m -j$jobs" 2>&1 | tee "$LOG_DIR/dev-build-$MODE-$(date +%Y%m%d-%H%M%S).log"
    else
        log "m $*"
        in_build_env "$TARGET" "$OUTDIR" "$(nice_cmd) m -j$jobs $*"
    fi
}

cmd_run() {
    [[ $MODE == emu ]] || die "run is for the emulator"
    local fg=0 extra=()
    while (( $# )); do
        case $1 in
            --fg) fg=1 ;;
            --wipe) extra+=(-wipe-data) ;;
            --headless) extra+=(-no-window) ;;
            *) extra+=("$1") ;;
        esac
        shift
    done
    [[ -n $(product_out) && -f $(product_out)/system.img ]] || die "no emulator build yet — run: ./dev.sh build"
    # the AOSP emulator's Qt has no Wayland plugin; use XWayland
    local qt=""
    [[ -n ${WAYLAND_DISPLAY:-} && -n ${DISPLAY:-} ]] && qt="QT_QPA_PLATFORM=xcb"
    local cmd="$qt emulator -writable-system -no-snapshot -memory $EMU_MEMORY_MB -cores $EMU_CORES -gpu ${EMU_GPU:-swiftshader_indirect} ${extra[*]}"
    if (( fg )); then in_build_env "$TARGET" "$OUTDIR" "$cmd"; return; fi
    local log_file="$LOG_DIR/emulator.log"
    log "starting emulator in background (log: $log_file)"
    nohup bash -c "$(declare -f in_build_env); SRC_DIR='$SRC_DIR'; in_build_env '$TARGET' '$OUTDIR' '$cmd'" \
        > "$log_file" 2>&1 &
    echo $! > "$STATE_DIR/emulator.pid"
    wait_boot
}

cmd_stop() {
    ADB emu kill 2>/dev/null || true
    [[ -f $STATE_DIR/emulator.pid ]] && { kill "$(cat "$STATE_DIR/emulator.pid")" 2>/dev/null || true; rm -f "$STATE_DIR/emulator.pid"; }
    ok "emulator stopped"
}

cmd_push() {
    local parts=("$@") po
    (( ${#parts[@]} )) || parts=(system system_ext product vendor)
    po=$(product_out)
    [[ -d $po ]] || die "nothing built in $po"
    ensure_root_remount
    log "adb sync ${parts[*]}"
    local p
    for p in "${parts[@]}"; do
        ANDROID_PRODUCT_OUT="$po" ADB sync "$p"
    done
}

cmd_restart() { log "soft restart"; ADB shell stop; ADB shell start; wait_boot; }

cmd_quick() {
    (( $# )) || die "usage: quick MODULE..."
    cmd_build "$@"
    cmd_push
    cmd_restart
    ok "$* deployed"
}

cmd_install() {
    local a=$1
    if [[ ! -f $a ]]; then
        a=$(find "$(product_out)" -name "$1.apk" -print -quit)
        [[ -n $a ]] || die "no APK for $1 in $(product_out)"
    fi
    ADB install -r -d "$a"
}

cmd_shell() {
    if (( $# )); then in_build_env "$TARGET" "$OUTDIR" "$*"; return; fi
    local rc
    rc=$(mktemp)
    cat > "$rc" <<EOF
[[ -f ~/.bashrc ]] && source ~/.bashrc
cd "$SRC_DIR"
export OUT_DIR="$OUTDIR"
source build/envsetup.sh >/dev/null
lunch $TARGET
PS1="(graphite $TARGET) \w \$ "
echo "Build env ready: m <module>, mm, mmm <dir>, croot ... (exit to leave)"
EOF
    bash --rcfile "$rc" -i
    rm -f "$rc"
}

cmd_flash() {
    [[ $MODE == device ]] || die "flash is for --device"
    local wipe=()
    [[ ${1:-} == --wipe ]] && wipe=(-w)
    local po; po=$(product_out)
    [[ -f $po/android-info.txt ]] || die "no device build in $po"
    cat <<EOF
This flashes the dev build (test keys) to the phone in fastboot mode.
Bootloader must be unlocked. Firmware (bootloader/radio) is NOT updated by this —
install a matching official GrapheneOS factory image first so firmware matches.
EOF
    read -rp "Continue? [y/N] " a; [[ $a == [yY]* ]] || exit 1
    local fb="$OUT_ABS/host/linux-x86/bin/fastboot"; [[ -x $fb ]] || fb=fastboot
    ANDROID_PRODUCT_OUT="$po" "$fb" flashall "${wipe[@]}"
}

cmd_status() {
    echo "target      : $TARGET"
    echo "out dir     : $OUT_ABS"
    local po; po=$(product_out)
    if [[ -n $po && -f $po/system.img ]]; then
        echo "built       : $po ($(date -r "$po/system.img" '+%F %T'))"
    else
        echo "built       : no (run ./dev.sh $( [[ $MODE == device ]] && echo '--device ')build)"
    fi
    echo "adb devices :"; "$(adb_bin)" devices -l | tail -n +2 | sed 's/^/    /'
}

cmd_modules() {
    local path=${1:?path relative to src, e.g. packages/apps/Settings}
    grep -rhoE '^\s*name:\s*"[^"]+"' --include=Android.bp "$SRC_DIR/$path" | sed -E 's/.*"([^"]+)"/\1/' | sort -u
    grep -rhoE 'LOCAL_(PACKAGE|MODULE)\s*:=\s*\S+' --include=Android.mk "$SRC_DIR/$path" 2>/dev/null | awk '{print $NF}' | sort -u
}

cmd=${1:-help}; shift || true
case $cmd in
    build) cmd_build "$@" ;;
    run) cmd_run "$@" ;;
    stop) cmd_stop ;;
    push) cmd_push "$@" ;;
    quick) cmd_quick "$@" ;;
    restart) cmd_restart ;;
    reboot) ADB reboot; wait_boot ;;
    install) cmd_install "$@" ;;
    shell) cmd_shell "$@" ;;
    adb) ADB "$@" ;;
    logcat) ADB logcat "$@" ;;
    flash) cmd_flash "$@" ;;
    status) cmd_status ;;
    modules) cmd_modules "$@" ;;
    help|-h|--help) usage ;;
    *) usage; exit 1 ;;
esac
