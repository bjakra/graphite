#!/usr/bin/env bash
# Graphite update script: moves the GrapheneOS pin in build.sh — safely.
#
#   ./update.sh status               current pin vs. newest GrapheneOS release
#   ./update.sh validate [TAG]       test all patches against TAG (default: latest), no changes
#   ./update.sh apply [TAG]          validate, snapshot, then bump PINNED_TAG in build.sh
#   ./update.sh rollback [ID|N]      restore pin + patches from a snapshot (default: before last update)
#   ./update.sh history              list snapshots / past updates
#   ./update.sh fix PATCH [TAG]      open a fix workspace for a broken patch (see AGENTS.md)
#
# validate never touches src/ (patches are test-applied into temporary git
# indexes), so it is safe to run while a build is running.

set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/tools/lib/common.sh"

SNAP_DIR="$STATE_DIR/snapshots"
HISTORY="$STATE_DIR/history.log"
mkdir -p "$SNAP_DIR"

usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; }

resolve_tag() {
    local t=${1:-latest}
    if [[ $t == latest ]]; then patchctl latest-tag; else
        [[ $t =~ ^[0-9]{10}$ ]] || die "not a GrapheneOS release tag: $t (expected e.g. 2026103100)"
        echo "$t"
    fi
}

cmd_status() {
    local pin latest tree
    pin=$(pinned_tag); tree=$(tree_tag)
    latest=$(patchctl latest-tag)
    echo "pinned in build.sh : $pin"
    echo "source tree        : ${tree:-not synced}"
    echo "latest GrapheneOS  : $latest"
    if [[ $latest == "$pin" ]]; then ok "up to date"
    else
        log "newer releases:"
        git ls-remote --tags "$MANIFEST_URL" | grep -oE 'refs/tags/[0-9]{10}$' | cut -d/ -f3 | sort -n \
            | awk -v p="$pin" '$1 > p {print "    " $1}'
        echo "Next: ./update.sh validate   (then ./update.sh apply)"
        echo "Release notes: https://grapheneos.org/releases"
    fi
    local last
    last=$(ls -1 "$SNAP_DIR" 2>/dev/null | sort | tail -n1)
    [[ -n $last ]] && echo "last snapshot      : $last (./update.sh rollback)"
    return 0
}

# run validation; sets VALIDATE_RC (0 ok, 3 optional broken, 2 required broken / sanity, 1 error)
VALIDATE_RC=0
run_validate() {
    local tag=$1; shift
    local report="$GRAPHITE_ROOT/reports/validate-$tag"
    set +e
    patchctl validate --tag "$tag" --base-tag "$(pinned_tag)" --report-dir "$report" \
        --device "$DEVICE" --kernel-project "$KERNEL_PROJECT" "$@"
    VALIDATE_RC=$?
    set -e
    REPORT_DIR=$report
}

cmd_validate() {
    local tag=latest
    if [[ ${1:-} && $1 != -* ]]; then tag=$1; shift; fi
    tag=$(resolve_tag "$tag")
    step "validating patches: $(pinned_tag) → $tag"
    run_validate "$tag" "$@"
    case $VALIDATE_RC in
        0) ok "all patches work on $tag. Next: ./update.sh apply $tag" ;;
        3) warn "only optional patches are broken. './update.sh apply $tag --skip-broken-optional' would disable them";;
        2) warn "required patches (or sanity checks) failed — fix them before updating" ;;
        *) die "validation could not run" ;;
    esac
    echo "Report: $REPORT_DIR/REPORT.md"
    [[ -f $REPORT_DIR/FIX_PROMPT.md ]] && echo "Agent/LLM fix prompt: $REPORT_DIR/FIX_PROMPT.md"
    return 0
}

snapshot() {
    local from=$1 to=$2 why=$3 id
    id="$(date +%Y%m%d-%H%M%S.%3N)_${from}"
    mkdir -p "$SNAP_DIR/$id"
    echo "$from" > "$SNAP_DIR/$id/pinned_tag"
    printf 'created: %s\nreason: %s\nnext tag: %s\n' "$(date -Iseconds)" "$why" "$to" > "$SNAP_DIR/$id/info"
    rsync -a "$GRAPHITE_ROOT/patches/" "$SNAP_DIR/$id/patches/"
    [[ -d "$GRAPHITE_ROOT/manifests" ]] && rsync -a "$GRAPHITE_ROOT/manifests/" "$SNAP_DIR/$id/manifests/"
    echo "$id"
}

cmd_apply() {
    local tag="" skip_opt=0 force=0 yes=0
    while (( $# )); do
        case $1 in
            --skip-broken-optional) skip_opt=1 ;;
            --force) force=1 ;;
            -y|--yes) yes=1 ;;
            -*) die "unknown option $1" ;;
            *) tag=$1 ;;
        esac
        shift
    done
    tag=$(resolve_tag "${tag:-latest}")
    local pin
    pin=$(pinned_tag)
    [[ $tag == "$pin" ]] && { ok "already pinned to $tag"; return 0; }
    step "update $pin → $tag"
    run_validate "$tag"
    local report_json="$REPORT_DIR/report.json"
    case $VALIDATE_RC in
        0) ;;
        3) if (( ! skip_opt && ! force )); then
               die "optional patches are broken on $tag (see $REPORT_DIR/REPORT.md).
       Fix them (./update.sh fix <id> $tag) or re-run with --skip-broken-optional to disable them."
           fi ;;
        2) if (( ! force )); then
               die "required patches/sanity checks fail on $tag — NOT updating. See $REPORT_DIR/REPORT.md
       and hand $REPORT_DIR/FIX_PROMPT.md to an agent, or use ./update.sh fix <id> $tag."
           fi
           warn "--force: updating although required patches are broken; the build WILL fail until they are fixed" ;;
        *) die "validation failed to run" ;;
    esac
    if (( ! yes )) && [[ -t 0 ]]; then
        read -rp "Pin build.sh to $tag (snapshot of the current state is kept)? [y/N] " a
        [[ $a == [yY]* ]] || die "aborted"
    fi
    local snap
    snap=$(snapshot "$pin" "$tag" "update")
    # patches that upstream already contains, and (if allowed) broken optional ones, go to skip.list
    python3 -I - "$report_json" "$tag" "$skip_opt" "$GRAPHITE_ROOT/patches/skip.list" <<'PY'
