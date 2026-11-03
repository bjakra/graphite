#!/usr/bin/env bash
# Build Now Playing (Kieron Quinn's rebuild of Android System Intelligence, cut down to music recognition;
# apps/NowPlaying) and install it as the ROM prebuilt in src/vendor/graphite/prebuilt/NowPlaying/.
#
# Needs Google's Android System Intelligence APK, version U.0.droidfood.pixel6.514591756, which only APKMirror
# has (see docs/song-recognition-plan.md):
#   apps/NowPlaying/base.apk         arm64-v8a, the APK that gets rebuilt
#   apps/NowPlaying/base-x86_64.apk  optional, its x86_64 libraries are added for the emulator
# Google's files are git-ignored and never pushed. The prebuilt is signed with the debug key here; Soong re-signs
# it with the platform key, the same key as Ambient Music Mod, which the two apps need to trust each other.
#   tools/apps/build-nowplaying.sh [--no-build]
set -euo pipefail
G="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
N="$G/apps/NowPlaying"
OUT="$G/src/vendor/graphite/prebuilt/NowPlaying"
BT="$G/sdk/build-tools/37.0.0"
APKTOOL_VERSION=2.11.1
export JAVA_HOME=${JAVA_HOME_17:-/usr/lib/jvm/openjdk-bin-17}

if [[ ${1:-} != --no-build ]]; then
    [[ -f $N/base.apk ]] || { echo "missing $N/base.apk, see docs/song-recognition-plan.md"; exit 1; }
    mkdir -p "$N/tools"
    if [[ ! -f $N/tools/apktool.jar ]]; then
        curl -fsSL -o "$N/tools/apktool.jar" \
            "https://github.com/iBotPeaches/Apktool/releases/download/v$APKTOOL_VERSION/apktool_$APKTOOL_VERSION.jar"
    fi
    if [[ -f $N/base-x86_64.apk ]]; then
        mkdir -p "$N/overlay/src/main/lib/x86_64"
        unzip -o -j -q "$N/base-x86_64.apk" lib/x86_64/libsense.so lib/x86_64/libsense_nnfp_v3.so \
            lib/x86_64/libmodeleditor-jni.so -d "$N/overlay/src/main/lib/x86_64"
    fi
    cat > "$N/local.properties" <<EOF
sdk.dir=$G/sdk
build.tools.version=${BT##*/}
storeFile=$HOME/.android/debug.keystore
keyAlias=androiddebugkey
storePassword=android
keyPassword=android
EOF
    (cd "$N" && bash ./gradlew --no-daemon -q buildApkRelease)
fi
apk="$N/build/out-release.apk"
[[ -f $apk ]] || apk=$(ls -t "$N"/build/*.apk | head -n1)
[[ -f $apk ]] || { echo "no Now Playing APK found"; exit 1; }
pkg=$("$BT/aapt2" dump packagename "$apk")

# The rebuilt APK still carries the native libraries of every other Android System Intelligence feature (205 MB).
# Recognition only loads these three of Google's, the same set Kieron Quinn ships for x86_64, so Google's others are
# dropped (the overlay's own libraries, like Pine, stay):
# the ROM gets arm64 only (small enough for the vendor repo), the emulator copy also keeps x86_64 (local only).
# GitHub refuses files over 100 MiB, so the ROM copy must stay below that.
trim() { # trim IN OUT ABI...
    python3 - "$N/base.apk" "$@" <<'PY'
import sys, zipfile
base, src, dst, abis = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
keep = {"libsense.so", "libsense_nnfp_v3.so", "libmodeleditor-jni.so"}
# Libraries the overlay adds itself (Pine hooking etc.) are not Google's and always stay
with zipfile.ZipFile(base) as zbase:
    google = {n.rsplit("/", 1)[1] for n in zbase.namelist() if n.startswith("lib/")}
with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w") as zout:
    for info in zin.infolist():
        name = info.filename
        if name.startswith("META-INF/"):
            continue
        if name.startswith("lib/"):
            _, abi, lib = name.split("/", 2)
            if abi not in abis or not lib.endswith(".so") or (lib in google and lib not in keep):
                continue
        # dex compressed for the repo copy: Soong stores dex uncompressed again for privileged apps
        compress = zipfile.ZIP_DEFLATED if name.endswith(".dex") else info.compress_type
        zout.writestr(info, zin.read(info), compress_type=compress, compresslevel=9)
PY
    "$BT/zipalign" -f -P 16 4 "$2" "$2.aligned"  # 16 KB page aligned .so, loaded straight from the APK
    "$BT/apksigner" sign --ks "$HOME/.android/debug.keystore" --ks-key-alias androiddebugkey \
        --ks-pass pass:android --key-pass pass:android --out "$2" "$2.aligned" 2>/dev/null
    rm -f "$2.aligned" "$2.idsig"
}
mkdir -p "$OUT"
trim "$apk" "$OUT/NowPlaying.apk" arm64-v8a
trim "$apk" "$N/build/nowplaying-emu.apk" arm64-v8a x86_64
ls -la "$OUT/NowPlaying.apk" "$N/build/nowplaying-emu.apk" | awk '{print $5, $9}'
echo "installed $pkg → $OUT (emulator copy: $N/build/nowplaying-emu.apk)"
