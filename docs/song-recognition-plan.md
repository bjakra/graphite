# Plan: offline song recognition (backlog item 19)

Goal: a Now Playing style service that recognises music playing nearby, offline, off by default, with a switch in
Graphite settings and an optional step in setup. When it is off, nothing listens to the microphone.

Status: decided 2026-11-03, waiting for one manual download (below).

Decisions (user, 2026-11-03): option A with Google's model and database, on the condition that it is fully private: no
network access at all, no way to talk to Google or other apps, and the database only changes with OS updates. When the
service is enabled, the microphone privacy indicator and its "active apps" entry are hidden.

## The database is the hard part

| Option | Recognition | Song database | Coverage | Concerns |
|---|---|---|---|---|
| A. Google's Now Playing, through a fork of Ambient Music Mod (GPL-3.0) | Google's on-device model in the Now Playing APK | Regional shards that Google publishes, downloaded once and then used offline | Same as a Pixel, tens of thousands of popular songs per region | Proprietary APK and data, like the clock faces; downloads come from Google's servers (a download only, no audio leaves the phone) |
| B. Open source fingerprinting (Chromaprint and similar) | Open code | None exists that is offline and broad; it would have to be built | Only songs added by hand | Not useful as a Now Playing replacement |

Recommendation: A. It is what Ambient Music Mod and other ROMs use, and recognition stays on the device.

## Design for option A

* **Fork** `KieronQuinn/AmbientMusicMod` to `bjakra/AmbientMusicMod`. Replace its Shizuku and accessibility parts with
  system app permissions, as was done for the other apps. Ship it platform signed in `system_ext/priv-app`, with no
  launcher icon; its settings open from Graphite settings.
* **Database:** downloaded on first enable, over Wi-Fi only by default, stored in the app's credential encrypted
  storage. The Now Playing APK itself is bundled in the vendor repo, like the clock APKs.
* **Off by default.** The service is disabled with `PackageManager` while off, so it cannot run or open the
  microphone at all, not just stay idle.
* **Setup:** one optional page in setup (Off by default), the same switch as in Graphite settings.
* **Microphone indicator:** hiding it means exempting this one package from the privacy indicator in the framework.
  That relaxes a privacy feature, so it would be its own clearly described patch, limited to this package and to the
  short recognition windows. Recommendation: keep the indicator on at first, decide after trying it.
* **Results:** history in the app, and the current song on the lock screen and in Lawnchair's At a Glance.

## How it is built (decided)

