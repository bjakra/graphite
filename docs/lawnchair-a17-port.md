# Lawnchair → Android 17 Quickstep port

Fork: `github.com/bjakra/lawnchair`, branch `graphite` (= upstream `16-dev` @ 849fec9).
Local clone: `apps/lawnchair/`. Trial merge worktree: `apps/lawnchair-a17/` (branch
`graphite-a17-merge`, merge of AOSP `android-17.0.0_r1` in progress, conflicts unresolved).

## How Lawnchair is built

* The repo **is** AOSP Launcher3's git history plus Lawnchair commits. Upstream versions arrive as
  plain merges (`Merge tag 'android-16.0.0_r3' into 16-dev`), so an Android 17 port follows the same
  procedure with `android-17.0.0_r1`, the tag our GrapheneOS tree is based on.
* It compiles against JARs built from a full Android tree (`prebuilts/libs/`):
  `framework-N.jar` (turbine stubs incl. hidden API), `SystemUI-core-N.jar`,
  `SystemUI-statsd-N.jar`, `WindowManager-Shell-N.jar`. **Our emulator build produces all four
  from GrapheneOS 17** (paths in `prebuilts/libs/README.md`, OUT_DIR `src/out-emu`).
* `systemUI/` and `wmshell/` hold source copies of SystemUI-shared / WM Shell pieces (AIDL contracts
  and helpers). Submodule `platform_frameworks_libs_systemui` is
  LawnchairLauncher's fork of `platform/frameworks/libs/systemui` (also needs forking + a 17 merge).
* `compatLib/` is thin: per-Android-version `ActivityManagerCompat` / `ActivityOptionsCompat` /
  `QuickstepCompatFactory` (`VQ` … `VBaklava`). Android 17 needs `compatLibVCinnamonBun`
  (`Build.VERSION_CODES.CINNAMON_BUN = 37`).
* Release builds gate Quickstep to SDK 35–36 (`quickstepMinSdk/MaxSdk` in `build.gradle`). Debug builds
  have no gate. The app also requires `config_recentsComponentName` to point at its own
  `com.android.quickstep.RecentsActivity` (`LawnchairApp.checkRecentsComponent`).

## Size of the job (measured 2026-11-01)

| Measure | Value |
|---|---|
| AOSP Launcher3 16.0.0_r3 → 17.0.0_r1 | 2 425 files, +170 806 / −83 123 lines |
| Lawnchair changes to AOSP files | ~455 modified files (plus its own `lawnchair/` tree) |
| Trial merge conflicts | **438 files, 1 032 hunks**: 298 content, 85 add/add (mostly widget-picker resources), 52 Lawnchair-modified files deleted in AOSP 17, 1 rename/delete |
| Hardest files (hunks) | DeviceProfile 20, Launcher 14, AbsSwipeUpHandler 14, InvariantDeviceProfile 13, FolderSpringAnimatorSet 13, Folder 12, ActivityAllAppsContainerView 12, TaskbarView 12 |

## IPC contract changes (Launcher ↔ SystemUI / WM Shell), A16 → A17

These decide whether Recents works at runtime. Lawnchair 16's AIDL copies vs. our A17 tree:
26 identical, **13 changed**, 5 gone.

* **`IRecentsAnimationRunner.onAnimationStart`**: the `minimizedHomeBounds` parameter was removed.
  This is the swipe-up-to-Recents path. Lawnchair 16 would unparcel the wrong layout, so the
  gesture breaks at runtime. **A merge is required, not just a compat shim.**
* `ISystemUiProxy`: `onBackEvent(KeyEvent, int displayId)`, `onOverviewShown` renamed to `…Deprecated`,
  new `onKeyEvent` / `onOverviewShown(displayId)` / `onOverviewHidden(displayId)` (60–62).
* `ILauncherProxy`: new `invokeContextualSearch(int, ContextualSearchConfig)` (= 40).
* Changed: `IBubbles`, `IBubblesListener`, `IDesktopMode`, `IDesktopTaskListener`,
  `ISplitSelectListener`, `IPipAnimationListener`, `BubbleBarLocation`, `IOriginTransitions`, `IRemoteCallback`.
