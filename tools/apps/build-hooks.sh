#!/usr/bin/env bash
# Build the hooking libraries the Now Playing engine needs on Android 17 and publish them to the local Maven repo
# (~/.m2), where apps/NowPlaying picks them up:
#   apps/hooks/lsplant        github.com/bjakra/LSPlant (branch graphite): upstream LSPlant master on Aliucord's
#                             packaging, 6.4-aliucord.4-graphite.1
#   apps/hooks/dobby-android  private, emulator only: Dobby with inline x64 jumps, 1.2-graphite.1
#   apps/hooks/aliuhook       github.com/bjakra/hook (branch graphite): AliuHook 1.1.4-graphite.3
# Without the private Dobby, AliuHook uses upstream Dobby 1.2, which is all the arm64 (phone) build needs.
# Needs sdk/ndk/30.0.16248370, sdk/ndk/22.1.7171670 (Dobby) and sdk/cmake/3.31.6.
#   tools/apps/build-hooks.sh
set -euo pipefail
G="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
H="$G/apps/hooks"
for repo in lsplant aliuhook dobby-android; do
    [[ -d $H/$repo ]] && printf 'sdk.dir=%s/sdk\n' "$G" > "$H/$repo/local.properties"
done
(cd "$H/lsplant" && bash ./gradlew --no-daemon -q :lsplant:publishToMavenLocal)
dobby=()
if [[ -d $H/dobby-android ]]; then
    (cd "$H/dobby-android" && bash ./gradlew --no-daemon -q :dobby:publishToMavenLocal)
    dobby=(-PgraphiteDobby=1.2-graphite.1)
fi
(cd "$H/aliuhook" && bash ./gradlew --no-daemon -q "${dobby[@]}" :core:publishToMavenLocal)
echo "published LSPlant and AliuHook${dobby:+ (with the emulator Dobby)} to ~/.m2"
