# How it works

## The idea

Android Auto apps (Waze, Spotify, …) don't draw to the car directly. Google's Android Auto app renders them and speaks the Android Auto protocol to the head unit. Re-implementing that side is not realistic, so Waydrive runs the real app, in Waydroid, and only bridges the transport.

Two facts make the bridge small:

1. A car talks to a phone over USB using **AOAP** (Android Open Accessory Protocol): three vendor control requests, after which the phone re-enumerates as `18d1:2d00` with one bulk IN and one bulk OUT endpoint. The Android kernel implements this in `f_accessory`, which Halium kernels can enable (`CONFIG_USB_CONFIGFS_F_ACC`). Userspace gets a plain byte stream, `/dev/usb_accessory`.
2. Android Auto has a developer feature, the **head unit server**, that listens on TCP 5277 and speaks the same protocol a car speaks over USB (it exists for Google's Desktop Head Unit). The bytes are identical on both transports.

So the relay copies bytes between `/dev/usb_accessory` and `<waydroid-ip>:5277`. It never parses the protocol.

## A session, step by step

1. **Idle.** `aa-bridge.py` has created the function `accessory.gs2` inside the phone's normal gadget `g1`, but not linked it into the configuration. That is enough for the kernel to answer AOAP control requests on whatever configuration is active. Android Auto in Waydroid has been force-stopped and its head unit server started fresh ("armed"). Android's `gps` test provider is registered.
2. **Car plugs in** and sends `GET_PROTOCOL`, six `SEND_STRING`s and `START`. The kernel emits the uevent `ACCESSORY=START`.
3. **Switch.** The relay asks `usb-moded` for its current mode, freezes it (`SIGSTOP`), unbinds `g1`, replaces its function links with the accessory function, sets `18d1:2d00` and binds again. This takes a few milliseconds.
4. **Relay.** It opens `/dev/usb_accessory`, connects to port 5277 and pumps bytes both ways. It starts `aa-gps-bridge.py`.
   It also follows Android's log: when Android Auto announces its phone-side dialog (`PREFLIGHT_UI_STARTING`), the relay opens Android's screen as a window on the phone.
5. **End.** The session ends when the UDC reports "not attached", when Android Auto closes the socket, or when nothing has arrived from the car for 20 s. The relay unbinds, removes the accessory link, thaws `usb-moded` and asks it over D-Bus to re-apply the previous mode (`charging_only`, then the old mode). It saves Android's logcat and arms a fresh server.

A keeper thread starts the Waydroid session after a reboot and re-arms if Android Auto has died.

## First connection to a car

Android Auto keeps a list of allowed cars, keyed by the vehicle id the head unit reports. For an unknown car it logs `Triggering FRX: car connection is not allowed`, goes to the state `PREFLIGHT`, projects "When safe, check your phone to start Android Auto" to the car and starts `PreflightPhoneWelcomeActivity` on the phone: terms plus "allow this car". Nothing else happens until that is confirmed.

On Ubuntu Touch, Android normally has no window, so nobody sees that dialog. The relay opens one (`show_android_ui`): it sets `waydroid.active_apps` to `Waydroid`, which makes Waydroid's compositor create its full-screen window, and Lomiri shows it as an app. The user unlocks the phone and confirms. After `Added car to Allowed Cars list` the session continues, and later connections of that car skip the step.

The same function serves manual requests: `show-android.sh` creates `/run/user/<uid>/aa-show-android`, the relay sees the file within a second. This needs no root on the user's side, and it avoids the cases where `waydroid show-full-ui` does nothing (see [pitfalls.md](pitfalls.md)).

## Why each odd detail exists

| Detail | Reason |
|---|---|
| Accessory function lives in `g1`, not in a second gadget | Android inside Waydroid watches `/sys/class/android_usb/android0`, which belongs to the first gadget. Android Auto ends a wired session about 3 s after that reports "disconnected". Also see the kernel panic in [pitfalls.md](pitfalls.md). |
| `usb-moded` is frozen, not stopped | It would otherwise reconfigure `g1` mid-session. Stopping it is slower and it may clean up the gadget on exit. |
| USB is restored by `usb-moded`, not by the relay | `umtprd` exits when its FunctionFS function is unbound; binding a configuration with a dead FunctionFS function fails with `EBUSY`. `usb-moded` restarts its helpers before binding. |
| A fresh Android Auto process per session | The head unit server accepts one client per process. A second connection, even a port probe, later crashes it with "Already connected". |
| `debug.stagefright.c2inputsurface=-1` | The video encoder's input surface must be created inside the 64-bit Android Auto process. The default (a 32-bit OMX service) cannot allocate graphics buffers on this host; the host's Codec2 service can create one but cannot be connected to from the container. |
| MediaTek encoders disabled in the container | `c2.mtk.avc.encoder` accepts frames from Waydroid and never returns them. The software encoder works. |
| The Android window is closed (`waydroid.active_apps=none`) before it is opened | If Waydroid still counts a window as open, a new request creates nothing. Closing through the property does not remove Android tasks, unlike closing the window in the shell. |
| Android's log of each session is saved under a dated name | The first car test was hard to analyse because the next session overwrote the log. |
| GPS provider registered before a session | Waze shows "Location disabled" if Android has no enabled `gps` provider when Android Auto starts it. |
| GPS client runs only during a session | So the GNSS receiver is off otherwise. |
| The GPS client stops on a stop-file | Killing location clients abruptly hung `lomiri-location-service` once. |

## The GPS bridge

Waydroid images have no GNSS HAL. `aa-gps-bridge.py` (root) starts `gps/pos.qml` as the phone user under `qmlscene -platform offscreen`. That QML uses Qt Positioning's `lomiri` source, which talks to Ubuntu Touch's location service, and prints one JSON line per update. The bridge keeps one root shell open in the container (`lxc-attach … sh`) and writes

```
cmd location providers set-test-provider-location gps --location LAT,LON --accuracy M
```

once per second. Root needs the app-op first: `cmd appops set root android:mock_location allow`. The shell command has no arguments for speed or bearing.

## Waydroid on a Halium 14 host

There is no HALIUM_14 Waydroid vendor image, so the Android 13 container runs with the HALIUM_13 vendor image on an Android 14 vendor partition:

- `waydroid init` is pointed at a local vendor channel that serves the HALIUM_13 list under the name `HALIUM_14.json`.
- The host's Mali driver needs Android 14 and MediaTek libraries that the container lacks; `waydroid-mali-libs.sh` copies ten of them into Waydroid's vendor overlay. Without them the compositor crashes in a loop.
- `waydroid-container.service` runs `waydroid upgrade -o` on every start, which rewrites the LXC config. A systemd drop-in runs `waydroid-lxc-extra.sh` afterwards to re-add the bind mount of the patched codec list.

[upstream-issue.md](upstream-issue.md) has the details in the form of a bug report.
