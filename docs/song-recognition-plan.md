# Plan: offline song recognition (backlog item 19)

Goal: a Now Playing style service that recognises music playing nearby, offline, off by default, with a switch in
Graphite settings and an optional step in setup. When it is off, nothing listens to the microphone.

Status: plan only. Needs a decision on the database (below) before work starts.

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

## Open questions for the user

1. Option A with Google's model and database?
2. Hide the microphone indicator for this service, or keep it?
