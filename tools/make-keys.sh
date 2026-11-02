#!/usr/bin/env bash
# Generate release signing keys for a device (GrapheneOS procedure), stored in keys/<device>/.
# Keep these SAFE and BACKED UP: losing them means users must wipe to install future builds.
#
#   tools/make-keys.sh [--no-passphrase] [DEVICE] [CN]
#
# The key list comes from GrapheneOS' script/common.sh (signing_keys), so it follows the tag.
# By default every key asks for a passphrase (use the same one). --no-passphrase creates them
# unencrypted for unattended builds; encrypt them later with:
#   (cd src && script/encrypt-keys keys/<device>)
set -euo pipefail
source "$(dirname "$(readlink -f "$0")")/lib/common.sh"
nopass=0
[[ ${1:-} == --no-passphrase ]] && { nopass=1; shift; }
dev=${1:-$DEVICE}
cn=${2:-Graphite}
dir="$KEYS_DIR/$dev"
[[ -e $dir/releasekey.pk8 ]] && die "$dir already has keys"
[[ -x $SRC_DIR/development/tools/make_key ]] || die "source tree not synced (need development/tools/make_key)"
mapfile -t keys < <(sed -n '/^readonly signing_keys=(/,/^)/p' "$SRC_DIR/script/common.sh" | sed '1d;$d' | tr -d ' ')
((${#keys[@]})) || die "could not read signing_keys from script/common.sh"
mkdir -p "$dir"; chmod 700 "$dir"; cd "$dir"
log "generating ${keys[*]} for $dev in $dir"
for k in "${keys[@]}"; do
    if ((nopass)); then
        echo | "$SRC_DIR/development/tools/make_key" "$k" "/CN=$cn/" >/dev/null 2>&1 || true
    else
        "$SRC_DIR/development/tools/make_key" "$k" "/CN=$cn/" || true   # judge success by the output file
    fi
    [[ -f $k.x509.pem && -f $k.pk8 ]] || die "failed to create $k"
done
if ((nopass)); then
    openssl genrsa 4096 2>/dev/null | openssl pkcs8 -topk8 -nocrypt -out avb.pem
else
    openssl genrsa 4096 | openssl pkcs8 -topk8 -scrypt -out avb.pem
fi
python3 "$SRC_DIR/external/avb/avbtool.py" extract_public_key --key avb.pem --output avb_pkmd.bin
if ((nopass)); then ssh-keygen -q -t ed25519 -N '' -f id_ed25519; else ssh-keygen -t ed25519 -f id_ed25519; fi
chmod 600 ./*.pk8 avb.pem id_ed25519
ok "keys created. Back up $dir offline. avb_pkmd.bin is what you flash with 'fastboot flash avb_custom_key'."
((nopass)) && warn "keys are NOT encrypted. Encrypt them with: (cd $SRC_DIR && script/encrypt-keys keys/$dev)"
exit 0
