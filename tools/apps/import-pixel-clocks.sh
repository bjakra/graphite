#!/usr/bin/env bash
# Refresh Google's lockscreen clock plugins in src/vendor/graphite/prebuilt/PixelClocks/, which are bundled
# in that repo and re-signed by Soong with the platform key, as crDroid does. Commit the result.
#
# They come from CLOCK_BUILD, not the newest stock image: their plugin interface has to match the AOSP
# source in this tree. CP3A's call ClockProvider.initialize(Executor, ClockMessageBuffers, ...), while
# android-17.0.0_r1 has initialize(ClockMessageBuffers), so only the clocks' default face would load.
# Check this again when the tree moves to a new AOSP release.
#
# The image is downloaded from Google once, checked against adevtool's build index, and by downloading it
# you agree to Google's terms: https://developers.google.com/android/images#legal
#   tools/apps/import-pixel-clocks.sh [DEVICE]
set -euo pipefail
G="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
DEVICE=${1:-husky}
CLOCK_BUILD=CP2A.260705.006
CLOCKS=(BigNum Calligraphy Growth Inflate Metro NumOverlap Weather)
OUT="$G/src/vendor/graphite/prebuilt/PixelClocks"
CACHE="$G/state/pixel-clocks/$DEVICE-$CLOCK_BUILD"
INDEX="$G/src/vendor/adevtool/config/build-index/build-index-main.yml"
BIN="$G/src/out/host/linux-x86/bin"

if [[ ! -f $CACHE/.complete ]]; then
    read -r sha file < <(grep -A3 "^$DEVICE $CLOCK_BUILD:" "$INDEX" | sed -n 's/^ *factory: //p')
    [[ -n ${sha:-} ]] || { echo "$DEVICE $CLOCK_BUILD isn't in adevtool's build index"; exit 1; }
    work="$CACHE/work"; mkdir -p "$work"
    if ! echo "$sha  $work/$file" | sha256sum -c --status - 2>/dev/null; then
        echo "By downloading this image you agree to https://developers.google.com/android/images#legal"
        curl -fL --retry 3 -o "$work/$file" "https://dl.google.com/dl/android/aosp/$file"
        echo "$sha  $work/$file" | sha256sum -c -
    fi
    unzip -q -o -j "$work/$file" '*/image-*.zip' -d "$work"
    unzip -q -o "$work"/image-*.zip system_ext.img -d "$work"
    if file "$work/system_ext.img" | grep -q sparse; then
        "$BIN/simg2img" "$work/system_ext.img" "$work/system_ext.raw"
        mv "$work/system_ext.raw" "$work/system_ext.img"
    fi
    for c in "${CLOCKS[@]}"; do
        apk="SystemUIClocks-$c.apk"
        debugfs -R "dump /priv-app/SystemUIClocks-$c/$apk $CACHE/$apk" "$work/system_ext.img" 2>/dev/null
        [[ -s $CACHE/$apk ]] || { echo "$apk not found in the image"; exit 1; }
    done
    rm -rf "$work"
    touch "$CACHE/.complete"
fi

rm -rf "$OUT"; mkdir -p "$OUT"
for c in "${CLOCKS[@]}"; do
    name="SystemUIClocks-$c"
    cp "$CACHE/$name.apk" "$OUT/"
    cat >> "$OUT/Android.bp" <<EOF
android_app_import {
    name: "$name",
    owner: "google",
    apk: "$name.apk",
    certificate: "platform",
    privileged: true,
    system_ext_specific: true,
    dex_preopt: {
        enabled: false,
    },
    optional_uses_libs: [
        "androidx.window.extensions",
        "androidx.window.sidecar",
    ],
}

EOF
done
echo "imported ${#CLOCKS[@]} clocks from $DEVICE $CLOCK_BUILD → $OUT"
