# Graphite

**Graphite = GrapheneOS + a stack of our own patches**, built for the
**Pixel 8 Pro (`husky`)**. GrapheneOS stays the base layer and Graphite adds
features on top (root, custom-ROM features, …) as small, documented patches
that can be re-applied to every new GrapheneOS release.

```
./build.sh          build the pinned version (never changes by itself)
./update.sh         move to a new GrapheneOS release — validated, with rollback
./dev.sh            fast loop: rebuild one component, push it to an emulator/phone
tools/patchctl      the patch engine (list, create, export, fix patches)
```

## Layout

| Path | What |
|---|---|
| `build.sh` | Build script. `PINNED_TAG` at the top is the GrapheneOS release being built. |
| `update.sh` | Changes `PINNED_TAG` after validating all patches; snapshots for rollback. |
| `dev.sh` | Emulator / device development loop (module builds + `adb sync`). |
| `graphite.conf` | Device, variant, jobs, out dirs, … (`graphite.local.conf` overrides, untracked). |
| `patches/` | One directory per patch: `patch.toml` (what/why/required) + `.patch` files. See [patches/README.md](patches/README.md). |
| `patches/skip.list` | Patch ids to leave out of builds (with reason). |
| `manifests/` | Extra repo projects (local manifests), e.g. for Graphite-only apps. |
| `src/` | The GrapheneOS source tree (repo checkout, ~100 GB). Don't commit work here: export it as patches. |
| `reports/` | Patch reports from builds and update validations (Markdown + JSON, agent-ready). |
| `state/` | Snapshots, caches, last-applied state. |
| `keys/` | `trust/` = GrapheneOS tag signing key; `<device>/` = your release keys (**keep private**). |
| `tools/` | `repo`, `patchctl`, container env, key generation. |
| `AGENTS.md` | Instructions for AI agents working on this repo. |

## Building

```bash
./build.sh                      # sync → patch → vendor files → build (userdebug dev images)
./build.sh --release --variant user     # signed factory images + OTA (needs tools/make-keys.sh first)
./build.sh --skip-sync          # offline rebuild after editing patches
./build.sh --only patch         # just re-apply the patches
```

Steps: `preflight → sync → patch → vendor → build [→ release]`.

* **sync**: `repo init/sync` to `PINNED_TAG`, after verifying the tag's signature against
  GrapheneOS' signing key (`keys/trust/grapheneos_allowed_signers`).
* **patch**: resets every patched project to the manifest revision, then commits each patch on
  top (commits carry a `Graphite-Patch: <id>` trailer). If a patch fails, the script tells you
  **what the patch does, whether it's required, what you lose by skipping it**, and writes a full
  report to `reports/build-*/`. Optional patches can be skipped interactively or with
  `--skip-optional`; a failing required patch stops the build.
* **vendor**: `adevtool generate-all -d husky` (see "Vendor files" below). Cached, so it only
  re-runs when adevtool changed.
* **build**: `m` (dev) or `m vendorbootimage vendorkernelbootimage target-files-package otatools-package` (release).

Flash a dev build (unlocked bootloader, test keys): `./dev.sh --device flash`.

### This machine

16 threads, **15 GiB RAM**, and the 31 GiB of swap is **zram** (compressed RAM, so not real extra
capacity). Soong's analysis of the full tree, which every build including adevtool's host-tool
build runs, needs well over 30 GiB and was OOM-killed at ~26 GiB effective. `preflight` refuses
to build below ~40 GiB effective (RAM + disk swap + zram/3) and prints the commands to add a
48 GiB disk swapfile on the (LUKS-encrypted) SSD. With that, builds work but swap: expect the
first full build to take many hours. Jobs are derived from RAM (currently 7). If compile steps
get OOM-killed, set `JOBS=4` in `graphite.local.conf`.

## Updating to a new GrapheneOS release

```bash
./update.sh status              # pinned vs. latest
./update.sh validate            # test all patches against the latest tag (touches nothing)
./update.sh apply               # validate + snapshot + bump PINNED_TAG
./build.sh
./update.sh rollback            # back to the state before the last update (pin + patches/)
./update.sh history
```

