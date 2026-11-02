# Graphite roadmap

Feature list from the user (2026-11-01), with an implementation design per item, suggested
improvements, and extra features. Base: GrapheneOS 17 (`2026103100`), husky.

Guiding principles, which keep `./update.sh` cheap every month:

1. **Put code in our own repos, not in big patches.** Features go into Graphite-owned projects
   pulled in through `manifests/` (GraphiteParts app, clock plugin, prebuilt apps, kernel modules).
   Patches to GrapheneOS repos only add *hooks* (a settings key, a call, an overlay).
2. **Use one settings namespace.** All toggles live in `Settings.Secure/System` keys prefixed `graphite_`,
   declared once in a single frameworks/base patch (`0100-graphite-settings-keys`).
3. **Keep GrapheneOS's security model intact by default.** Anything that weakens it (root, FLAG_SECURE) is opt-in and scoped as narrowly as possible.

## Decisions (2026-11-01)

* **Verified boot:** relock the bootloader with Graphite's own AVB key, like GrapheneOS
  (`tools/make-keys.sh`, `fastboot flash avb_custom_key avb_pkmd.bin`, `fastboot flashing lock`).
  Release builds are always signed (`./build.sh --release --variant user`); test-key builds are
  for the emulator and development only.
* **FLAG_SECURE:** a per-app override list in Graphite settings. Overridden apps can be captured
  **only by the system** (system screenshots, plus screen recording started from SystemUI).
  Third-party capture (MediaProjection apps, casting to other apps) still sees them as secure.
  There is no global switch.