* Gone in A17: `IOverviewProxy` (long replaced by `ILauncherProxy`), `GroupedRecentTaskInfo.aidl`,
  and Lawnchair's `IShellTransitions2` / `IHomeTransitionListener2` / `IFocusTransitionListener2` compat copies.

## Plan

1. **Prebuilts:** copy the four JARs from `src/out-emu` as `*-17.jar`, plus an A17 `framework.jar`.
2. **Interface layer:** refresh `systemUI/` and `wmshell/` from `src/frameworks/base` (GrapheneOS 17),
   then fork + merge `platform_frameworks_libs_systemui` @ `android-17.0.0_r1`.
3. **Launcher3 merge**, resolved in this order (compile after each step against the A17 jars):
   resources/add-add → `src/` core (DeviceProfile, Launcher, Workspace, folders, all-apps) →
   `quickstep/` (swipe handler, RecentsView/TaskView, taskbar) → tests last (or drop Lawnchair's
   test changes).
4. `compatLibVCinnamonBun` + raise `quickstepMaxSdk` to 37.
5. Test on the stock A17 emulator (root, `tools/testing/lawnchair-on-emulator.sh`), then on the
   GrapheneOS emulator build, then on husky.
6. ROM integration: app pipeline builds the APK → `prebuilts/graphite/Lawnchair`, platform-signed
   priv-app, privapp allowlist, `config_recentsComponentName` overlay, default home. GrapheneOS's
   Launcher3 stays as the fallback Recents provider (overlay switch).

## Test environment (works today, independent of the ROM build)

* SDK at `sdk/` (cmdline-tools, platform 37.2, build-tools 37.0.0, emulator, AOSP image
  `system-images;android-37.0;default;x86_64`). AVD `graphite-a17-stock` in `sdk/avd/`
  (writable system, `adb root`, verity off).
* `tools/testing/lawnchair-on-emulator.sh <apk>` re-signs the APK with the AOSP **platform test key**
  (the stock image uses test keys, so signature permissions are granted), installs it as a
  priv-app with a generated privapp allowlist, adds a static framework overlay setting
  `config_recentsComponentName`, reboots, and makes it home. This is exactly the integration the
  ROM will ship.
* Build: `JAVA_HOME=src/prebuilts/jdk/jdk21/linux-x86 ANDROID_HOME=sdk ./gradlew assembleLawnWithQuickstepGithubDebug`
  (`GRADLE_USER_HOME=sdk/gradle-home`).

## Baseline test: unmodified Lawnchair 16 (849fec9) on stock Android 17 (CE2A.260420.051.A3)

| Test | Result |
|---|---|
| As a normal home app (no Quickstep) | ✅ works: home, dock, search bar, drawer. Recents stays with the system launcher. |
| As platform-signed priv-app + `config_recentsComponentName` overlay (Quickstep) | ❌ `TouchInteractionService.onCreate` crashes immediately: `NoSuchMethodError: IWindowManager.createInputConsumer(IBinder,String,int,InputChannel)`. A17 changed it to `InputChannel createInputConsumer(IBinder,String,int)`. SystemUI's `LauncherProxyService` then retries forever ("connection to service timed out"), and gestures do nothing. |

So the privileged integration itself works (SystemUI binds Lawnchair's `QUICKSTEP_SERVICE`, and
signature permissions are granted). What fails is purely the A16 Quickstep code against the A17
framework/WM Shell APIs, as predicted by the AIDL diff. Compiling against the A17 `framework.jar`
(already produced at `src/out-emu/soong/.intermediates/frameworks/base/framework/android_common/turbine-combined/framework.jar`)
will list these breaks at build time instead of one per runtime crash.

## Status (2026-11-01, merge stage)

* `apps/lawnchair-a17` (branch `graphite-a17-merge`): AOSP `android-17.0.0_r1` merged, **all conflicts resolved, not yet committed, never compiled**.
  Rule used: AOSP wins over Lawnchair's old-Android guards; Lawnchair features are kept or logged.
* Submodule `platform_frameworks_libs_systemui` (local branch `graphite`, from `bjakra/…`): AOSP 17 merged the same way, uncommitted.
* `systemUI/`, `wmshell/`: 3-way refreshed from `src/frameworks/base` against `android-16.0.0_r3` (cached in `state/cache/fb16.git`).
* Reapply list: `docs/lawnchair-port/TODO-reapply.md`. Saved Lawnchair diffs for files AOSP rewrote: `docs/lawnchair-port/lost-deltas*/`.
* Next: `tools/testing/lawnchair-collect-prebuilts.sh`, add `compatLibVCinnamonBun`, compile loop, reapply list, runtime test.