`validate` test-applies every patch into temporary git indexes of the new revisions, so it
needs no checkout and is safe to run while building. Per patch it reports one of:

| Status | Meaning |
|---|---|
| OK | applies cleanly |
| NEEDS_REFRESH | applies only via 3-way merge, or partly upstreamed → `tools/patchctl refresh <id> --tag T` |
| ALREADY_APPLIED | upstream contains the change → `apply` adds it to `skip.list` |
| CONFLICT / FAILED | broken → fix it (below) |
| PROJECT_MISSING | the repo vanished from the manifest |
| SKIPPED_DEP | not tried, a dependency is broken |

`apply` refuses to update if a required patch is broken (`--force` overrides), and needs
`--skip-broken-optional` to disable broken optional ones.

It also checks the tag signature, that adevtool still supports `husky`, that the kernel prebuilt
project exists, and whether the stock vendor build (factory image) changes.

### When a patch breaks

The report (`reports/validate-<tag>/`) has `REPORT.md`, `report.json`, a `FIX_PROMPT.md`, and a
**self-contained fix request per broken patch** in `failures/<id>.md`. It contains the patch's
purpose, the failing hunks, the new upstream code around the location (with line numbers), the
3-way conflict, and upstream's own diff of the file between the two versions. Hand it to an agent,
or paste it into any LLM. To fix it by hand:

```bash
./update.sh fix <id> <tag>               # worktree at work/fix-<id>/ with conflicts marked
# edit, then: git -C work/fix-<id>/<project> add -A
tools/patchctl fix continue <id>
tools/patchctl fix finish <id>           # writes the new patch file back into patches/<id>/
./update.sh validate <tag> --only <id>
```

## Development: patch, rebuild one component, test

Full OS builds take hours, so for day-to-day work use the emulator (or a userdebug phone) and
rebuild only what changed:

```bash
./dev.sh build                  # once: full emulator build (sdk_phone64_x86_64, separate out-emu/)
./dev.sh run                    # boots the emulator (KVM, writable /system), background
# edit src/frameworks/base/... or src/packages/apps/Settings/...
./dev.sh quick Settings         # m Settings → adb sync → soft restart (minutes, not hours)
./dev.sh quick framework services   # framework changes
./dev.sh shell                  # bash with envsetup+lunch, for m/mm/mmm
./dev.sh --device quick SystemUI    # same against a USB-connected husky userdebug build
```

Turning the work into a patch:

```bash
tools/patchctl new 0200-my-feature --title "My feature"   # then edit patch.toml (description, required, skip_impact)
git -C src/packages/apps/Settings commit -am "Settings: my feature"
tools/patchctl export 0200-my-feature --project packages/apps/Settings --new
./build.sh --only patch          # re-applies everything; your commit now comes from the patch
```

`build.sh` / `patchctl apply` refuse to reset projects that contain commits or edits that aren't
in a patch yet, so work in `src/` can't be lost silently (`--force` discards).

## Vendor files: why adevtool and not TheMuppets

The plan was to take blobs from TheMuppets (`proprietary_vendor_google_husky`). That doesn't work
for a GrapheneOS base:

* Since Android 16, Google no longer publishes Pixel device trees. GrapheneOS's manifest no
  longer contains `device/google/shusky`, `zuma` or `gs-common`. **adevtool generates the whole
  device + vendor layer** (`vendor/google_devices/husky`, including the device makefiles kept in
  `vendor/adevtool/config/mk/`) from Google's factory image and checks it against hashes in
  `vendor-specs/`.
* TheMuppets' repo is laid out for **LineageOS** device trees (`vendor/google/husky`,
  `husky-vendor.mk`, LineageOS' `proprietary-files.txt` selection). Nothing in the GrapheneOS
  tree consumes that layout, and it lacks GrapheneOS' state/overlays and the firmware handling.
* Both currently come from the same stock build (`CP3A.261005.005`), so TheMuppets has no
  advantage. adevtool downloads the factory image straight from Google, verifies it, and always
  matches the build ID that the pinned GrapheneOS tag expects.

