#!/usr/bin/env bash
# Graphite build script: builds exactly the pinned GrapheneOS version + patches.
#
#   ./build.sh                 sync → patch → vendor files → build (dev images)
#   ./build.sh --release       ... → target-files → signed factory images + OTA (needs keys)
#   ./build.sh --only patch    run a single step (preflight|sync|patch|vendor|build|release)
#   ./build.sh --from vendor   start at a step
#   ./build.sh -h              all options
#
# The version is pinned below and changed ONLY by ./update.sh (which validates
# patches first and keeps a rollback snapshot). A new upstream release can't
# break this script by itself.

PINNED_TAG="2026103100"   # managed by update.sh — do not edit by hand

set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/tools/lib/common.sh"
ORIG_ARGS=("$@")

STEPS=(preflight sync patch vendor build release)
usage() {
    cat <<EOF
Usage: $0 [options]

Builds GrapheneOS tag $PINNED_TAG + patches/ for $DEVICE.

Steps: ${STEPS[*]}   ('release' only runs with --release)

Options:
  --release            build target-files and sign factory images / OTA with keys/$DEVICE
  --variant V          user | userdebug | eng   (default from graphite.conf: $VARIANT)
  --only STEP[,STEP]   run only these steps
  --from STEP          start at STEP
  --skip-sync          don't touch the network (same as --from patch, but runs preflight)
  --skip-optional      failing optional patches are skipped without asking
  --force              discard uncommitted changes / foreign commits in patched projects
  --force-vendor       re-run adevtool even if vendor files look current
  --jobs N             parallel build jobs (default: $(auto_jobs), from RAM)
  --clean              delete the device out dir before building
  -h, --help           this help
EOF
}

RELEASE=0 ONLY="" FROM="" SKIP_OPTIONAL=0 FORCE=0 FORCE_VENDOR=0 CLEAN=0 SKIP_SYNC=0
while (( $# )); do
    case $1 in
        --release) RELEASE=1 ;;
        --variant) VARIANT=$2; shift ;;
        --only) ONLY=$2; shift ;;
        --from) FROM=$2; shift ;;
        --skip-sync) SKIP_SYNC=1 ;;
        --skip-optional) SKIP_OPTIONAL=1 ;;
        --force) FORCE=1 ;;
        --force-vendor) FORCE_VENDOR=1 ;;
        --jobs) JOBS=$2; shift ;;
        --clean) CLEAN=1 ;;
        -h|--help) usage; exit 0 ;;
        *) die "unknown option: $1 (see --help)" ;;
    esac
    shift
done
maybe_reexec_in_container "${ORIG_ARGS[@]}"

want() {
    local s=$1
    [[ $s == release && $RELEASE == 0 ]] && return 1
    if [[ -n $ONLY ]]; then [[ ",$ONLY," == *",$s,"* ]]; return; fi
    [[ $SKIP_SYNC == 1 && $s == sync ]] && return 1
    if [[ -n $FROM ]]; then
        local seen=0 x
        for x in "${STEPS[@]}"; do
            [[ $x == "$FROM" ]] && seen=1
            [[ $x == "$s" ]] && { (( seen )); return; }
        done
        die "unknown step: $FROM"
    fi
    return 0
}

BUILD_LOG="$LOG_DIR/build-$(date +%Y%m%d-%H%M%S).log"
TARGET=$(device_lunch)

# run a command, tee its output into the build log, return the command's status
run_logged() {
    set +e +o pipefail
    "$@" 2>&1 | tee -a "$BUILD_LOG"
    local rc=${PIPESTATUS[0]}
    set -e -o pipefail
    return "$rc"
}

# --- preflight -------------------------------------------------------------------
do_preflight() {
    step "preflight"
    need_tools git python3 curl zip unzip rsync openssl ssh-keygen
    python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || die "python >= 3.11 required"
    [[ -x "$GRAPHITE_ROOT/tools/bin/repo" ]] || die "tools/bin/repo missing (see README)"
    check_memory
    if [[ ! -d "$SRC_DIR/.repo" ]]; then
        check_space "$GRAPHITE_ROOT" 100 "a fresh source sync" || true
    fi
    check_space "$GRAPHITE_ROOT" 60 "a device build" || warn "the build may run out of disk space"
    ok "tag $PINNED_TAG, target $TARGET, $(auto_jobs) jobs"
}

