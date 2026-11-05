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
# Graphite: SuSFS is compiled in (CONFIG_KSU_SUSFS), so its kernel/susfs directory is copied too.
# The directory's own Makefile (which builds the standalone susfs_guard_lkm.ko) is left unused: the
# Kbuild lists susfs/*.o as part of kernelsu-objs, so kbuild never descends into the directory.
tar -C "$G/apps/KernelSU-Next/kernel" -cf - . | tar -C "$ACK/drivers/kernelsu" -xf -
# A symlink out of the kernel directory in the source, which the sandbox wouldn't include
rm "$ACK/drivers/kernelsu/include/uapi"
cp -r "$G/apps/KernelSU-Next/uapi" "$ACK/drivers/kernelsu/include/uapi"
# No git repository inside the sandbox, so the version can't be worked out there
sed -i "s/^KSU_VERSION_FALLBACK := 1\$/KSU_VERSION_FALLBACK := $VERSION/" "$ACK/drivers/kernelsu/Kbuild"
sed -i "s/v0\.0\.1/v3.4.2/" "$ACK/drivers/kernelsu/Kbuild"
grep -q 'kernelsu/' "$ACK/drivers/Makefile" || printf '\nobj-$(CONFIG_KSU) += kernelsu/\n' >> "$ACK/drivers/Makefile"
grep -q 'drivers/kernelsu/Kconfig' "$ACK/drivers/Kconfig" || sed -i '/^endmenu/i source "drivers/kernelsu/Kconfig"' "$ACK/drivers/Kconfig"
# Graphite: built-in SuSFS rewrites saved_boot_config by name (susfs/spoof_cmdline.c), so it cannot
# stay file-local in fs/proc/bootconfig.c. Expose it under CONFIG_KSU_SUSFS, static otherwise. The
# rest of SuSFS is inside drivers/kernelsu above; this is the one edit outside that directory.
python3 -I - "$ACK/fs/proc/bootconfig.c" <<'PY'
import sys
path = sys.argv[1]
text = open(path).read()
needle = "static char *saved_boot_config;\n"
block = ("#ifdef CONFIG_KSU_SUSFS\n"
         "/* Graphite: built-in SuSFS (drivers/kernelsu/susfs/spoof_cmdline.c) rewrites this pointer\n"
         " * to spoof /proc/bootconfig; it reaches it by name, so it must not be file-local here. */\n"
         "char *saved_boot_config;\n"
         "#else\n"
         "static char *saved_boot_config;\n"
         "#endif\n")
if "CONFIG_KSU_SUSFS" not in text and needle in text:
    open(path, "w").write(text.replace(needle, block, 1))
PY
