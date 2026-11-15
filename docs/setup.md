# Setup

These are the steps that were done on the Volla Phone Plinius, in order. Steps marked **(device-specific)** may be different or unnecessary on other phones; see [porting.md](porting.md). Most of this was done once, by hand, over an evening; only the last part (`aa-install.sh`) has been run repeatedly.

Everything on the phone is done over SSH as `phablet`. `sudo` asks for the phone's passcode.

## 0. Prerequisites

- Ubuntu Touch with Waydroid installed (`which waydroid`).
- Kernel with the accessory function:
  ```sh
  zcat /proc/config.gz | grep -E "CONFIGFS_F_ACC|CONFIGFS_UEVENT"   # both =y
  ```
- A Google account for the Play Store inside Waydroid.
- For desk testing: a Linux PC with Docker and a USB data cable.

Optional sanity check of the kernel side before anything else: `phone/debug/aoap-test.sh run` on the phone and `host/aoap_host.py` on the PC (needs `pyusb`). The PC plays the car, the phone switches to accessory mode and echoes a message. The phone's normal USB functions are off for about a minute.

## 1. Waydroid with Google apps

```sh
sudo waydroid init -s GAPPS
```

**(device-specific)** On a Halium 14 phone this fails, because `https://ota.waydro.id/vendor/waydroid_arm64/HALIUM_14.json` does not exist. Workaround: serve the HALIUM_13 list from a local channel under the expected name.

```sh
mkdir -p ~/android-auto/vendor-channel/waydroid_arm64
curl -s https://ota.waydro.id/vendor/waydroid_arm64/HALIUM_13.json \
     -o ~/android-auto/vendor-channel/waydroid_arm64/HALIUM_14.json
sudo waydroid init -s GAPPS -v file:///home/phablet/android-auto/vendor-channel
```

The download is about 1.3 GB. Later `waydroid upgrade` runs use this local list, so vendor updates do not arrive by themselves.

## 2. Make Android boot **(device-specific)**

Start a session (`waydroid session start`, or tap the Waydroid icon) and check `waydroid prop get sys.boot_completed`. If Android never finishes booting and `dmesg` shows `hwcomposer`, `surfaceflinger` and `zygote` dying in a loop, the host GPU driver is missing libraries in the container:

```sh
sudo sh ~/android-auto/waydroid-mali-libs.sh
```

The list of libraries in that script is for the MT6878's Mali driver. To find yours, look in Android's logcat for `dlopen failed: library "…" not found` and follow the `NEEDED` entries of the host's `libGLES_*.so`.

## 3. Google certification

Play refuses uncertified devices. Read the Google Services Framework ID and register it at <https://www.google.com/android/uncertified>:

```sh
sudo sh -c 'cp /home/phablet/.local/share/waydroid/data/data/com.google.android.gsf/databases/gservices.db /tmp/ && chmod 644 /tmp/gservices.db'
python3 -c "import sqlite3; print(sqlite3.connect('/tmp/gservices.db').execute(\"select value from main where name='android_id'\").fetchone()[0])"
rm /tmp/gservices.db
```

Then sign in. If the Play Store shows an empty screen, add the Google account in Android's Settings instead and open the Play Store afterwards. Install Waze, Spotify or whatever you want on the car screen.

## 4. Android Auto

The Play Store reports Android Auto as "not compatible" in Waydroid. Install the split APKs from a source you trust and check the signature (Google's certificate, `CN=Android, OU=Android, O=Google Inc.`). Put `base.apk` and the splits for `arm64_v8a`, your screen density and your languages into one directory on the phone, then:

```sh
sudo sh ~/android-auto/waydroid-install-splits.sh <directory>
```

Open its settings (it has no launcher icon):

```sh
waydroid app intent com.google.android.projection.gearhead.SETTINGS ""
```

Tap **Version** ten times to enable developer settings. You do not need to start the head unit server by hand; the relay does that.

## 5. Install Waydrive

On the PC:

```sh
./deploy.sh phablet@<phone>
ssh -t phablet@<phone> sudo sh android-auto/aa-install.sh
```

`aa-install.sh`:

1. stops a running relay and Waydroid;
2. copies the scripts to `/userdata/android-auto` (root-owned);
3. sets `debug.stagefright.c2inputsurface=-1` in `/var/lib/waydroid/waydroid.cfg`;
4. installs a drop-in for `waydroid-container.service` that disables the MediaTek H.264/HEVC encoders inside the container after every start;
5. restarts Waydroid and prints the H.264 encoders Android now offers (should be only `c2.android.avc.encoder`);
6. installs, enables and starts `aa-bridge.service`.

The output should end with `enabled`, `active`, `Android Auto head unit server armed` and `waiting for a car`.

## 6. First connection

The first time a head unit connects, Android Auto shows a welcome and permission dialog **on the phone**. It opens inside Android but is not brought to the front; show it with:

```sh
waydroid show-full-ui
```

This worked on the first day but later stopped showing anything; see the open problems in [pitfalls.md](pitfalls.md).

Grant navigation apps their location permission, either in their own UI or with:

```sh
sudo sh ~/android-auto/aa-grant-location.sh com.waze
```

## 7. Desk test with OpenAuto

```sh
cd headunit
./build.sh             # once; about 3 GB image
./run-openauto.sh      # USB mode; contacts the attached phone on start
```

Android Auto should appear in the emulator window within about 15 seconds. Watch the relay with `journalctl -u aa-bridge -f` on the phone. The emulator hangs when a session ends; restart the container for the next one.

To test only the Android side, without USB: `phone/debug/aa-test.sh -1` on the phone (with `sudo`), forward the port with `phone/debug/tcp-forward.py`, and run the emulator with `--no-usb --host <phone-ip>`.

## Updating and removing

```sh
./deploy.sh phablet@<phone>
ssh -t phablet@<phone> sudo sh android-auto/aa-update.sh          # copy relay files, restart the service
ssh -t phablet@<phone> sudo sh android-auto/aa-install.sh --remove
```

Removing the service leaves Waydroid and its settings as they are. The drop-in is `/etc/systemd/system/waydroid-container.service.d/android-auto.conf`.

## Checking a running system

```sh
systemctl is-active aa-bridge
journalctl -u aa-bridge -n 30 --no-pager
waydroid status
```

Android's log of the last session is in `/userdata/android-auto/diag/aa-last-session.txt`.