# --- sync --------------------------------------------------------------------------
do_sync() {
    step "sync GrapheneOS $PINNED_TAG"
    mkdir -p "$SRC_DIR"
    if [[ -d "$SRC_DIR/.repo" ]]; then
        log "restoring patched projects to pristine state"
        if ((FORCE)); then patchctl reset --force; else patchctl reset; fi
    fi
    # Graphite's extra projects (manifests/*.xml) go in as local manifests
    mkdir -p "$SRC_DIR/.repo/local_manifests"
    rm -f "$SRC_DIR"/.repo/local_manifests/graphite-*.xml
    for m in "$GRAPHITE_ROOT"/manifests/*.xml; do
        [[ -e $m ]] && sed "s|@GRAPHITE_ROOT@|$GRAPHITE_ROOT|g" "$m" > "$SRC_DIR/.repo/local_manifests/graphite-$(basename "$m")"
    done
    if [[ $(tree_tag) != "$PINNED_TAG" ]]; then
        log "repo init → $PINNED_TAG"
        (cd "$SRC_DIR" && repo init -q -u "$MANIFEST_URL" -b "refs/tags/$PINNED_TAG" --depth=1 --no-clone-bundle)
    fi
    log "verifying the GrapheneOS tag signature"
    git -C "$SRC_DIR/.repo/manifests" -c gpg.ssh.allowedSignersFile="$GRAPHITE_ROOT/keys/trust/grapheneos_allowed_signers" \
        verify-tag "$PINNED_TAG" 2>&1 | sed 's/^/    /' || die "tag $PINNED_TAG failed signature verification!"
    log "repo sync (-j$SYNC_JOBS)"
    run_logged bash -c "cd '$SRC_DIR' && repo sync -q -c -j$SYNC_JOBS --no-tags --force-sync --optimized-fetch --fail-fast" \
        || die "repo sync failed (log: $BUILD_LOG). Re-running usually continues where it stopped."
    [[ $(tree_tag) == "$PINNED_TAG" ]] || die "tree is at '$(tree_tag)', expected $PINNED_TAG"
    ok "source tree at $PINNED_TAG"
}

# --- patch -------------------------------------------------------------------------
do_patch() {
    step "apply Graphite patches"
    [[ $(tree_tag) == "$PINNED_TAG" ]] || die "tree is at '$(tree_tag)' but build.sh pins $PINNED_TAG — run the sync step"
    local args=()
    ((SKIP_OPTIONAL)) && args+=(--skip-optional)
    ((FORCE)) && args+=(--force)
    patchctl apply "${args[@]}" || die "patching failed — see the explanation above and the report under reports/"
}

# --- vendor (adevtool) --------------------------------------------------------------
yarn_cmd() {
    if command -v yarnpkg >/dev/null; then echo yarnpkg
    elif command -v yarn >/dev/null; then echo yarn
    else echo "npx --yes yarn@1.22.22"; fi
}
do_vendor() {
    step "vendor files for $DEVICE (adevtool)"
    need_tools node
    local adev="$SRC_DIR/vendor/adevtool" stamp="$STATE_DIR/vendor-$DEVICE.stamp" want_stamp
    want_stamp="$(git -C "$adev" rev-parse HEAD) $DEVICE"
    if [[ $FORCE_VENDOR == 0 && -f $stamp && $(cat "$stamp") == "$want_stamp" \
          && -d "$SRC_DIR/vendor/google_devices/$DEVICE" ]]; then
        ok "vendor files current (adevtool $(cut -c1-12 <<<"$want_stamp")); --force-vendor to regenerate"
        return
    fi
    if [[ ! -d "$adev/node_modules" || "$adev/yarn.lock" -nt "$adev/node_modules" ]]; then
        log "installing adevtool dependencies"
        (cd "$adev" && $(yarn_cmd) install --frozen-lockfile) || die "yarn install in vendor/adevtool failed"
        touch "$adev/node_modules"
    fi
    log "adevtool generate-all -d $DEVICE (downloads the stock factory image on first run, several GiB)"
    run_logged in_build_env "" "$DEVICE_OUT_DIR" "vendor/adevtool/bin/run generate-all -d $DEVICE" \
        || die "adevtool failed (log: $BUILD_LOG)"
    echo "$want_stamp" > "$stamp"
    ok "vendor/google_devices/$DEVICE generated"
}

# --- build ---------------------------------------------------------------------------
build_targets() {
    if (( RELEASE )); then echo "vendorbootimage vendorkernelbootimage target-files-package otatools-package"
    else echo ""; fi   # plain 'm' = default target (flashable images)
}
do_build() {
    step "build $TARGET"
    [[ -d "$SRC_DIR/vendor/google_devices/$DEVICE" ]] || die "vendor files missing — run the vendor step"
    if (( CLEAN )); then
        log "removing $DEVICE_OUT_DIR"
        rm -rf "${SRC_DIR:?}/$DEVICE_OUT_DIR"
    fi
    local jobs extra=""
    jobs=$(auto_jobs)
    if [[ -n $UPDATE_URL ]]; then
        extra="export OFFICIAL_BUILD=true;"
        sed -i "s|<string name=\"url\" translatable=\"false\">[^<]*</string>|<string name=\"url\" translatable=\"false\">$UPDATE_URL</string>|" \
            "$SRC_DIR/packages/apps/Updater/res/values/config.xml"
    fi
    log "m -j$jobs $(build_targets)   (log: $BUILD_LOG)"
    local start=$SECONDS
    if ! run_logged in_build_env "$TARGET" "$DEVICE_OUT_DIR" "$extra $(nice_cmd) m -j$jobs $(build_targets)"; then
        warn "build failed after $(( (SECONDS - start) / 60 )) min"
        [[ -f "$SRC_DIR/$DEVICE_OUT_DIR/error.log" ]] && { echo "--- $DEVICE_OUT_DIR/error.log (tail) ---"; tail -n 40 "$SRC_DIR/$DEVICE_OUT_DIR/error.log"; }
        cat <<EOF

If the failure is in code touched by a Graphite patch, check 'tools/patchctl list' and the
patch's patch.toml. Rebuild just a module with: ./dev.sh --device build <module>
Full log: $BUILD_LOG
EOF
        exit 1
    fi
    ok "build finished in $(( (SECONDS - start) / 60 )) min"
    if (( ! RELEASE )); then
        cat <<EOF

Images: $SRC_DIR/$DEVICE_OUT_DIR/target/product/$DEVICE/
Flash (bootloader unlocked, test keys — development only):
    ./dev.sh --device flash
EOF
    fi
}

# --- release (signing) ----------------------------------------------------------------
do_release() {
    step "sign release for $DEVICE"
    local keys="$KEYS_DIR/$DEVICE"
    [[ -f "$keys/releasekey.x509.pem" && -f "$keys/avb.pem" ]] || die "no release keys in $keys — create them with tools/make-keys.sh $DEVICE"
    [[ "$DEVICE_OUT_DIR" == out ]] || die "GrapheneOS release scripts expect DEVICE_OUT_DIR=out"
    ln -sfn "$KEYS_DIR" "$SRC_DIR/keys"
    # GrapheneOS' decrypt-keys prompts unless $password is set; unencrypted keys need no prompt
    if [[ -z ${password+x} ]] && openssl pkcs8 -inform DER -nocrypt -in "$keys/releasekey.pk8" >/dev/null 2>&1; then
        export password=""
    fi
    local build_number
    build_number=$(cat "$SRC_DIR/out/soong/build_number.txt" 2>/dev/null || cat "$SRC_DIR/out/build_number.txt")
    run_logged in_build_env "$TARGET" "$DEVICE_OUT_DIR" "script/finalize.sh && script/generate-release.sh $DEVICE $build_number" \
        || die "signing failed (log: $BUILD_LOG)"
    ok "release: $SRC_DIR/releases/$build_number/release-$DEVICE-$build_number/"
}

echo "${_B}Graphite${_N} — GrapheneOS $PINNED_TAG for $DEVICE ($TARGET)$( ((RELEASE)) && echo ', release')"
for s in "${STEPS[@]}"; do
    want "$s" && "do_$s"
done
echo
ok "done"