No Ambient Music Mod app. Its features are rebuilt inside Graphite (user, 2026-11-03: "replicate all of its features
and integrate them into the system", in a dedicated Now Playing page in Graphite settings).

* **Engine (the only part that is not Graphite code):** Kieron Quinn's Now Playing, a rebuild of Google's Android
  System Intelligence cut down to music recognition. Shipped headless in `system_ext/priv-app`: no launcher icon, no
  screens of its own, platform signed. It only does recognition (Google's model, on device) and stores the database.
* **Graphite Now Playing, in GraphiteParts:** the recognition service, scheduling, history database, the settings page,
  the Quick Settings tile, database updates, and the data the lock screen and At a Glance show.
* **Network:** the engine never opens connections itself; all of its HTTP goes through the Astrea service (Google's open
  source Private Compute Services, Apache 2.0), which Ambient Music Mod hosted. In Graphite the engine has no
  `INTERNET` permission at all, and Astrea is hosted by a tiny separate app, `org.graphite.musicdb`, the only part that
  declares `INTERNET`. On GrapheneOS that is a runtime permission: it stays revoked, and only a database update (button
  or schedule, both chosen by the user) grants it until the download ends or fails. Astrea also refuses requests
  outside an update. GraphiteParts itself gets no network. On Demand recognition (sends audio to Google) is not ported.
* **Engine build:** `tools/apps/build-nowplaying.sh` (fork bjakra/NowPlaying, branch graphite). The rebuilt APK keeps
  only the three native libraries recognition loads, arm64 only for the ROM (83 MiB, below GitHub's 100 MiB limit),
  and is committed to the vendor repo as `GraphiteNowPlayingEngine`.
* **Database in the ROM:** the build host downloads the current database before a release, so a fresh install works
  offline. Automatic updates are off by default.
* **Privacy indicator:** SystemUI patch hiding the microphone indicator and the active-apps entry for the engine and
  GraphiteParts' recognition only while Now Playing is on. The patch says it relaxes a privacy indicator.

### Architecture (user choice 2026-11-03: headless AMM core + Graphite UI)

* **Graphite Now Playing core:** fork bjakra/AmbientMusicMod, branch `graphite`, package `org.graphite.nowplaying`. AMM's
  service, repositories and workers stay as they are (same code means same behaviour; upstream fixes can be merged).
  Removed: all screens and the launcher entry, Shizuku, GitHub update checks, On Demand, network. Added: an API for
  Graphite settings (settings, history, track list, actions). Hidden system component in `system_ext/priv-app`.
* **Graphite settings, Now Playing page:** the only UI. Talks to the core through that API.
* **Engine** (`com.kieronquinn.app.pixelambientmusic`, bjakra/NowPlaying): host package becomes `org.graphite.nowplaying`.
* **Downloader** `org.graphite.musicdb`: AMM's `astrea` module as its own tiny app, the only one with `INTERNET`.

### Shizuku replaced in-process (ShizukuService, run as shell by AMM)

Rule: same behaviour as AMM; where something changes, the reason is written here.

| ShizukuService method | Graphite core (same process, platform signed priv-app) |
|---|---|
| AudioRecord_* (AudioRecord built with a shell context) | Same calls, built with the core's own context; needs `RECORD_AUDIO` and `CAPTURE_AUDIO_HOTWORD`. Attribution is the core instead of Shell. Background recording needs the core's foreground service to be of type microphone (started at boot through the `START_ACTIVITIES_FROM_BACKGROUND` exemption); shell was exempt |
| isCompatible, isRoot, ping | true, false, true: the core always has the permissions, never root |
| MusicRecognitionManager_* | Only used by On Demand, which is not ported (sends audio to Google) |
| is/add/removeMicrophoneDisabledListener | Same SensorPrivacyManager calls; `OBSERVE_SENSOR_PRIVACY` |
| getSystemUIPackageName | Same |
| dismissKeyguard | Same IWindowManager call; `CONTROL_KEYGUARD` |
| setOwnerInfo | Root only in AMM, so a no-op there without root; replaced by the native lock screen line |
| forceStopNowPlaying (`am force-stop`) | `ActivityManager.forceStopPackage`, the API `am force-stop` calls; `FORCE_STOP_PACKAGES` |
| expediteJobs (`cmd jobscheduler run [-f]`) | Android only accepts that command from ADB, so the engine reschedules its own jobs (ExpediteJobsReceiver): without delay and with conditions, or without conditions when forced |
| onCreate: grant notification / restricted-settings permissions | Granted by the ROM's default permissions instead |
| destroy | Not needed: nothing to tear down outside the core's own process |

### Ambient Music Mod features and where they go

| AMM feature | Graphite |
|---|---|
| Enable Now Playing, setup | Switch at the top of the Now Playing page (off by default), optional page in setup |
| Recognition period, adaptive period | "How often": list of intervals, adaptive switch |
| Recognition buffer (recording length) | "Listening time" |
| Trigger when screen is on | Switch |
| Bedtime mode (start, end) | "Pause at night" with start and end time |
| Recognise now | Button on the page, Quick Settings tile, At a Glance tap |
| Lock screen overlay (style, position, colour, shadow, on-click action) | Native: song line on the lock screen drawn by SystemUI in its own style; on-tap action setting (history, search the song, nothing) |
| Owner info on lock screen | Not needed, replaced by the native lock screen line |
| Notification of recognised songs | Optional, silent notification like the Pixel's |
| History, favourites, summary | History screen on the page: list, favourites, delete, most heard |
| Track list (artists, tracks, track info) | "Songs in the database" screen with search |
| Database country, extra countries | Country picker plus extra countries |
| Automatic database updates | "Database updates": Update now, automatic Off / daily / weekly / monthly, Wi-Fi only, with a warning that only this download connects to Google's servers |
| Database info | Version, date and track count on the page |
| Backup and restore, periodic backup | Export and import of the history, optional periodic backup to a chosen folder |
| Battery optimisation, Shizuku, accessibility setup | Not needed in a system component |
| On Demand (online recognition) | Not ported: sends audio to Google |
| Home screen widget | At a Glance card in Lawnchair plus the Quick Settings tile |
| Microphone indicator | Hidden while enabled (SystemUI patch) |

Code from Ambient Music Mod (GPL-3.0) may be ported into GraphiteParts where it saves work; GraphiteParts then has to be
distributed under GPL-3.0, which fits an open source ROM.

## Manual step for the user

Google's Android System Intelligence APK can only be downloaded from APKMirror, which blocks scripts. Download in a
browser: "Android System Intelligence U.0.droidfood.pixel6.514591756" (arm64-v8a, the APK, not the bundle), from
https://www.apkmirror.com/apk/google-inc/device-personalization-services/device-personalization-services-u-0-droidfood-pixel6-514591756-release/
and save it as `apps/NowPlaying/base.apk`. The x86_64 build of the same version is needed for emulator testing
(`apps/NowPlaying/base-x86_64.apk`).

## Answered questions

1. Option A with Google's model and database? Yes, if fully offline and only updated with the OS.
2. Hide the microphone indicator for this service, or keep it? Hide it, and the active-apps entry, while enabled.

## Engine on Android 17: findings (2026-11-03)

* GrapheneOS blocks runtime code changes in system apps; the engine is on the allowlist (overlay, user decision 1a).
* Kieron Quinn's engine used AliuHook main-SNAPSHOT with LSPlant 6.4 (2024), which fails on Android 17's ART
  ("Failed to init instrumentation"). Fixed by building LSPlant from upstream master (Android 17 support) on Aliucord's
  packaging (`apps/hooks/lsplant`, 6.4-aliucord.4-graphite.1) and AliuHook against it (`apps/hooks/aliuhook`,
  1.1.4-graphite.N), both published to the local Maven repo (`~/.m2`). Needs NDK 30.0.16248370 + CMake 3.31.6 in `sdk/`.
* `extractNativeLibs=false` and 16 KB alignment: a preinstalled app has no extracted lib folder.
* Engine binder shell commands (`cmd jobscheduler run`) only work from ADB: replaced by the engine's
  ExpediteJobsReceiver, which reschedules its own jobs.
* Hook libraries: public forks github.com/bjakra/LSPlant and github.com/bjakra/hook (branch `graphite`, needed for the
  arm64 ROM); the emulator-only Dobby fix lives in private repos bjakra/dobby-graphite and bjakra/dobby-android-graphite.
  `tools/apps/build-hooks.sh` builds them in order into `~/.m2`, using the private Dobby only when it is checked out.
* **Fixed (x86_64 emulator only):** the engine aborted ~20 s after start in ART's userfaultfd GC ("mremap to move pages
  failed: Bad address"). Cause: Dobby (AliuHook's inline hooker) on x86_64 puts the address table for its
  `jmp [rip+x]` hooks in a page within 2 GB of libart, which lands inside ART's LinearAlloc reservation; ART then can't
  move that region. `dobby_disable_near_branch_trampoline()` does not help on x64. On arm64 Dobby inlines the address
  (`ldr x17, #8; br x17`), so the phone should not be affected. Fix candidates: Dobby x64 with inline 14-byte
  absolute jumps, or keep the slot page out of ART's reservations.

### Database freshness (checked 2026-11-03)

* Google still publishes the database weekly in the format the engine reads (`music-iq-db/updatable_db_v3/`, 189
  versions, newest 20261101). Kieron Quinn's `AmbientMusicManifest` (`release_v3.json`) is still updated (commit
  2026-11-03) and points at the newest one (version 3188). AMM's built-in default (20240901, v3099) is only used until
  its first check.
* In Graphite the core has no network, so both the manifest check (raw.githubusercontent.com) and the database
  download (storage.googleapis.com, through Astrea) go through `org.graphite.musicdb`, only during a user-started or
  scheduled update. The ROM build sets the default to the newest manifest at build time, so a fresh install starts
  with the database current at that build.
