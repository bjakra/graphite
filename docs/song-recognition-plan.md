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
