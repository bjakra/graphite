# Installing Graphite on the Pixel 8 Pro (husky)

**Flashing wipes the phone, and locking wipes it again.** Back up everything first.

Current release: `src/releases/2026110100/release-husky-2026110100/` (GrapheneOS 2026103100 +
Graphite patches, `user` build, signed with `keys/husky/`).

Keep `keys/husky/` private and backed up. Without those keys you can't sign updates for a locked
phone, so you would have to unlock (which wipes it) to install anything else.

## 1. Prepare the phone

1. Settings → About phone → tap *Build number* seven times.
2. Settings → System → Developer options → enable **OEM unlocking**.
3. Reboot into the bootloader: power off, then hold Power + Volume Down.
4. Connect USB. Use a port on the machine, not a hub.

## 2. Unlock and flash

The script needs fastboot 35.0.1 or newer; `sdk/platform-tools` has 37.0.1.

```bash
cd /SSD-1TB/android/graphite
export PATH="$PWD/sdk/platform-tools:$PATH"
fastboot devices                       # must list the phone
fastboot flashing unlock               # confirm on the phone; this wipes it

mkdir -p ~/graphite-flash && cd ~/graphite-flash
unzip /SSD-1TB/android/graphite/src/releases/2026110100/release-husky-2026110100/husky-install-2026110100.zip
cd husky-install-2026110100/
bash flash-all.sh                      # bootloader, radio, your AVB key, then the OS; it reboots several times
```

`flash-all.sh` already flashes your key (`avb_custom_key`) and doesn't lock the bootloader.

## 3. Check that it boots, while still unlocked

Reboot and go through setup. Check that Lawnchair is home, Recents works, and
Settings → System → Graphite opens.

**Don't lock a build that doesn't boot.** A locked phone can't be reflashed until you unlock it
again from a working OS, so a bad locked build is much harder to recover. Unlocked, you can just
reflash.

Graphite has only run on the emulator so far. This is its first run on real hardware, so expect
this step to find problems. The modem, camera, fingerprint reader, NFC and real charging data
couldn't be tested on the emulator.

## 4. Lock

Back in the bootloader (power off, then hold Power + Volume Down):

```bash
fastboot flashing lock                 # confirm on the phone; this wipes it again
```

Each boot now shows a yellow "different operating system" warning. That is expected for a custom
key. It also shows a key ID. The SHA-256 of your key is:

```
76030e9e1f970470e372d15a4d8518e8cdd1b7370b997a39c771a984a4873c13
```

The ID should match the start of it. This comparison hasn't been tried on the phone yet, so if the
ID differs, stop and investigate before trusting the phone with anything.

Then turn **OEM unlocking** off again in Developer options.

## 5. Updating a locked phone (keeps your data)

With USB debugging on, this works without touching the phone. `sideload-auto-reboot` goes straight to sideload mode and
reboots when the install is done:

```bash
adb reboot sideload-auto-reboot
adb sideload src/releases/2026110100/release-husky-2026110100/husky-ota_update-2026110100.zip
```

Without USB debugging, use the manual steps below.

Don't use `flash-all.sh` for this: it needs an unlocked bootloader, and unlocking wipes the phone. Sideload
the OTA from recovery instead. It's signed with your keys, so the locked bootloader accepts it.

1. Power off, then hold Power + Volume Down to reach the bootloader. Use the volume keys to select
   **Recovery Mode** and press Power.
2. At the "No command" screen, hold Power and tap Volume Up once.
3. Select **Apply update from ADB**, then run:

```bash
cd /SSD-1TB/android/graphite
export PATH="$PWD/sdk/platform-tools:$PATH"
adb sideload src/releases/2026110100/release-husky-2026110100/husky-ota_update-2026110100.zip
```

4. Select **Reboot system now**.

The OTA installs to the other slot and switches to it, so the active slot changes. That is normal.

The release folder is overwritten by each rebuild while the build number stays the same. The release first
flashed to the phone is kept in `state/flashed-release-2026110100/`.

The updater isn't pointed at any server yet, and never at GrapheneOS's: their builds are signed with
different keys.
