# Backlog

The user's feature and bug list from 2026-11-03, in the order it will be worked on. Update the Status column as items
land. Rule for every item: anything with a setting gets it in the UI (Graphite settings, Lawnchair settings or setup), and
every existing toggle has to actually do what it says.

| # | Item | Area | Plan | Status |
|---|---|---|---|---|
| 1 | KernelSU-Next manager says "Not installed" | Kernel | The kernel finds its manager by scanning `/data/app` only, and Graphite ships the manager in `/system_ext/app`. Make the kernel also accept the preinstalled manager. | Fixed in the kernel (preinstalled manager accepted after the same signature check), in the next release |
| 2 | Remove Classic Power Menu | Power menu | Drop the app, patch 0510 and Parts' switch. The system power menu becomes the only one again. | Done: app, patch 0510 and Parts switch removed |
| 3 | Reboot options in the system power menu | Power menu | Restart, recovery, bootloader and SystemUI restart are already selectable (patch 0410). Group them under Restart as a submenu like other ROMs, add haptics, keep the editor in Graphite settings. | Done (patch 0520): Restart opens a compact submenu, haptics on every tap, switch in Graphite power menu settings |
| 4 | Remove Smartspacer, port its useful parts into Lawnchair's At a Glance | Launcher | Lawnchair's own smartspace (date, weather, calendar, alarm, battery, media) styled like the Pixel's, with weather from Graphite Weather. Delete the app, prebuilt, fork branch use and docs. | Partly done: Smartspacer removed; Lawnchair At a Glance shows Graphite Weather beside the date, next event and next alarm, at Pixel sizes. Further Smartspacer features open |
| 5 | Search opens slowly, results jump while typing | Launcher search | Open the search UI without the delay. Keep a stable result order while typing: no "Search on Play Store" row that appears and is pushed down when other results arrive. | Partly done: no more drawer flash, open transition 450 ms, results wait for all sections (250 ms), ranking refreshed in the background. Needs a check on the phone |
| 6 | Search settings toggles don't do anything (for example Android settings) | Launcher search | Check every toggle on the search settings page and wire each one up. | Open |
| 7 | Material You search bar on home and in the app drawer | Launcher search | Google-style bar with more theming (colours from the wallpaper, shape, icons), same look in both places. | Open |
| 8 | Quick settings search results lack haptics and animation | Launcher search | Same toggle animation and haptic as SystemUI's QS tiles. | Open |
| 9 | Notification dots need the notification permission | Launcher | Grant Lawnchair notification listener access by default as a system app, without asking. | Done: Lawnchair grants itself notification access |
| 10 | Themed icons chosen in Wallpaper & style aren't kept by Lawnchair | Launcher | Make the picker setting and Lawnchair's setting one value, in both directions, surviving restarts. | Done: root cause was Launcher3 deleting the themed_icons key at start; tested on, off and across restarts |
| 11 | Option to force themed icons for apps without a monochrome icon | Launcher | Generate a Material You tinted icon for apps that don't ship one. Setting in Lawnchair. | Done: the existing "enforce themed icons" option now works, because themed icons are one setting |
| 12 | Caddy (beta app drawer) crashes | Launcher | Fix the crash, or remove the option if it can't be made stable. | Done: crash with a folder in the drawer fixed (missing page arrows) |
| 13 | Recents settings: "Show taskbar" does nothing | Launcher recents | Make the transient taskbar work on phones, as the setting promises. | Open |
| 14 | Recents settings: translucent background and translucency don't apply | Launcher recents | Fix every option on the recents settings page so it changes the real recents screen. | Open |
| 15 | App open/close animation jumps into a circle at the end | Launcher animations | Smooth the end of the window-to-icon transition. | Open |
| 16 | Smoother, iOS/HyperOS/One UI like animations without being slow | Launcher animations | Spring-based tuning, plus an animation speed and style slider in Lawnchair settings. | Open |
| 17 | Double tap to sleep without the accessibility service | Launcher | Lock the screen through a system API as a system app. Existing Lawnchair setting stays. | Done: system method via DEVICE_POWER, default when "Auto" |
| 18 | Double tap to sleep and double tap to wake on the lock screen | SystemUI, framework | Lock screen gesture for sleep. Wake depends on the Pixel 8 touchscreen supporting tap-to-wake. Switches in Graphite lock screen settings. | Open |
| 19 | Offline song recognition (like Now Playing / Ambient Music Mod) | System service | Background system service with an offline database, off by default, a switch in settings and in setup, no launcher icon, not listening at all when off. Hiding the microphone indicator is a privacy exception and needs its own clearly described patch. Database source still to be decided. | Open |
