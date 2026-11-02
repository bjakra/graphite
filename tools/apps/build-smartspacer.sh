#!/usr/bin/env bash
# Build Smartspacer (Graphite fork, apps/Smartspacer, no Firebase or Play Services) and install it as
# the ROM prebuilt in src/vendor/graphite/prebuilt/Smartspacer/. Soong signs it with the release key.
#   tools/apps/build-smartspacer.sh [--no-build]
set -euo pipefail
G="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
S="$G/apps/Smartspacer"
OUT="$G/src/vendor/graphite/prebuilt/Smartspacer"
if [[ ${1:-} != --no-build ]]; then
    cd "$S"
    export LC_ALL=C.UTF-8 JAVA_HOME="$G/src/prebuilts/jdk/jdk21/linux-x86" ANDROID_HOME="$G/sdk" GRADLE_USER_HOME="$G/sdk/gradle-home"
    rc=0
    nice -n 10 bash ./gradlew --no-daemon --max-workers="${GRADLE_WORKERS:-3}" --console=plain \
        -Dorg.gradle.jvmargs="-Xmx${GRADLE_HEAP:-5g} -Dfile.encoding=UTF-8" \
        -Pkotlin.compiler.execution.strategy=in-process :app:assembleRelease \
        > "$G/logs/smartspacer-gradle.log" 2>&1 || rc=$?
    grep -E "^e: |error:|\* What went wrong|FAILED|BUILD (SUCCESSFUL|FAILED)" "$G/logs/smartspacer-gradle.log" | cut -c1-220 | tail -30
    ((rc == 0)) || exit "$rc"
fi
apk=$(ls -t "$S"/app/build/outputs/apk/release/*.apk | head -n1)
[[ -f $apk ]] || { echo "no release APK found"; exit 1; }
mkdir -p "$OUT"
cp "$apk" "$OUT/Smartspacer.apk"
echo "installed $apk -> $OUT"