## Status (compile stage)

Compiles against Android 17: compatLib (incl. new compatLibVCinnamonBun), flags, iconloaderlib,
displaylib, viewcapturelib, tracinglib (added), mechanics, animationlib, msdllib, log, common,
unfold, animation, wmshell, and the Kotlin half of shared.

Blocked until the ROM build produces the real `WindowManager-Shell`, `SystemUI-core` and
`SystemUI-statsd` JARs: `prebuilts/libs/*-17.jar` for those three are **temporary stand-ins**
(Android 16 copies, untracked; the WM Shell one has its shared classes removed). Errors about
window-manager classes are unreliable until `tools/testing/lawnchair-collect-prebuilts.sh` replaces them.
Known stand-in error: `PipSurfaceTransactionHelper` / `IPipAnimationListener.PipResources`.

Tools: `tools/testing/lawnchair-gradle.sh` (gentle Gradle runner, errors only),
`tools/testing/lawnchair-regen-flags.py` (flags/ from Android 17 aconfig output, with the Lawnchair
override table: enableQsbOnHotseat, forceMonochromeAppIcons, homeScreenEditImprovements).

## Status (main app compile)

`tools/testing/lawnchair-collect-prebuilts.sh` now merges the real Android 17 JARs (javac + kotlin + aidls).
All library modules compile. Main app Kotlin, with KSP skipped: 1383 errors on first compile, now about 290,
of which ~280 are in Lawnchair's own `lawnchair/` code. Java errors and Dagger (KSP) will only show after those.
Current list: `state/lc-errors.txt`. Command:
`tools/testing/lawnchair-gradle.sh -x :kspLawnWithQuickstepGithubDebugKotlin :compileLawnWithQuickstepGithubDebugKotlin`

Removed (need Google-internal libraries): workspace app functions, Ambient Cue bar (`CueBarController` is a
no-op stub), computer control automation (uses AOSP's `AutomationNoOpRepository`).

## Status (runtime, 2026-11-01)

The whole app compiles (Kotlin, Java, Dagger/KSP) and the APK builds:
`tools/testing/lawnchair-gradle.sh :assembleLawnWithQuickstepGithubDebug`.

Tested as a platform-signed priv-app with the `config_recentsComponentName` overlay
(`tools/testing/lawnchair-on-emulator.sh`) on the stock Android 17 emulator **and on the GrapheneOS
17 emulator build** (`./dev.sh run`):

| Test | Result |
|---|---|
| Home screen, dock, search bar, smartspace | ✅ |
| App drawer (via long-press → Apps list), Lawnchair settings | ✅ |
| Recents button (`KEYCODE_APP_SWITCH`) | ✅ overview with task card |
| Swipe-up gesture from an app | ✅ recents animation runs, held swipe shows the task card |
| Swipe up on home to open the drawer with `adb input swipe` | ❌ opens and closes again. Stock Launcher3 behaves the same with injected swipes, so check this by hand |

Fixes needed to get here: Dagger KSP stack overflow (RecentsView field injection → `RecentsViewDependencies`),
ThemeManager constructor reading subclass state, platform aconfig `Flags` classes that the boot classpath
hides from apps (now compiled into `flags/`, see `tools/testing/lawnchair-regen-flags.py`), and a dbFile race in
`InvariantDeviceProfile` that reset the home screen database.

Tools: `tools/testing/dex-missing-classes.py APK boot-jars…` lists classes the APK references that neither the
APK nor the device defines (catches NoClassDefFoundError before running). `tools/testing/lawnchair-emu-log.sh`
restarts Lawnchair and prints any startup crash.

When Lawnchair takes over Recents, GrapheneOS's Launcher3 crashes if it is launched (it loses the role permissions).
That is expected; the ROM should leave Launcher3 disabled while Lawnchair is the Recents provider.

Next: hand testing of gestures, then the reapply list (`docs/lawnchair-port/TODO-reapply.md`), then ROM integration
(prebuilt module, privapp allowlist and overlay as a patch).