* **Search:** fork of [PixelishSearch](https://github.com/pchmn/PixelishSearch) (MIT), made
  Google-independent (see §2).
* **Forks** live on GitHub user `bjakra` so they can be published:
  `bjakra/lawnchair` (fresh fork of LawnchairLauncher/lawnchair; work branch `graphite`, created from
  upstream `16-dev` @ 849fec9), `bjakra/Smartspacer`, `bjakra/KernelSU-Next`.
  The old 2024 lawnchair fork was deleted; a backup is in `state/backups/lawnchair-old-fork-2024.bundle`.
  susfs4ksu and GrapheneOS's kernel live on GitLab (no `gh` fork). Their changes are kept as patches.

## 0. Infrastructure (needed before most features)

| Item | Design |
|---|---|
| **GraphiteParts** (the "ROM settings page") | A separate privileged app (`packages/apps/GraphiteParts`, own git repo, local manifest). It appears under *Settings → System → Graphite* through Settings' **tile injection** (`com.android.settings.action.EXTRA_SETTINGS` + `com.android.settings.category=com.android.settings.category.ia.system`), so the Settings patch is zero or tiny. LineageParts and crDroidSettings follow the same pattern. |
| Settings keys | `0100-graphite-settings-keys` (frameworks/base): `Settings.Secure.GRAPHITE_*` constants + backup/validators. |
| Kernel pipeline | New `kernel.sh` and `patches-kernel/`: sync GrapheneOS `kernel_pixel_6.1` (branch matching the pinned tag), apply kernel patches with patchctl (needs a `--tree` option), build `shusky`, and copy `out/shusky/dist` into `src/device/google/shusky-kernels/6.1/grapheneos/` before `build.sh`'s build step. `update.sh validate` also validates kernel patches. |
| App pipeline | Gradle-built apps (Lawnchair, Smartspacer, KernelSU-Next manager) built from **pinned forks** by `tools/apps/build-*.sh` → `prebuilts/graphite/<app>/` (`android_app_import`, `privileged: true`, privapp-permissions XML, re-signed with our platform/releasekey). |

## 1. Root: KernelSU-Next + SUSFS (in kernel)

* The Pixel 8 runs the android14-6.1 GKI; GrapheneOS builds that GKI from source in `kernel_pixel_6.1`.
  KernelSU-Next is integrated as built-in (`CONFIG_KSU=y`). SUSFS uses the
  `gki-android14-6.1` branch of susfs4ksu. Check the KernelSU-Next ↔ SUSFS version pairing
  (KernelSU-Next v3.x loads SUSFS as an LKM on GKI 2.0, so it may not need the classic in-tree patch).
* **Bootloader stays *locked* (decided).** The kernel is part of our AVB-signed boot image, so
  Graphite can relock with our own key (`fastboot flash avb_custom_key avb_pkmd.bin`). The result is root
  plus full verified boot and the GrapheneOS update security model, which most rooted ROMs can't offer.
* Status: KernelSU-Next v3.4.2 is built in and the manager preinstalled. SUSFS is deferred, and the kernel stays ready for it.
* Preinstall the KernelSU-Next manager as a system app. Root is granted per app in the manager, and
  the default is "nobody". Optionally ship a default SUSFS config (hide mounts/props, spoof uname).
* Defaults for "best hiding" belong in a small KernelSU module bundled with the manager
  (not compiled into the kernel), so they update without a reflash.

## 2. Lawnchair as default home + recents (Quickstep)

* Hardest item. Lawnchair's newest branch is `16-dev`, with no Android 17 Quickstep yet, and every
  Android QPR changes the Quickstep ↔ SystemUI/WM Shell interfaces.
* Design:
  * A Graphite fork of Lawnchair (`graphite-17` branch) that ports Quickstep to A17 by
    diffing AOSP Launcher3 `android16` → GrapheneOS 17 Launcher3, which sits in our tree.
  * Built by the app pipeline, installed as priv-app, **signed with our platform key**, so the
    signature permissions Quickstep needs are granted natively (no QuickSwitch/root).
  * Overlay `config_recentsComponentName` → Lawnchair's recents activity, and set it as default home.
* **Improvement: a fallback.** Keep GrapheneOS's Launcher3 Quickstep installed but hidden. An
  overlay toggle in GraphiteParts switches the recents provider back if a Lawnchair port lags behind
  an update. `update.sh validate` can't test a Gradle app, so the app pipeline gets its own
  "does it build against this tag's SDK" check.
* At a Glance: the **real Pixel At a Glance needs proprietary Google apps (ASI) that can't be
  redistributed**. Use **Smartspacer** (open source) preinstalled and enabled, with Lawnchair's
  smartspace provider set to Smartspacer and a toggle to hide it. As a privileged system app,
  Smartspacer gets its permissions without Shizuku.
* Search bar: Lawnchair's own search, restyled like PixelishSearch. The original plan, a **fork of PixelishSearch** (Pixel Launcher-style unified search, Kotlin/Compose, MIT):
  * Web search goes through `Intent.ACTION_WEB_SEARCH` to the **default browser**, so Vanadium
    uses its own configured default search engine. No hard-coded Google.
  * Suggestions use a configurable provider (none / DuckDuckGo / Startpage / Brave / …)
    instead of Google Suggest. Default: none.
  * Replace the bundled Google Sans font with an openly licensed one (Google Sans isn't
    redistributable). Check whether Google Sans Flex's licence allows bundling.
  * Lawnchair's hotseat search bar opens it **without window animation** (zero-duration
    `ActivityOptions` + a translucent, no-animation theme in the search activity), so it feels built
    in. Later it can become a library module inside the Lawnchair fork.
  * Preinstalled as a system app, so `WRITE_SECURE_SETTINGS` for the quick toggles is granted
    via privapp permissions instead of adb.

## 3. Graphite settings: features

