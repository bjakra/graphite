# shellcheck shell=bash
# Shared helpers for build.sh / update.sh / dev.sh. Source, don't execute.

GRAPHITE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export GRAPHITE_ROOT
# shellcheck source=../../graphite.conf
source "$GRAPHITE_ROOT/graphite.conf"
[[ -f "$GRAPHITE_ROOT/graphite.local.conf" ]] && source "$GRAPHITE_ROOT/graphite.local.conf"

export PATH="$GRAPHITE_ROOT/tools/bin:$PATH"
export GRAPHITE_SRC="$SRC_DIR" GRAPHITE_DEVICE="$DEVICE" GRAPHITE_KERNEL_PROJECT="$KERNEL_PROJECT"
MANIFEST_URL="https://github.com/GrapheneOS/platform_manifest.git"
LOG_DIR="$GRAPHITE_ROOT/logs"
STATE_DIR="$GRAPHITE_ROOT/state"
mkdir -p "$LOG_DIR" "$STATE_DIR"

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    _B=$'\e[1m' _R=$'\e[1;31m' _G=$'\e[1;32m' _Y=$'\e[1;33m' _C=$'\e[1;34m' _N=$'\e[0m'
else
    _B="" _R="" _G="" _Y="" _C="" _N=""
fi
log()  { printf '%s==>%s %s\n' "$_C" "$_N" "$*"; }
ok()   { printf '%s ✓ %s %s\n' "$_G" "$_N" "$*"; }
warn() { printf '%sWARNING:%s %s\n' "$_Y" "$_N" "$*" >&2; }
die()  { printf '%sERROR:%s %s\n' "$_R" "$_N" "$*" >&2; exit 1; }
step() { printf '\n%s━━ %s ━━%s\n' "$_B" "$*" "$_N"; }

patchctl() { python3 -I "$GRAPHITE_ROOT/tools/graphite/patchctl.py" "$@"; }

# --- version pin (lives in build.sh so the build script is self-describing) ---
pinned_tag() {
    sed -n 's/^PINNED_TAG="\([^"]*\)".*/\1/p' "$GRAPHITE_ROOT/build.sh" | head -n1
}
set_pinned_tag() {
    local tag=$1
    [[ $tag =~ ^[0-9]{10}$ ]] || die "not a GrapheneOS release tag: $tag"
    sed -i "s/^PINNED_TAG=\"[^\"]*\"/PINNED_TAG=\"$tag\"/" "$GRAPHITE_ROOT/build.sh"
    [[ $(pinned_tag) == "$tag" ]] || die "failed to update PINNED_TAG in build.sh"
}
tree_tag() {
    git -C "$SRC_DIR/.repo/manifests" describe --tags --exact-match 2>/dev/null || true
}

# --- resources -------------------------------------------------------------------
auto_jobs() {
    if [[ -n "$JOBS" ]]; then echo "$JOBS"; return; fi
    local mem_gb cpus j
    mem_gb=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo)
    cpus=$(nproc)
    j=$(( mem_gb / 2 ))
    (( j < 2 )) && j=2
    (( j > cpus )) && j=$cpus
    echo "$j"
}
nice_cmd() {
    if [[ "$NICE_BUILDS" == 1 ]]; then echo "nice -n 10 ionice -c 3"; fi
}
free_gib() { df -BG --output=avail "$1" | tail -n1 | tr -dc '0-9'; }
check_space() {
    local dir=$1 need=$2 what=$3 have
    have=$(free_gib "$dir")
    if (( have < need )); then
        warn "only ${have} GiB free on $(df --output=target "$dir" | tail -n1) — $what needs ~${need} GiB"
        return 1
    fi
    return 0
}
# Prints "effective ram disk_swap zram" in GiB. zram is compressed RAM, not extra
# capacity, so it only counts at ~1/3 of its nominal size.
effective_mem_gib() {
    awk 'FILENAME=="/proc/meminfo" && /MemTotal/ {ram=$2}
         FILENAME=="/proc/swaps" && FNR>1 { if ($1 ~ /zram/) z+=$3; else d+=$3 }
         END {printf "%d %d %d %d\n", (ram+d+z/3)/1048576, ram/1048576, d/1048576, z/1048576}' \
        /proc/meminfo /proc/swaps
}
check_memory() {
    local eff ram disk zram
    read -r eff ram disk zram < <(effective_mem_gib)
    (( eff >= 40 )) && return 0
    warn "memory: ${ram} GiB RAM + ${disk} GiB disk swap + ${zram} GiB zram ≈ ${eff} GiB usable." \
         "Soong analysis of the full tree needs well over 30 GiB and gets OOM-killed below ~40 GiB."
    [[ ${GRAPHITE_IGNORE_MEMORY:-0} == 1 ]] && return 0
    cat >&2 <<'MSG'
Add a disk swapfile (one-time, needs root; /SSD-1TB is LUKS-encrypted so swap stays encrypted):
    sudo btrfs subvolume create /SSD-1TB/swap
    sudo btrfs filesystem mkswapfile --size 48g /SSD-1TB/swap/swapfile
    sudo swapon --priority 1 /SSD-1TB/swap/swapfile        # zram keeps its higher priority
    echo '/SSD-1TB/swap/swapfile none swap defaults,pri=1 0 0' | sudo tee -a /etc/fstab
(or set GRAPHITE_IGNORE_MEMORY=1 to try anyway)
MSG
    die "not enough memory for an AOSP build"
}

# --- running things inside the AOSP build environment -----------------------------
# usage: in_build_env <lunch-target> <out-dir> <command string>
in_build_env() {
    local target=$1 outdir=$2 cmd=$3
    ( cd "$SRC_DIR" && OUT_DIR="$outdir" bash -c "
        set -eo pipefail
        source build/envsetup.sh >/dev/null
        if [[ -n '$target' ]]; then lunch '$target' >/dev/null; fi
        $cmd" )
}
device_lunch() { echo "${DEVICE}-${RELEASE_CONFIG}-${VARIANT}"; }
emu_lunch() { echo "${EMU_TARGET}-${RELEASE_CONFIG}-${EMU_VARIANT}"; }

# --- container re-exec (GRAPHITE_CONTAINER=1) ------------------------------------
maybe_reexec_in_container() {
    [[ "$GRAPHITE_CONTAINER" == 1 ]] || return 0
    [[ -f /run/.containerenv || -f /.dockerenv ]] && return 0
    command -v podman >/dev/null || die "GRAPHITE_CONTAINER=1 but podman is not installed"
    "$GRAPHITE_ROOT/tools/container/run.sh" "$0" "$@"
    exit $?
}

need_tools() {
    local missing=()
    for t in "$@"; do command -v "$t" >/dev/null || missing+=("$t"); done
    (( ${#missing[@]} == 0 )) || die "missing tools: ${missing[*]}"
}
