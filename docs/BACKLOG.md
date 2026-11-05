# Backlog

The user's feature and bug list from 2026-11-03, in the order it will be worked on. Update the Status column as items
land. Rule for every item: anything with a setting gets it in the UI (Graphite settings, Lawnchair settings or setup), and
every existing toggle has to actually do what it says.

| # | Item | Area | Plan | Status |
|---|---|---|---|---|
| 1 | KernelSU-Next manager says "Not installed" | Kernel | The kernel finds its manager by scanning `/data/app` only, and Graphite ships the manager in `/system_ext/app`. Make the kernel also accept the preinstalled manager. | Fixed in two kernel changes: the preinstalled manager is accepted, and since the exec hooks miss second stage and zygote on this kernel, the first app start catches up and scans. Next release |
| 2 | Remove Classic Power Menu | Power menu | Drop the app, patch 0510 and Parts' switch. The system power menu becomes the only one again. | Done: app, patch 0510 and Parts switch removed |
| 3 | Reboot options in the system power menu | Power menu | Restart, recovery, bootloader and SystemUI restart are already selectable (patch 0410). Group them under Restart as a submenu like other ROMs, add haptics, keep the editor in Graphite settings. | Done (patch 0520): Restart opens a compact submenu, haptics on every tap, switch in Graphite power menu settings |
| 4 | Remove Smartspacer, port its useful parts into Lawnchair's At a Glance | Launcher | Lawnchair's own smartspace (date, weather, calendar, alarm, battery, media) styled like the Pixel's, with weather from Graphite Weather. Delete the app, prebuilt, fork branch use and docs. | Done: Smartspacer removed. At a Glance: one date card with Graphite Weather (always first; the duplicate date page is gone), next event, next alarm, running timer with end time or stopwatch, latest missed call, Do Not Disturb, Bluetooth headphone battery, each with a switch. Headphone battery to be checked on the phone |
| 5 | Search opens slowly, results jump while typing | Launcher search | Open the search UI without the delay. Keep a stable result order while typing: no "Search on Play Store" row that appears and is pushed down when other results arrive. | Partly done: no more drawer flash, open transition 450 ms, results wait for all sections (250 ms), ranking refreshed in the background. Needs a check on the phone |
| 6 | Search settings toggles don't do anything (for example Android settings) | Launcher search | Check every toggle on the search settings page and wire each one up. | Done: "Apps and shortcuts" was never read; "Android settings" now also hides the Settings app's own shortcuts (Wi-Fi, Battery), which were the results that stayed |
| 7 | Material You search bar on home and in the app drawer | Launcher search | Google-style bar with more theming (colours from the wallpaper, shape, icons), same look in both places. | Done: Colour setting for both bars. Default "Automatic" is strong Material You (primary) while themed icons are on and Lawnchair's colours otherwise; neutral, primary, secondary, tertiary and Lawnchair are manual overrides |
| 8 | Quick settings search results lack haptics and animation | Launcher search | Same toggle animation and haptic as SystemUI's QS tiles. | Written, not yet tested: pill-to-24dp shape morph, colour animation, press bounce and SWITCH_ON/OFF haptics from SystemUI |
| 9 | Notification dots need the notification permission | Launcher | Grant Lawnchair notification listener access by default as a system app, without asking. | Done: Lawnchair grants itself notification access |
| 10 | Themed icons chosen in Wallpaper & style aren't kept by Lawnchair | Launcher | Make the picker setting and Lawnchair's setting one value, in both directions, surviving restarts. | Done: root cause was Launcher3 deleting the themed_icons key at start; tested on, off and across restarts |
| 11 | Option to force themed icons for apps without a monochrome icon | Launcher | Generate a Material You tinted icon for apps that don't ship one. Setting in Lawnchair. | Done: the existing "enforce themed icons" option now works, because themed icons are one setting |
| 12 | Caddy (beta app drawer) crashes | Launcher | Fix the crash, or remove the option if it can't be made stable. | Done: crash with a folder in the drawer fixed (missing page arrows) |
| 13 | Recents settings: "Show taskbar" does nothing | Launcher recents | Make the transient taskbar work on phones, as the setting promises. | Dropped (user decision, 2026-11-03): the phone taskbar made the launcher look broken. Graphite keeps the phone navigation bar; the switch that did nothing is removed from Lawnchair |
| 14 | Recents settings: translucent background and translucency don't apply | Launcher recents | Fix every option on the recents settings page so it changes the real recents screen. | Written, not yet tested: recents used a fixed theme colour, now the colour token that applies the translucency settings. Other options on the page read their settings |
| 15 | App open/close animation jumps into a circle at the end | Launcher animations | Smooth the end of the window-to-icon transition. | Done: the floating icon used AOSP's squircle instead of Lawnchair's icon shape, so the window ended as a rounded square and then jumped to the round icon. Feel to be checked on the phone |
| 16 | Smoother, iOS/HyperOS/One UI like animations without being slow | Launcher animations | Spring-based tuning, plus an animation speed and style slider in Lawnchair settings. | Done: Lawnchair settings, Recents screen, App animations: speed 50-200% (open/close durations and swipe home springs) and style Standard, Smooth (soft curve, no overshoot) or Bouncy. Feel to be checked on the phone |
| 17 | Double tap to sleep without the accessibility service | Launcher | Lock the screen through a system API as a system app. Existing Lawnchair setting stays. | Done: system method via DEVICE_POWER, default when "Auto" |
| 18 | Double tap to sleep and double tap to wake on the lock screen | SystemUI, framework | Lock screen gesture for sleep. Wake depends on the Pixel 8 touchscreen supporting tap-to-wake. Switches in Graphite lock screen settings. | Written (patch 0530): AOSP lock screen double tap to sleep enabled; double tap to wake on the single tap sensor; switches in Graphite settings, Lock screen. Needs the phone: emulator taps are rejected as synthetic |
| 19 | Offline song recognition (like Now Playing / Ambient Music Mod) | System service | Background system service with an offline database, off by default, a switch in settings and in setup, no launcher icon, not listening at all when off. Hiding the microphone indicator is a privacy exception and needs its own clearly described patch. Database source still to be decided. | Done on the emulator: Ambient Music Mod's logic as the headless core (org.graphite.nowplaying), Google's engine (Android 17 hooks), downloader with network only during updates, Now Playing page in Graphite settings (switch, recognise now, history, show the song, notifications, music database with countries/updates/song list, settings, pause at night, backup and restore), lock screen line (0570), At a Glance card, setup step (0580), no mic indicator (hotword op), not under active apps (0460). Real song recognition to be checked on the phone |
| 20 | Status bar AM/PM and network speed options don't work or apply | SystemUI, Graphite settings | Check both on the phone and in the emulator. | Done: network speed hid itself below 1 KB/s, now always shown while on (0 KB/s idle); AM/PM only exists in 12-hour time, so its switch is greyed out with an explanation in 24-hour time. Both apply immediately |
| 21 | Lawnchair drawer kept the old Material You colours after a new wallpaper | Launcher | Follow system palette changes | Done: theme cache follows the system accent colour; tested live on the emulator |
| 22 | Lock screen clocks (Weather clock) kept the old palette with the screen on, AOD was right | SystemUI | Plugin contexts follow overlay changes | Done (patch 0560): tested on the emulator |
| 23 | At a Glance sat inside the large Weather clock (between time and date), clock shifted up | SystemUI | At a Glance at the top, large clock below, all clocks | Done (patch 0590), to check on the phone |
| 24 | Lawnchair search quick toggles: colours by on/off like SystemUI | Launcher | Already in the newer Lawnchair (#8) | Checked on the emulator: off is a light pill, on the primary colour |
| 25 | Song recognition didn't work on the phone, manual recognition failed after a few seconds | Now Playing, build | Logs from the phone | Fixed: every Graphite build had the same fingerprint (envsetup.sh reused the first build's date), so the OTA wasn't treated as an upgrade and the default permission grants never ran: the core had no RECORD_AUDIO, the engine no READ_PHONE_STATE ("assuming call in progress"). Releases now get their own build number; turning Now Playing on also grants its permissions |
| 26 | No Bluetooth battery card; show left, right and case for earbuds | Launcher | | Fixed: same missing default grant (BLUETOOTH_CONNECT). Card shows L/R/case when the earbuds report them (Bluetooth metadata), otherwise one level. Sony earbuds over classic Bluetooth only report one level |
| 27 | App drawer still blue-tinted on the phone | Launcher | | Fixed: with blur the drawer used a fixed light blue (#66D9E2FF); now SystemUI's shade panel colours. The emulator has no blur, so it never showed |
| 28 | Search bar too strong; use the themed icon background colour | Launcher | | Done: new "Themed icon colours" style, used by Automatic while themed icons are on |
| 29 | Search quick toggles inconsistent (torch without colour or haptics) | Launcher | | Done: torch, Wi-Fi and Bluetooth toggle directly with on/off colours, hotspot and cast show state, every tile has SystemUI's haptics and re-reads its real state |
| 30 | KernelSU-Next: "Failed to grant root" | Kernel, build | | Fixed: the manager's libksud.so was installed as 0644, so it couldn't run ksud. Patch 0003 + config.fs make it 0755 |
| 31 | Weather clock: At a Glance between time and weather | SystemUI | | Checked on the phone: Google's Weather clock places At a Glance there itself. Kept its layout, but At a Glance no longer repeats the date and alarm the clock shows (0590). Other clocks: At a Glance above the large clock |
| 32 | Update to GrapheneOS 2026110200 | Build | | Done: all patches unchanged; KernelSU kernel reinstalled (same kernel source as GrapheneOS' rebuild) |
| 33 | Song recognition still didn't work after the permissions fix | Now Playing | Logs from the phone | Done: the update window fix got the database onto the phone (3188, about 17k songs). The remaining silence was the phone's system-wide Microphone access toggle being off, not a bug |
| 34 | Hide the "Ambient Music Mod running" notification | Now Playing, SystemUI | | Done: confirmed on the phone |
| 35 | At a Glance gone next to the Weather clock; a switch for it | SystemUI, Graphite settings | | Done: confirmed on the phone |
| 36 | Second factor PIN keys in old colours | SystemUI | Number keys in the lock screen button colour; delete and enter keep theirs | Done: confirmed on the phone |
| 37 | Editing a screenshot crashes sometimes | Gallery | | Done: confirmed on the phone |
| 38 | Lawnchair: the Wi-Fi tile was called Internet | Launcher | | Done: confirmed on the phone |
| 39 | 3D parallax wallpaper with object selection | New app | | Dropped (user decision, 2026-11-04): not their thing. Archived with its ROM integration in the private repo graphite_depth_wallpaper |
| 40 | Experimental AMOLED mode for the 3D wallpaper | New app | Menu, off by default, warning | Dropped with the wallpaper, in the same archive |

## Plan to the release (user, 2026-11-03)

Finish everything open (Now Playing: track list, backup and restore, lock screen song line, At a Glance card, Quick
Settings tile, setup; any bug fixes), then build the husky release, flash it over ADB sideload
(`adb reboot sideload-auto-reboot` + `adb sideload`), check the phone boots normally (not fastboot/recovery, no
failure), and only then shut down the PC.

Release 2026-11-04: built `2026110100` (user, release keys, all 19 patches) and sideloaded the signed OTA at 02:20
(transfer complete, exit 0). After the reboot the phone left USB entirely, which is expected: user builds default to
GrapheneOS' "USB-C port: charging-only when locked", so data stays off until the first unlock. Fastboot or recovery would
still have shown up, and neither did. To check after unlocking: `adb shell pm list packages org.graphite.nowplaying` must list the package
(new in this build; the build number and date are pinned to the tag, so they look the same as before), then the
large-clock layout (0590), real song recognition, the Bluetooth card and items 5, 8, 14 and 18.

Release 2026-11-04 (second): `2026110400` on GrapheneOS 2026110200 with items 25-32, ready to install, not flashed yet.
`src/releases/2026110400/release-husky-2026110400/husky-ota_update-2026110400.zip` (`adb reboot sideload-auto-reboot`, then
`adb sideload` it). Checked in the release: new fingerprint and timestamp, libksud.so 0755, KernelSU kernel. After installing,
check Now Playing (Graphite settings, recognise now), the headphones card, the drawer colour and KernelSU root.

## Now Playing recognition, 2026-11-04 (in the sources, needs the next build)

The phone only had the built-in core (15,943 songs, one Carti track). Measured on the emulator: Germany alone gives 81,561
songs, Germany + US + UK 151,394, with France 188,001. Each country is about 230 MB. Google's 3188 is the newest database.

Fixed and tested on the emulator: update window closing before the songs downloaded, added countries ignored until the engine
restarted, engine crash from too many scheduled jobs, core killed by the network grant, out of memory with several countries.
Added and tested there: US as a default extra country, up to four extras, country picker at setup, Live Update progress.

Still to check on the phone after flashing, because the emulator has no real microphone:

* Byte order fix and automatic gain: compare recognition of loud and quiet songs. `ProxyAudioRecord` logs the gain per capture.
* Microphone hint: the emulator image predates patch 0550, so the hint itself hasn't been seen yet.
* Matching time with several countries (`fingerprint_matcher.cc: Match results (in N ms)`).
* The little core setting pins to CPUs 0-3 (mask 0xF in libsense), the little cluster on Tensor G3. It stays off and was never
  measured on the phone.

Known cost: the core keeps the song list in memory after a database search (about 180 MB with four countries).

## Phone report, 2026-11-05

Fixed and tested on the emulator, not yet on the phone (needs a release build):

| Item | Cause | Still to check on the phone |
|---|---|---|
| Song download stuck at 0% | Expediting ran all three job variants; the delayed and periodic ones reschedule and cancel the one that downloads. Scheduled updates could never download: Android never runs a job needing a network for an app without INTERNET | Add a country unplugged. The 13 minute stall on 2026-11-05 07:04 isn't fully explained: its logs are gone |
| Notification stayed on Preparing after the install | The finished check counted all songs (43 s on the phone); one text for both stages | Time after the install |
| Double tap to sleep never worked | Touch view refused ACTION_DOWN with long press off; AOSP timed both taps against 300 ms | Real finger speed |
| Double tap to wake: single tap woke, later nothing did | PulsingGestureListener ignored the setting; the tap sensor reports one event for two quick taps and doesn't re-arm | **Sensor path untested**: the emulator has no tap sensor. First tap should light the screen, the second wake it |
| At a Glance on the AOD only | New switch (patch 0640) | Layout on the real AOD |

