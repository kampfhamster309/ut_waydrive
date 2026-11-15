# OpenAuto head unit emulator (desk test rig)

Android Auto *head unit* (car side) running on a Linux PC in Docker, so the phone
side can be tested at the desk. Built from the maintained opencardev forks:

| repo | branch | commit tested |
|------|--------|---------------|
| github.com/opencardev/aasdk    | `newdev` | 9bf6adf (2026-06-11) |
| github.com/opencardev/openauto | `main`   | 4cc739b (2026-02-08) |

`newdev` is the aasdk branch openauto's own `build.sh --with-aasdk` uses. Both
built cleanly on Debian trixie with no patches (openauto with `-DNOPI=ON`, i.e.
no Raspberry Pi / OMX bits; video goes through Qt Multimedia + GStreamer).

## Files

- `Dockerfile` - Debian trixie, builds aasdk then openauto, installs `autoapp`
  and `btservice` to `/usr/local/bin`, runs as user `hu` (uid 1000).
- `entrypoint.sh` - creates the Crankshaft flag files the UI looks at
  (shows the Wifi button, optional TCP target), then execs `autoapp`.
- `build.sh` - clones the two repos into `src/` if missing and builds image `openauto-hu`.
- `run-openauto.sh` - starts the container with display/USB/audio/network flags.
- `config/` - bind-mounted as the app's working directory (created on first run).
- `screenshot-mainwindow.png` - main screen as rendered on the PC.

## Build

```sh
cd headunit
./build.sh            # ~5 min first time (apt downloads dominate), image ~3.2 GB
```

## Run

```sh
./run-openauto.sh                   # USB + TCP; --privileged, /dev/bus/usb, /run/udev
./run-openauto.sh --no-usb          # TCP only, no USB access, not privileged
./run-openauto.sh --host 10.0.0.5   # pre-fill the TCP target (see below)
./run-openauto.sh --shell           # bash inside the container
```

Flags used: `--network host --ipc host`, `DISPLAY` + `/tmp/.X11-unix` + the
XWayland cookie (`$XAUTHORITY`) for the window (it runs as an X11 client under
XWayland), the PipeWire PulseAudio socket (`$XDG_RUNTIME_DIR/pulse/native`) for
audio, `/dev/dri` for the GPU.

The window opens fullscreen on the primary screen. Quit with the red power tile
-> exit, or `docker stop openauto-hu` from another terminal.

**USB mode:** on startup, and whenever a device is plugged in, autoapp sends the
AOAP "switch to accessory" request to every USB device it is allowed to open. With
the relay running on the phone, that starts a wired session by itself. Use
`--no-usb` when an attached phone should be left alone. The container runs as
uid 1000, so it can only open devices your user can write to (typically the phone,
and sometimes a Bluetooth adapter).

## Connecting over TCP (phone "head unit server", port 5277)

The port is hard-coded to 5277 (`src/autoapp/UI/ConnectDialog.cpp`); only the
IP is entered. On the phone, enable Android Auto developer mode and start the
"head unit server", then:

1. **Via the UI:** start the container, tap the orange **Wifi** tile on the
   main screen, type the phone's IP in the dialog, press **Connect**. Successful
   addresses are saved to `config/openauto_wifi_recent.ini` and shown in the
   dialog's list next time.
2. **Pre-filled:** `./run-openauto.sh --no-usb --host <phone-ip>`. The
   entrypoint writes the IP to `/tmp/gateway_wlan0` inside the container. When
   the Wifi tile is tapped, the dialog finds that single address and connects
   to `<phone-ip>:5277` immediately, with no typing.

The Wifi tile normally only appears on Crankshaft when a hotspot is up; the
image forces it with `/etc/button_wifi_visible` and `/tmp/mobile_hotspot_detected`.

autoapp also listens on **TCP 5000** for wireless projection clients
(`startServerSocket()`); with `--network host` that port is open on the PC.

## Config

autoapp reads/writes `openauto.ini` and `openauto_wifi_recent.ini` from its
current directory, which is `/home/hu/openauto` in the container =
`./config` on the host. On first start there is no `openauto.ini` and defaults
are used; it is written when settings are saved from the gear tile. Useful keys:
`General.HideWarning`, `Video.Resolution`, `Video.FPS`, `Video.ScreenDPI`,
`Audio.OutputBackendType`, `Input.EnableTouchscreen`,
`Bluetooth.WirelessProjectionEnabled`.

## Status / known issues

- Tested against Waydrive on a Volla Phone Plinius, over TCP (phone's head unit
  server) and over USB: video, touch input, Waze and Spotify tiles all work.
  Audio output was not checked.
- **autoapp hangs after a session ends** (cable unplugged, phone side closes). It
  keeps showing the last frame. Restart the container (`docker stop openauto-hu`,
  then `./run-openauto.sh`); on start it contacts an attached phone again.
- The GStreamer video sinks (`gstreamer1.0-x`, `gstreamer1.0-gl`) must be in the
  image. Without them the player fails with "GStreamer encountered a general
  resource error" and the projection stays black although frames arrive.
- Screenshot of the projection from the host: find the window with
  `xwininfo -root -tree | grep autoapp`, then `import -window <id> out.png`.
- A small "Warning" dialog is shown at startup unless `General.HideWarning=true`.
- Harmless startup noise: `Cannot find a running Bluez`, missing
  `/boot/crankshaft/crankshaft_env.sh`, `XDG_RUNTIME_DIR not set`. The Crankshaft
  helper tiles (camera, brightness, update) do nothing here.
- Fullscreen on the "primary" screen, which on a multi-monitor setup may be an
  external display. The mouse cursor is hidden over the window.
- autoapp listens on TCP 5000 while it runs (wireless projection); with
  `--network host` that port is open on the PC.
