#!/usr/bin/env bash
# Build the Android 17 JARs Lawnchair compiles against from the emulator ROM build (src/out-emu)
# into the port worktree's prebuilts/libs as *-17.jar. Android 17 splits WM Shell and SystemUI
# into javac, kotlin and aidl outputs, so those are merged. Prints what is missing.
set -uo pipefail
G="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
exec python3 -I - "$G" "${1:-$G/apps/lawnchair-a17}" <<'PY'
import sys, zipfile
from pathlib import Path
g, wt = Path(sys.argv[1]), Path(sys.argv[2])
I = g / "src/out-emu/soong/.intermediates/frameworks/base"
JARS = {
    "framework-17.jar": ["framework/android_common/turbine-combined/framework.jar"],
    "SystemUI-statsd-17.jar": ["packages/SystemUI/shared/SystemUI-statsd/android_common/javac/SystemUI-statsd.jar"],
    "WindowManager-Shell-17.jar": [
        "libs/WindowManager/Shell/WindowManager-Shell/android_common/javac/WindowManager-Shell.jar",
        "libs/WindowManager/Shell/WindowManager-Shell/android_common/kotlin/WindowManager-Shell.jar",
        "libs/WindowManager/Shell/WindowManager-Shell-aidls/android_common/javac/WindowManager-Shell-aidls.jar",
    ],
    "SystemUI-core-17.jar": [
        "packages/SystemUI/SystemUI-core/android_common/javac/SystemUI-core.jar",
        "packages/SystemUI/SystemUI-core/android_common/kotlin/SystemUI-core.jar",
    ],
}
rc = 0
for name, parts in JARS.items():
    missing = [p for p in parts if not (I / p).exists()]
    if missing:
        print(f"missing {name}: {missing}")
        rc = 1
        continue
    seen = set()
    with zipfile.ZipFile(wt / "prebuilts/libs" / name, "w", zipfile.ZIP_DEFLATED) as out:
        for p in parts:
            with zipfile.ZipFile(I / p) as z:
                for e in z.infolist():
                    if e.filename not in seen and not e.is_dir() and not e.filename.startswith("META-INF/"):
                        seen.add(e.filename)
                        out.writestr(e.filename, z.read(e.filename))
    print(f"ok      {name} ({len(seen)} entries from {len(parts)} jars)")
sys.exit(rc)
PY