import json, sys
report, tag, skip_opt, skip_list = sys.argv[1], sys.argv[2], sys.argv[3] == "1", sys.argv[4]
data = json.load(open(report))
existing = set()
try:
    existing = {l.partition("#")[0].strip() for l in open(skip_list)}
except FileNotFoundError:
    pass
add = []
for p in data["patches"]:
    if p["id"] in existing:
        continue
    if p["status"] == "ALREADY_APPLIED":
        add.append((p["id"], f"upstream contains this change since {tag}; patch can be deleted"))
    elif skip_opt and not p["required"] and p["status"] in ("CONFLICT", "FAILED", "PROJECT_MISSING", "SKIPPED_DEP"):
        add.append((p["id"], f"broken on {tag}, auto-skipped by update.sh; see reports/validate-{tag}/"))
if add:
    with open(skip_list, "a") as f:
        for pid, why in add:
            f.write(f"{pid}  # {why}\n")
            print(f"  skip.list += {pid}  ({why})")
PY
    set_pinned_tag "$tag"
    echo "$(date -Iseconds) update $pin -> $tag snapshot=$snap rc=$VALIDATE_RC" >> "$HISTORY"
    ok "build.sh now pins $tag (rollback: ./update.sh rollback $snap)"
    echo "Next: ./build.sh"
}

pick_snapshot() {
    local sel=${1:-}
    local snaps s pin
    mapfile -t snaps < <(ls -1 "$SNAP_DIR" | sort -r)
    (( ${#snaps[@]} )) || die "no snapshots — nothing to roll back to"
    if [[ -z $sel ]]; then
        # default: the state before the most recent update to a different version
        pin=$(pinned_tag)
        for s in "${snaps[@]}"; do
            if grep -q '^reason: update$' "$SNAP_DIR/$s/info" && [[ $(cat "$SNAP_DIR/$s/pinned_tag") != "$pin" ]]; then
                echo "$s"; return
            fi
        done
        die "no earlier update snapshot found (see ./update.sh history, then rollback N)"
    fi
    if [[ $sel =~ ^[0-9]+$ ]] && (( sel <= ${#snaps[@]} )) && (( ${#sel} < 4 )); then
        echo "${snaps[$((sel - 1))]}"
    elif [[ -d $SNAP_DIR/$sel ]]; then
        echo "$sel"
    else
        die "no such snapshot: $sel (see ./update.sh history)"
    fi
}

cmd_rollback() {
    local snap pin target
    snap=$(pick_snapshot "${1:-}")
    target=$(cat "$SNAP_DIR/$snap/pinned_tag")
    pin=$(pinned_tag)
    step "rollback $pin → $target (snapshot $snap)"
    [[ -t 0 ]] && { read -rp "Restore pin and patches/ from $snap? Current state is snapshotted first. [y/N] " a
                    [[ $a == [yY]* ]] || die "aborted"; }
    local pre
    pre=$(snapshot "$pin" "$target" "pre-rollback (undo with: ./update.sh rollback <this id>)")
    rsync -a --delete "$SNAP_DIR/$snap/patches/" "$GRAPHITE_ROOT/patches/"
    [[ -d $SNAP_DIR/$snap/manifests ]] && rsync -a --delete "$SNAP_DIR/$snap/manifests/" "$GRAPHITE_ROOT/manifests/"
    set_pinned_tag "$target"
    echo "$(date -Iseconds) rollback $pin -> $target from=$snap undo=$pre" >> "$HISTORY"
    ok "build.sh pins $target again; patches/ restored. Undo: ./update.sh rollback $pre"
    echo "Next: ./build.sh   (repo sync will move the tree back to $target)"
}

cmd_history() {
    echo "${_B}snapshots${_N} (newest first; 'rollback N' picks the Nth):"
    local i=1 s
    while read -r s; do
        [[ -z $s ]] && continue
        printf '  %2d) %s  pin=%s  %s\n' "$i" "$s" "$(cat "$SNAP_DIR/$s/pinned_tag")" \
            "$(sed -n 's/^reason: //p' "$SNAP_DIR/$s/info")"
        i=$((i + 1))
    done < <(ls -1 "$SNAP_DIR" | sort -r)
    echo
    echo "${_B}log${_N}:"
    [[ -f $HISTORY ]] && sed 's/^/  /' "$HISTORY" || echo "  (empty)"
}

cmd_fix() {
    local id=${1:?patch id}; local tag
    tag=$(resolve_tag "${2:-latest}")
    patchctl fix start "$id" --tag "$tag"
}

case ${1:-status} in
    status) cmd_status ;;
    validate) shift; cmd_validate "$@" ;;
    apply) shift; cmd_apply "$@" ;;
    rollback) shift; cmd_rollback "$@" ;;
    history) cmd_history ;;
    fix) shift; cmd_fix "$@" ;;
    -h|--help|help) usage ;;
    *) usage; exit 1 ;;
esac
