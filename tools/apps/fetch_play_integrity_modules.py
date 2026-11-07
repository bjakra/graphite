#!/usr/bin/env python3
"""Fetch and verify the Zygisk modules bundled for Play Integrity (Play Integrity Fork, ReZygisk).

build.sh runs this before the build. For each module it downloads the asset of the project's latest
official GitHub release, checks it against the SHA-256 digest GitHub reports for that asset (an asset
without a digest is refused), and writes into <dest-dir>:

    <id>.zip          the release zip, unmodified
    <id>.zip.sha256   its SHA-256; the on-device controller checks it before installing
    <id>.meta         module id, versionCode, release tag, asset name and digest

The zips land in /system_ext through vendor/graphite/prebuilt/PlayIntegrity/Android.mk, so verified boot
covers them on the phone. The digest proves the bytes are what GitHub serves for the release; neither
project signs its releases, so it is integrity, not independent provenance.

If GitHub can't be reached, the files from the previous run are kept and the exit status is 0 when every
module still has a complete set (a warning is printed), so an offline rebuild keeps working.

Standard library only:
    python3 -I fetch_play_integrity_modules.py <dest-dir>
"""

import hashlib
import io
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile

# module id -> (GitHub repo, the asset name must contain, the asset name must not contain)
MODULES = {
    "playintegrityfix": ("osm0sis/PlayIntegrityFork", "PlayIntegrityFork", "source"),
    "rezygisk": ("PerformanC/ReZygisk", "ReZygisk", "debug"),
}

API = "https://api.github.com/repos/{repo}/releases/latest"
USER_AGENT = "graphite-build"


def http(url, accept=None, timeout=60):
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        return r.read()


def pick_asset(release, need, avoid):
    candidates = [
        a for a in release.get("assets", [])
        if a["name"].endswith(".zip") and need.lower() in a["name"].lower()
        and avoid.lower() not in a["name"].lower()
    ]
    if len(candidates) != 1:
        names = [a["name"] for a in release.get("assets", [])]
        raise RuntimeError(f"expected one module zip in {release.get('tag_name')}, found {names}")
    return candidates[0]


def module_prop(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if "module.prop" not in z.namelist():
            raise RuntimeError("no module.prop at the zip root")
        props = {}
        for line in z.read("module.prop").decode("utf-8", "replace").splitlines():
            key, sep, value = line.partition("=")
            if sep:
                props[key.strip()] = value.strip()
    if not props.get("id") or not props.get("versionCode", "").isdigit():
        raise RuntimeError("module.prop lacks id or a numeric versionCode")
    return props


def write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def fetch(dest, mid, repo, need, avoid):
    release = json.loads(http(API.format(repo=repo), "application/vnd.github+json", 30))
    asset = pick_asset(release, need, avoid)
    want = asset.get("digest") or ""
    if not want.startswith("sha256:"):
        raise RuntimeError(f"{asset['name']} has no SHA-256 digest from GitHub, refusing it")

    zip_path = os.path.join(dest, f"{mid}.zip")
    meta_path = os.path.join(dest, f"{mid}.meta")
    old = {}
    if os.path.exists(meta_path):
        for line in open(meta_path):
            k, _, v = line.strip().partition("=")
            old[k] = v
    if old.get("digest") == want and os.path.exists(zip_path) and \
            "sha256:" + hashlib.sha256(open(zip_path, "rb").read()).hexdigest() == want:
        print(f"   {asset['name']} ({release.get('tag_name')}): already current")
        return

    data = http(asset["browser_download_url"], timeout=180)
    got = "sha256:" + hashlib.sha256(data).hexdigest()
    if got != want:
        raise RuntimeError(f"{asset['name']}: SHA-256 {got} doesn't match GitHub's {want}")
    props = module_prop(data)
    if props["id"] != mid:
        raise RuntimeError(f"{asset['name']} is module '{props['id']}', expected '{mid}'")

    write(zip_path, data)
    write(zip_path + ".sha256", (got[len("sha256:"):] + "\n").encode())
    write(meta_path, (
        f"id={mid}\nversionCode={props['versionCode']}\nversion={props.get('version', '')}\n"
        f"tag={release.get('tag_name', '')}\nasset={asset['name']}\ndigest={got}\n").encode())
    print(f"   {asset['name']} ({release.get('tag_name')}, versionCode {props['versionCode']}): verified {got}")


def complete(dest, mid):
    return all(os.path.exists(os.path.join(dest, f"{mid}{s}")) for s in (".zip", ".zip.sha256", ".meta"))


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: fetch_play_integrity_modules.py <dest-dir>")
    dest = sys.argv[1]
    os.makedirs(dest, exist_ok=True)
    failed = []
    for mid, (repo, need, avoid) in MODULES.items():
        print(f"== {mid}: latest release of {repo}")
        try:
            fetch(dest, mid, repo, need, avoid)
        except (OSError, urllib.error.URLError, RuntimeError, ValueError, zipfile.BadZipFile) as e:
            print(f"   WARNING: {e}", file=sys.stderr)
            if complete(dest, mid):
                print("   keeping the previously fetched copy", file=sys.stderr)
            else:
                failed.append(mid)
    if failed:
        raise SystemExit(f"no usable copy of: {', '.join(failed)}")


if __name__ == "__main__":
    main()
