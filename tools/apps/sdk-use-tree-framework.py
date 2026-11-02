#!/usr/bin/env python3
"""Make the SDK platform that Gradle links apps against use this tree's framework resources.

aapt2 compiles references to framework resources into numeric IDs. Private IDs differ between
Google's SDK and a GrapheneOS build, so a reference such as @*android:dimen/taskbar_stashed_size
would silently read a different resource on the device. This swaps the resource table in
sdk/platforms/android-<api>/android.jar for the one in the built framework-res.apk, so names
resolve to the IDs the device really uses. The Java stubs in the jar stay as they are.

  tools/apps/sdk-use-tree-framework.py [--api 37.0]        patch the jar (keeps android.jar.orig)
  tools/apps/sdk-use-tree-framework.py --check APK         fail if APK references a missing ID
"""
import argparse
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AAPT2 = ROOT / "sdk/build-tools/37.0.0/aapt2"
SWAPPED = ("resources.arsc", "AndroidManifest.xml")


def framework_res():
    candidates = [
        ROOT / "src/out/target/product/husky/system/framework/framework-res.apk",
        ROOT / "src/out-emu/target/product/emu64x/system/framework/framework-res.apk",
    ]
    found = [p for p in candidates if p.exists()]
    if not found:
        sys.exit("no built framework-res.apk: build the emulator or device first")
    return max(found, key=lambda p: p.stat().st_mtime)


def patch(api):
    jar = ROOT / f"sdk/platforms/android-{api}/android.jar"
    orig = jar.with_name("android.jar.orig")
    if not orig.exists():
        shutil.copy2(jar, orig)
    source = framework_res()
    tmp = jar.with_name("android.jar.tmp")
    with zipfile.ZipFile(orig) as old, zipfile.ZipFile(source) as new, \
            zipfile.ZipFile(tmp, "w") as out:
        for item in old.infolist():
            if item.filename not in SWAPPED:
                out.writestr(item, old.read(item.filename))
        for name in SWAPPED:
            # resources.arsc must stay uncompressed so the asset manager can map it
            method = zipfile.ZIP_STORED if name.endswith(".arsc") else zipfile.ZIP_DEFLATED
            out.writestr(zipfile.ZipInfo(name), new.read(name), compress_type=method)
    tmp.replace(jar)
    print(f"{jar.relative_to(ROOT)}: resources from {source.relative_to(ROOT)}")


def resource_ids(apk):
    dump = subprocess.run([AAPT2, "dump", "resources", apk], check=True,
                          capture_output=True, text=True).stdout
    return dump


def check(apk):
    table = set(re.findall(r"^\s+resource (0x[0-9a-f]+) ", resource_ids(framework_res()), re.M))
    used = set(re.findall(r"@(0x01[0-9a-f]{6})", resource_ids(apk)))
    missing = sorted(used - table)
    if missing:
        sys.exit(f"{apk}: references framework IDs that don't exist: {missing}")
    print(f"{apk}: all {len(used)} framework references exist")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="37.0")
    parser.add_argument("--check", metavar="APK")
    args = parser.parse_args()
    if args.check:
        check(args.check)
    else:
        patch(args.api)


if __name__ == "__main__":
    main()
