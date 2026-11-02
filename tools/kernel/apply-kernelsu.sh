#!/usr/bin/env bash
# Add KernelSU-Next (apps/KernelSU-Next, release tag) to the Pixel kernel in kernel/pixel/common/ack as a
# built-in driver. It is a copy rather than a symlink, because kleaf builds in a sandbox.
#   tools/kernel/apply-kernelsu.sh
set -euo pipefail
G="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
ACK="$G/kernel/pixel/common/ack"
# The manager release this kernel is paired with (KernelSU_Next_v3.4.2_33355-release.apk)
VERSION=33355
rm -rf "$ACK/drivers/kernelsu"
mkdir -p "$ACK/drivers/kernelsu"
tar -C "$G/apps/KernelSU-Next/kernel" --exclude=./susfs -cf - . | tar -C "$ACK/drivers/kernelsu" -xf -
# A symlink out of the kernel directory in the source, which the sandbox wouldn't include
rm "$ACK/drivers/kernelsu/include/uapi"
cp -r "$G/apps/KernelSU-Next/uapi" "$ACK/drivers/kernelsu/include/uapi"
# No git repository inside the sandbox, so the version can't be worked out there
sed -i "s/^KSU_VERSION_FALLBACK := 1\$/KSU_VERSION_FALLBACK := $VERSION/" "$ACK/drivers/kernelsu/Kbuild"
sed -i "s/v0\.0\.1/v3.4.2/" "$ACK/drivers/kernelsu/Kbuild"
grep -q 'kernelsu/' "$ACK/drivers/Makefile" || printf '\nobj-$(CONFIG_KSU) += kernelsu/\n' >> "$ACK/drivers/Makefile"
grep -q 'drivers/kernelsu/Kconfig' "$ACK/drivers/Kconfig" || sed -i '/^endmenu/i source "drivers/kernelsu/Kconfig"' "$ACK/drivers/Kconfig"