| Feature | Implementation | Source to port |
|---|---|---|
| Caffeine QS tile | SystemUI tile (`CaffeineTile`): wakelock with 5/10/30 min/∞ cycle | LineageOS SystemUI |
| Status bar icon manager | AOSP still honours `Settings.Secure.icon_blacklist`. GraphiteParts lists every slot **with its real icon** (loaded from SystemUI resources via `createPackageContext`) | AOSP SystemUI Tuner, crDroid |
| Clock seconds | `Settings.Secure.clock_seconds` (still read by SystemUI) + UI | AOSP tuner |
| More tuner options | clock position (left/center/right), am/pm, battery % inside icon, network traffic meter, hide notification icons (the "hide notch icons" item) | crDroid 17.0 |
| Lockscreen clocks | Google's own clock plugins (SystemUIClocks-*), the same ones crDroid ships, imported from the stock husky image by `tools/apps/import-pixel-clocks.sh`. Proprietary, so they stay out of git and must not be published. | stock Pixel image |
| Power menu | **Classic Power Menu** ([bjakra/ClassicPowerMenu](https://github.com/bjakra/ClassicPowerMenu), Apache 2.0) replaces the long-press menu as a platform-signed system app, no root needed. Patch 0510 opens it and falls back to the system menu, whose action list stays editable in Graphite settings. Keeps its settings icon in the app drawer | KieronQuinn |
| Generic wallet | (1) If the chosen wallet implements `QuickAccessWalletService`, show its cards. (2) Otherwise, show a button that launches the **default NFC payment app** (`CardEmulation.getDefaultServiceForCategory(CATEGORY_PAYMENT)`), which covers Sparkasse "Mobiles Bezahlen" and others without wallet support | new |
| Charging info | lockscreen indication line with V / A / W (+ temperature) from `BatteryManager` / `power_supply` | crDroid `KeyguardIndicationController` |
| FLAG_SECURE / stealth screenshots | see below | crDroid, new |

### FLAG_SECURE: per-app override, system-only capture (decided)

* Graphite settings → "Screenshot protection override": an app list (like GrapheneOS's per-app
  toggles). Stored in `Settings.Secure.graphite_secure_override_packages`.
* For listed apps, windows keep FLAG_SECURE, but **system captures may include them**:
  * SystemUI screenshots request secure layers (`captureSecureLayers=true`; SystemUI holds
    `CAPTURE_BLACKOUT_CONTENT`) only when the top task's package is on the list.
  * SystemUI's own screen recorder gets the same treatment, per window (patch 0490), so unlisted
    protected apps stay black. Third-party MediaProjection, casting and recents thumbnails remain blacked out.
* Stealth option per list (or global toggle): suppress `Activity.ScreenCaptureCallback`
  notifications for system screenshots of listed apps. Optionally save those screenshots outside
  MediaStore so apps with media permission can't spot them.
* Off by default (empty list).

## 4. Suggested extra features

Ordered by value / effort:

1. **Locked bootloader with your own keys + OTA updates** from your own update server (GrapheneOS's
   Updater + `generate-delta.sh` already exist; you only need a static web host).
2. **Advanced restart** in the power menu: recovery, bootloader, restart SystemUI, soft reboot.
3. Gestures: double-tap status bar / lockscreen to sleep, 3-finger screenshot, long-press volume
   to skip tracks (screen off), torch by long-pressing power while the screen is off.
4. Navigation: hide the gesture pill, adjust the back-gesture height.
5. Per-app network/sensor toggles exist in GrapheneOS already, so don't duplicate them. Instead, add
   a **firewall-style "no internet" quick tile** for the foreground app.
6. QS: tiles for heads-up toggle, AOD, USB tethering, sync, data switch, and a "reboot to …" tile.
7. Battery: charging limit (the Pixel 8 supports an 80% limit via sysfs/HAL) and charging-speed info.
8. **A daily `update.sh validate` cron job** that reports when a new GrapheneOS tag breaks a patch,
   before you even try to update.
9. Monet/theming extras (custom accent seed, icon shapes). Lawnchair covers launcher icons.
10. A KernelSU module for hosts-based ad blocking (systemless, easy to switch off).

## 5. Order of work

| Phase | Content | Why first |
|---|---|---|
| A | Settings keys, GraphiteParts skeleton, emulator build | everything else plugs into this |
| B | Caffeine tile, icon manager + seconds, charging info, power-menu actions | small and well understood; good for exercising the patch pipeline |
| C | Kernel pipeline → KernelSU-Next + SUSFS; own AVB key | needs the device build; high value |
| D | FLAG_SECURE screenshots | framework patches; test in the emulator |
| E | Clock plugin; A11 power menu + wallet | larger SystemUI work |
| F | Lawnchair A17 Quickstep port + Smartspacer + search | biggest and riskiest; the fallback launcher stays meanwhile |

## Status (2026-11-02)

Search: the PixelishSearch fork was dropped in favour of Lawnchair's own search, restyled to match it, and deleted.

