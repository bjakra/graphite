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

* Two apps, both forks by Kieron Quinn: Ambient Music Mod (manager, GPL-3.0) and Now Playing (Android System
  Intelligence rebuilt with apktool down to the music recognition part). Both are rebuilt with Graphite's platform key
  and shipped in `system_ext/priv-app`, neither declares `INTERNET`, so the kernel blocks all network sockets for them.
* AMM's privileged half (`ShizukuService`, the `IShellProxy` implementation) runs inside AMM itself instead of through
  Shizuku: as a platform signed system app it has the permissions directly.
* Recording goes through Android's own `MusicRecognitionManager`, with Now Playing set as
  `config_defaultMusicRecognitionService` in Graphite's framework overlay.
* Database: downloaded once on the build host (never on the phone), stored outside git (Google's files must not be
  published), copied into the ROM, and copied into Now Playing's storage on first enable. New database only with an
  OS update.
* Privacy indicator: a SystemUI patch that hides the microphone indicator and the active-apps entry for these two
  packages only while the Secure setting for the service is on. The patch says it relaxes a privacy indicator.

## Manual step for the user

Google's Android System Intelligence APK can only be downloaded from APKMirror, which blocks scripts. Download in a
browser: "Android System Intelligence U.0.droidfood.pixel6.514591756" (arm64-v8a, the APK, not the bundle), from
https://www.apkmirror.com/apk/google-inc/device-personalization-services/device-personalization-services-u-0-droidfood-pixel6-514591756-release/
and save it as `apps/NowPlaying/base.apk`. The x86_64 build of the same version is needed for emulator testing
(`apps/NowPlaying/base-x86_64.apk`).

## Answered questions

1. Option A with Google's model and database? Yes, if fully offline and only updated with the OS.
2. Hide the microphone indicator for this service, or keep it? Hide it, and the active-apps entry, while enabled.
