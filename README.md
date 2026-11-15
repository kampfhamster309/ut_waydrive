# Waydrive

Wired **Android Auto from an Ubuntu Touch phone**: plug the phone into a car (or a head-unit emulator) and get Google's Android Auto with Waze and Spotify on the car screen.

Google's real Android Auto app runs in Waydroid. A small relay on the Ubuntu Touch side answers the car's USB handshake and pipes the connection into the container.

```
car (USB host) ──AOAP──▶ kernel f_accessory ──▶ aa-bridge.py ──TCP 5277──▶ Android Auto in Waydroid
                                                     ▲
                Ubuntu Touch location service ──▶ aa-gps-bridge.py ──▶ Android "gps" test provider
```

## Status

| | |
|---|---|
| Device | Volla Phone Plinius (MediaTek MT6878, Halium 14), Ubuntu Touch 24.04, Waydroid 1.6.3 with the LineageOS 20 (Android 13) GAPPS image |
| Verified | Against the [OpenAuto](https://github.com/opencardev/openauto) head-unit emulator over USB: video, touch, Waze with the phone's real GPS, Spotify tile. Starts by itself after a reboot. |
| **Not verified** | A real car. Audio output. Behaviour while driving. Any other phone. |

This is a record of one working setup and of what it took to get there, published so others can adapt it. It is not a packaged product. Several steps are specific to this phone; [docs/porting.md](docs/porting.md) says which.

## What you get

- **`phone/aa-bridge.py`** — the relay, run as a systemd service. Switches the phone's USB gadget into accessory mode when a car asks, copies bytes between `/dev/usb_accessory` and Android Auto's head unit server, restores USB afterwards, starts Waydroid after a reboot and keeps a fresh Android Auto server ready.
- **`phone/aa-gps-bridge.py`** — feeds the phone's GPS into Android while a car is connected (Waydroid has no GNSS).
- **Waydroid fixes** for a Halium 14 host with an Android 13 container: GPU libraries, video encoder path, settings that survive a reboot.
- **`headunit/`** — OpenAuto in Docker, to play the car at your desk.
- **`docs/`** — how it works, setup, the pitfalls (one of them panics the kernel), porting notes.

## Limits

- **Wired only.** Wireless Android Auto needs Bluetooth inside Waydroid.
- **No calls or contacts** through Android Auto, for the same reason.
- **No CarPlay.** Only iPhones can be a CarPlay source.
- **GPS without speed or heading.** Only position and accuracy are injected.
- **Battery.** Waydroid runs all the time and is never suspended.
- **Developer mode.** It relies on Android Auto's "head unit server", a developer feature Google could remove.
- The relay runs as **root**, and Android Auto's developer server listens inside the container on TCP 5277 without authentication.

## Quick start

Read [docs/setup.md](docs/setup.md) first; the short version:

```sh
./deploy.sh phablet@<phone>                                   # copies phone/ to ~/android-auto
ssh -t phablet@<phone> sudo sh android-auto/aa-install.sh     # service + Waydroid settings
cd headunit && ./build.sh && ./run-openauto.sh                # optional: desk test
```

Before that you need Waydroid running with Google apps, Android Auto installed in it with developer mode on, and the kernel option `CONFIG_USB_CONFIGFS_F_ACC`.

## Layout

```
phone/            everything that goes onto the phone (~/android-auto)
  aa-bridge.py, aa-gps-bridge.py, gps/pos.qml, aa-bridge.service
  aa-install.sh, aa-update.sh, waydroid-aa-persist.sh, waydroid-lxc-extra.sh
  waydroid-mali-libs.sh, waydroid-install-splits.sh, aa-grant-location.sh
  debug/          test and diagnostic helpers
host/aoap_host.py plays the car's USB handshake from a PC (pyusb)
headunit/         OpenAuto head-unit emulator in Docker
docs/             how-it-works, setup, pitfalls, porting, upstream issue draft
```

## Read this before experimenting

On this kernel, **removing a USB gadget from configfs panics the phone** at the next plug or unplug. See [docs/pitfalls.md](docs/pitfalls.md).

## License

MIT. OpenAuto and aasdk are built from their own sources by `headunit/build.sh` and keep their own licenses (GPLv3).

Android Auto, Waze and Spotify are trademarks of their owners; this project is not affiliated with any of them.
