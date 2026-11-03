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
mkdir -p "$OUT"
cp "$apk" "$OUT/NowPlaying.apk"
echo "installed $apk ($pkg) → $OUT"
