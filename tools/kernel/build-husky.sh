#!/usr/bin/env bash
# Build the Pixel 8 kernel from kernel/pixel with KernelSU-Next and install it in the OS tree.
# All modules are rebuilt with it: GrapheneOS's kernel uses struct randomisation and forced module
# signing, so prebuilt modules only load on the exact kernel build they came from.
#   tools/kernel/build-husky.sh [--install-only]
# SUSFS is not integrated. apply-kernelsu.sh leaves out KernelSU-Next's kernel/susfs directory, so adding it later
# only needs that exclude removed plus the driver's kernel configuration.
set -euo pipefail
G="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
P="$G/kernel/pixel"
DEST="$G/src/device/google/shusky-kernels/6.1/grapheneos"
if [[ ${1:-} != --install-only ]]; then
    (cd "$P" && KLEAF_REPO_MANIFEST=aosp_manifest.xml ./build_shusky.sh)
fi
# Only the files the OS tree already has; the dist folder also holds headers and other build output
n=0
for f in "$DEST"/*; do
    b=$(basename "$f")
    [[ -e $P/out/shusky/dist/$b ]] || { echo "missing from the kernel build: $b"; exit 1; }
    cp "$P/out/shusky/dist/$b" "$f"
    n=$((n + 1))
done
echo "installed $n files in $DEST"
