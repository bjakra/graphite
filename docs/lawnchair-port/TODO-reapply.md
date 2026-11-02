# Lawnchair hooks to re-apply after the merge compiles

AOSP 17 rewrote these areas, so conflict resolution took AOSP's structure.

- HotseatProfile: `hotseatMode` / `isQsbEnable` (dock search bar on/off, qsb height 0 when off). NEEDED for the search bar feature.
- DepthController: `mEnableDepth` (wallpaper depth pref), `clearWorkspaceRenderEffects()` on NORMAL.
- BubbleView: Lawnchair notification dot colours.
- TaskbarViewController: `getIgnoreTaskbarIconCount`.
- BubbleTextView: drawer-folder `newIcon(.., shouldUseTheme())`, prediction-row dot renderer, `enableLabelInDock` in shouldTextBeVisible.
- AllAppsState: Lawnchair scrim colours (ColorTokens).
- OverviewState: scrim colour token.
- OptionsPopupView: Lawnchair's getOptions list (AOSP removed the method).
- Utilities.getFullDrawable: wrap-adaptive-icons / icon-pack check (AOSP moved it).
- WorkspaceItemSpaceFinder: don't place new items on the smartspace row (AOSP dropped the QSB reservation).
- lost-deltas/: Lawnchair edits to files AOSP rewrote in Kotlin or removed. Review all.
- HotseatPredictionController: took AOSP HotseatOrganizer; Lawnchair's paged-dock prediction logic dropped (recheck predictions on paged docks; multiply count by numHotseatRows).
- TaskbarView: Lawnchair's `getIgnoreCountForTaskbarIcons` + `hotseatMode` QSB handling (taken AOSP).
- BaseDepthControllerImpl: stuck-blur fix (clear RenderEffect on settled NORMAL), wallpaper zoom max with mWallpaperZoomOnly.
- InvariantDeviceProfile: **core feature** — Lawnchair's custom grid (DeviceProfileOverrides.DBGridInfo, previewOverrides, static getCurrentGridName, public grid constants, Preview ctor, parseAllGridOptions). AOSP moved GridOption out of this class; re-wire overrides into initGridForDisplayOption.
- ActivityAllAppsContainerView: drawer opacity / header colour / cached bottom-sheet colour (ColorTokens); took AOSP.
- DeviceProfile: **core feature** — TextFactors, drawer cell height, workspace/widget/drawer padding factors, taskbar pref, page indicator factor, numHotseatRows/numHotseatPages, isQsbEnable. Took AOSP structure; add fields back and feed them into the *Profile factories.

## platform_frameworks_libs_systemui (submodule, merged with android-17.0.0_r1)
- FastBitmapDrawable: hardware-bitmap software-canvas crash fix must move into delegate.drawContent.
- MonochromeIconFactory wrap: check shouldForceMonochrome behaviour.
- IconNormalizer / ShadowGenerator: took AOSP.
- BaseIconFactory, ClockDrawableWrapper, GraphicsUtils, PlaceHolderIconDrawable: AOSP moved to Kotlin. Lawnchair edits NOT carried yet, see lost-deltas-systemui/ (BaseIconFactory and ClockDrawableWrapper are big: icon packs, clock icons).

## Reset to clean AOSP 17 during the compile stage (Lawnchair logic to restore)
Recover with `git diff aosp-16.0.0_r3 849fec9ef6 -- <file>`:
- src/.../states/EditModeState.kt (page strip in edit mode), src/.../ModelCallbacks.kt (persisted screen order),
  src/.../deviceprofile/AllAppsProfile.kt (cellHeightMultiplier), src/.../graphics/ShapeDelegate.kt,
  src/.../model/WorkspaceItemProcessor.kt, quickstep/.../util/ScalingWorkspaceRevealAnim.kt,
  quickstep/.../OverviewCommandHelper.kt, quickstep/.../views/TaskView.kt, quickstep/.../util/ContextualSearchInvoker.kt,
  quickstep/.../dagger/PerDisplayModule.kt, quickstep/.../taskbar/TaskbarRecentAppsController.kt
- LoaderTask: reset to AOSP 17 (kept `|=` quiet fix). Check Lawnchair's getActivityList SecurityException workaround for non-main users (issuetracker 547643926) and WIDGET_ON_FIRST_SCREEN.
- SystemUiProxy, LauncherDbUtils (Lawnchair 13 upgrade compat), LauncherRestoreEventLoggerImpl, DesktopTaskView, QuickstepTestInformationHandler: reset to AOSP 17; Lawnchair's edits there were compat for other Android versions.

## Added during main-app compile

* `LawnchairFloatingSurfaceView.getBackgroundAnimator`: A17 has no disposable DepthController. It now animates the launcher's own controller; check the blur during the home transition at runtime.
* `DeviceProfile.shouldShowAllAppsOnSheet`: A17 dropped this. Restored as `isLargeScreen`. The old `allAppsSheetForHandheld` flag no longer exists, so check phones at runtime.
* Widget prediction: removed from `LawnchairAppPredictor` and `LawnchairModelDelegate`, because A17 dropped `WidgetsPredictionUpdateTask`.
* `ReloadHelper.reloadTaskbar`: no-op while SysUI isn't connected (it used to wait for the bind).
* `clearAllViewsFromHomeScreen`: runs as a model task, so it does nothing until the model has loaded.
* Removed widget-picker `DrawableTokens`, because A17 dropped those drawables: the picker no longer follows Lawnchair's theme colours. Check it at runtime.
* `AsyncClockEventDelegate`: reset to AOSP. Lawnchair's holder class only existed to support Android versions below 15, which this build doesn't target.
* `tests/shared/.../testcomponent` and `util/rule`: deleted from this fork. They need test libraries and aren't used by the app.
* `moveWorkspaceScreensInDatabase` and `persistWorkspaceScreenOrderSync` were ported to `ModelWriter.kt`. Check reordering home pages at runtime, including that a stale load id doesn't skip `onComplete`.
* `QuickstepBaseAppComponent.getInsightHandler`: removed along with the Ambient Cue bar.
* `DepthController`, `BaseDepthControllerImpl`: reset to AOSP. Kept the wallpaper depth setting and `clearStuckBlurOnResumeIfHome` (now in `LauncherDepthController`). Dropped Lawnchair's other stuck-blur guards; check that blur clears after All Apps at runtime.
* `TaskbarOverlayController`: early wakeup restored as in AOSP (Lawnchair had it disabled).