So Graphite uses adevtool, as GrapheneOS does. If a feature ever needs a specific extra blob, we
can add it as a small vendor project in `manifests/` plus a patch.

## Container (optional)

The host (Gentoo) builds natively. For an officially supported environment (Debian bookworm +
Node 24) set `GRAPHITE_CONTAINER=1` in `graphite.local.conf`: the scripts then re-run
themselves inside `tools/container/` via podman. `tools/container/run.sh` gives a shell there.

## Release signing

`tools/make-keys.sh husky` creates keys in `keys/husky/` (GrapheneOS procedure, passphrase-
encrypted). Back them up offline: losing them means a wipe to install future builds. Then
`./build.sh --release --variant user` produces `src/releases/<build>/release-husky-<build>/` with
factory images and an OTA zip. To use the Updater app, set `UPDATE_URL` to **your own** server.
Never point it at GrapheneOS's.

## Repositories

Everything is tracked on GitHub under `bjakra`. Keep them up to date when a change lands.

| Repo | Contents | Local path |
|---|---|---|
| `graphite` | Tooling, patches, docs | this directory |
| `graphite_vendor` | Overlays, prebuilts, product config, test wallet. Contains Google's clock APKs and the Now Playing engine built from Google's APK | `src/vendor/graphite` |
| `graphite_parts`, `graphite_weather` | Graphite's settings and weather apps | `src/packages/apps/` |
| `lawnchair` (`graphite-a17-merge`) | Launcher fork, shipped as a prebuilt in `graphite_vendor` | `apps/lawnchair-a17` |
| `AmbientMusicMod` (`graphite`) | Headless Now Playing core (`org.graphite.nowplaying`) and the database downloader (`org.graphite.musicdb`). Built by `tools/apps/build-nowplaying-core.sh` | `apps/AmbientMusicMod` |
| `NowPlaying` (`graphite`) | Now Playing engine (`com.kieronquinn.app.pixelambientmusic`) built around Google's recognition APK. Built by `tools/apps/build-nowplaying.sh` | `apps/NowPlaying` |
| `LSPlant`, `hook` (`graphite`) | Hook libraries the engine needs on Android 17. Built in order by `tools/apps/build-hooks.sh` | `apps/hooks/` |
| `dobby-android-graphite`, `dobby-graphite` (private) | Dobby with x86_64 inline jumps. Only the emulator build needs it (`-PgraphiteDobby`) | `apps/hooks/dobby-android` |
| `graphite_depth_wallpaper` | The 3D wallpaper. Built by `tools/apps/build-depth-wallpaper.sh`, which downloads its models | `apps/GraphiteDepthWallpaper` |
| `Smartspacer`, `ClassicPowerMenu` (`graphite`) | Older forks. Their features are now built into Lawnchair and SystemUI patches, so they don't ship | `apps/` |

The Now Playing design (privacy, network gating, database updates) is described in
[docs/song-recognition-plan.md](docs/song-recognition-plan.md).

`build.sh` still syncs Graphite's own repos from the local copies in `projects/`.

`vendor/graphite/tests/WalletTestCards` is a test app that never ships. It has made-up Quick Access Wallet cards and a
`FLAG_SECURE` screen. Install it on the emulator with `adb install`, then run
`adb shell settings put secure nfc_payment_default_component org.graphite.wallettest/.TestPaymentService`.

## Kernel

The Pixel 8 kernel lives in `kernel/pixel` (GrapheneOS `kernel_pixel_6.1`, branch `17`) and adds KernelSU-Next v3.4.2 through
`patches-kernel/`. `tools/kernel/build-husky.sh` builds it and installs the result in `device/google/shusky-kernels`. A repo
sync of that project restores GrapheneOS's kernel, so run `tools/kernel/build-husky.sh --install-only` again after one. All
modules come from the same build, because forced module signing and struct randomisation tie modules to their kernel build.

SUSFS isn't integrated yet. `tools/kernel/apply-kernelsu.sh` leaves out KernelSU-Next's `kernel/susfs` directory, and nothing else
in the kernel depends on it, so it can be added later.
