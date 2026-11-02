#!/usr/bin/env python3
"""Regenerate Lawnchair's flags/ module from the aconfig srcjars of the emulator ROM build.

The launcher talks to the system it runs on, so the generated Android 17 values are used,
except for the LAWNCHAIR_OVERRIDES below (features Lawnchair implements itself). Differences
from the previous flags are printed for review.
Usage: lawnchair-regen-flags.py <lawnchair-worktree> [--dry-run]
"""
import io, os, re, shutil, sys, zipfile
from pathlib import Path

G = Path(__file__).resolve().parents[2]
I = G / "src/out-emu/soong/.intermediates"
JARS = {
    "com/android/launcher3": "packages/apps/Launcher3/aconfig/com_android_launcher3_flags_lib/android_common/gen/com_android_launcher3_flags_lib.srcjar",
    "com/android/systemui": "frameworks/base/packages/SystemUI/aconfig/com_android_systemui_flags_lib/android_common/gen/com_android_systemui_flags_lib.srcjar",
    "com/android/systemui/shared": "frameworks/libs/systemui/aconfig/com_android_systemui_shared_flags_lib/android_common/gen/com_android_systemui_shared_flags_lib.srcjar",
    "com/android/window/flags": "frameworks/base/com.android.window.flags.window-aconfig-java/android_common/gen/com.android.window.flags.window-aconfig-java.srcjar",
    "com/android/wm/shell": "frameworks/base/libs/WindowManager/Shell/aconfig/com_android_wm_shell_flags_lib/android_common/gen/com_android_wm_shell_flags_lib.srcjar",
}
# The platform hides these from apps at runtime (they aren't under these names on the boot
# classpath), but launcher code reads them, so they are compiled in with the build's values.
PLATFORM_PACKAGES = [
    "android/app", "android/appwidget/flags", "android/companion",
    "android/companion/virtualdevice/flags", "android/multiuser", "android/os", "android/security",
    "android/service/dreams", "android/view/accessibility",
    "com/android/graphics/surfaceflinger/flags", "com/android/hardware/input",
    "com/android/providers/media/flags", "com/android/server/am",
    "com/android/server/ui_latency_stats",
]
for dirpath, dirs, files in os.walk(I):
    for name in files:
        if not name.endswith(".srcjar") or "aconfig" not in dirpath + name:
            continue
        srcjar = Path(dirpath) / name
        names = zipfile.ZipFile(srcjar).namelist()
        for pkg in PLATFORM_PACKAGES:
            if f"{pkg}/Flags.java" in names and pkg not in JARS:
                JARS[pkg] = str(srcjar.relative_to(I))
missing = [p for p in PLATFORM_PACKAGES if p not in JARS]
if missing:
    print(f"WARNING: no aconfig srcjar found for: {missing}")
LAWNCHAIR_OVERRIDES = {
    "com/android/launcher3": {
        "enableQsbOnHotseat": "false",  # Lawnchair's own dock search bar (HotseatMode)
        "forceMonochromeAppIcons": "false",  # Lawnchair's own themed-icon preference
        "homeScreenEditImprovements": "false",  # Lawnchair's own edit mode page strip
    },
}
root = Path(sys.argv[1]) / "flags/src"
dry = "--dry-run" in sys.argv
METHOD = re.compile(r"public (?:static )?boolean (\w+)\(\)\s*\{[^{}]*?return (true|false);", re.S)
for pkg, jar in JARS.items():
    dest = root / pkg
    old = {}
    if (dest / "FeatureFlagsImpl.java").exists():
        old = dict(METHOD.findall((dest / "FeatureFlagsImpl.java").read_text()))
    zf = zipfile.ZipFile(I / jar)
    new = {n: zf.read(n).decode() for n in zf.namelist() if n.endswith(".java") and n.startswith(pkg + "/")}
    names = sorted(Path(n).name for n in new)
    flags = new[f"{pkg}/Flags.java"]
    gen = dict(METHOD.findall(flags))
    if not gen and f"{pkg}/FeatureFlagsImpl.java" in new:
        gen = dict(METHOD.findall(new[f"{pkg}/FeatureFlagsImpl.java"]))
    diffs = {k: (old[k], gen[k]) for k in gen if k in old and old[k] != gen[k]}
    print(f"{pkg}: files={names} flags={len(gen)} old={len(old)} differs-from-before={len(diffs)} "
          f"new={len(set(gen)-set(old))} gone={len(set(old)-set(gen))}")
    for k, (o, g) in sorted(diffs.items()):
        print(f"    {k}: lawnchair={o} aosp17={g}")
    if dry:
        continue
    dest.mkdir(parents=True, exist_ok=True)
    for f in dest.glob("*.java"):
        f.unlink()
    for n, text in new.items():
        overrides = LAWNCHAIR_OVERRIDES.get(pkg, {})
        def fix(m):
            v = overrides.get(m.group(1), m.group(2))
            return m.group(0)[: m.group(0).rfind("return ")] + f"return {v};"
        text = METHOD.sub(fix, text)
        # The aconfig annotations don't exist outside the platform build
        text = re.sub(r"^\s*@com\.android\.aconfig\.annotations\.\w+(\(.*?\))?\s*$\n?", "", text, flags=re.M)
        text = re.sub(r"^import (android\.provider\.flags|com\.android\.aconfig)\..*\n", "", text, flags=re.M)
        (dest / Path(n).name).write_text(text)
