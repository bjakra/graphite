#!/usr/bin/env bash
# Install a Lawnchair APK as a *privileged, platform-signed system app* and make it the
# system Recents (Quickstep) provider — the same integration the Graphite ROM will ship.
#
# Works on any emulator image signed with AOSP test keys (stock SDK "default"/google_apis
# images, and our own GrapheneOS emulator build). Needs adb root + writable system.
#
#   tools/testing/lawnchair-on-emulator.sh path/to/Lawnchair.apk [package]
#
# package defaults to the APK's package (e.g. app.lawnchair.debug).
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
SDK="$ROOT/sdk"
BT="$SDK/build-tools/37.0.0"
PLATFORM_JAR=$(ls -d "$SDK"/platforms/android-37*/android.jar | tail -n1)
ADB="${ADB:-$SDK/platform-tools/adb} -e"
KEYS="$ROOT/src/build/make/target/product/security"
JAVA_HOME="${JAVA_HOME:-$ROOT/src/prebuilts/jdk/jdk21/linux-x86}"; export JAVA_HOME PATH="$JAVA_HOME/bin:$PATH"
WORK="$ROOT/state/emu-test"; mkdir -p "$WORK"

apk=${1:?usage: $0 Lawnchair.apk [package]}
pkg=${2:-$("$BT/aapt2" dump packagename "$apk")}
echo "==> $apk ($pkg)"

# 1. re-sign with the AOSP *platform* test key → signature permissions get granted
cp "$apk" "$WORK/Lawnchair-unsigned.apk"
"$BT/zipalign" -f -p 4 "$WORK/Lawnchair-unsigned.apk" "$WORK/Lawnchair.apk"
"$BT/apksigner" sign --key "$KEYS/platform.pk8" --cert "$KEYS/platform.x509.pem" "$WORK/Lawnchair.apk"

# 2. privapp allowlist: every android.* permission the APK requests
{
    echo '<?xml version="1.0" encoding="utf-8"?>'
    echo '<permissions>'
    echo "  <privapp-permissions package=\"$pkg\">"
    "$BT/aapt2" dump permissions "$WORK/Lawnchair.apk" | sed -n "s/^uses-permission: name='\(android\.permission\.[^']*\)'.*/    <permission name=\"\1\"\/>/p" | sort -u
    echo '  </privapp-permissions>'
    echo '</permissions>'
} > "$WORK/privapp-permissions-lawnchair.xml"

# 3. static framework overlay: config_recentsComponentName → Lawnchair's RecentsActivity
ov="$WORK/overlay"; rm -rf "$ov"; mkdir -p "$ov/res/values"
cat > "$ov/AndroidManifest.xml" <<EOF
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="org.graphite.overlay.recents">
    <overlay android:targetPackage="android" android:isStatic="true" android:priority="999"/>
    <application android:hasCode="false"/>
</manifest>
EOF
cat > "$ov/res/values/config.xml" <<EOF
<resources>
    <string name="config_recentsComponentName" translatable="false">$pkg/com.android.quickstep.RecentsActivity</string>
</resources>
EOF
"$BT/aapt2" compile --dir "$ov/res" -o "$ov/res.zip"
"$BT/aapt2" link -I "$PLATFORM_JAR" --manifest "$ov/AndroidManifest.xml" -o "$ov/unsigned.apk" "$ov/res.zip"
"$BT/apksigner" sign --key "$KEYS/platform.pk8" --cert "$KEYS/platform.x509.pem" --out "$WORK/GraphiteRecentsOverlay.apk" "$ov/unsigned.apk"

# 4. push into the (remounted) system image and reboot
$ADB root >/dev/null; sleep 2; $ADB wait-for-device
# The first remount disables verity and only takes effect after a reboot
if $ADB remount 2>&1 | grep -q "reboot"; then
    $ADB reboot; sleep 5; $ADB wait-for-device
    until [[ $($ADB shell getprop sys.boot_completed 2>/dev/null | tr -d '\r') == 1 ]]; do sleep 3; done
    $ADB root >/dev/null; sleep 2; $ADB wait-for-device
    $ADB remount >/dev/null
fi
$ADB shell pm uninstall "$pkg" >/dev/null 2>&1 || true      # drop a user-installed copy
$ADB shell mkdir -p /system_ext/priv-app/GraphiteLawnchair /system_ext/etc/permissions /product/overlay
$ADB push "$WORK/Lawnchair.apk" /system_ext/priv-app/GraphiteLawnchair/GraphiteLawnchair.apk
$ADB push "$WORK/privapp-permissions-lawnchair.xml" /system_ext/etc/permissions/
$ADB push "$WORK/GraphiteRecentsOverlay.apk" /product/overlay/
$ADB reboot; sleep 5; $ADB wait-for-device
until [[ $($ADB shell getprop sys.boot_completed 2>/dev/null | tr -d '\r') == 1 ]]; do sleep 3; done
$ADB shell cmd package set-home-activity "$pkg/com.android.launcher3.uioverrides.QuickstepLauncher" >/dev/null 2>&1 || true
echo "==> recents provider:"; $ADB shell dumpsys activity recents | grep -m1 mRecentsComponent
echo "==> home:"; $ADB shell cmd package resolve-activity --brief -c android.intent.category.HOME -a android.intent.action.MAIN | tail -n1
