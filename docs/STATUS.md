# Status

Last update: 2026-11-03. The husky release with KernelSU-Next, Classic Power Menu and Smartspacer was sideloaded at about
02:00. The install was accepted, and the phone hadn't returned to fastboot 10 minutes later. Its boot wasn't observed, because
USB debugging is off after reboot.

Check on the phone:

1. It boots and unlocks with your data.
2. The KernelSU-Next manager opens and reports the kernel as working, and root can be granted to one app.
3. Holding power opens the menu smoothly, and wallet cards load at once from the second open.
4. At a Glance shows the date and weather. Smartspacer has no notification and isn't under Active apps.

Same build fingerprint means Android may not run its first-boot defaults on an existing install, so Smartspacer's
calendar permission and notification access may need granting by hand. They apply by default on a wipe.

If the new slot fails to boot, the phone falls back to the previous slot, the earlier build.
