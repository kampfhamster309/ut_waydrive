# Pitfalls

Things that cost hours, in rough order of how badly they bite.

## Removing a configfs gadget panics the kernel

On the tested kernel (GKI android14-6.1 with Android's configfs additions), every gadget gets a state device `androidN`, all created with `dev_t` 0:0. `android_device_destroy()` then calls `device_destroy(class, MKDEV(0, 0))`, which destroys the **first** such device, `android0`, whichever gadget is being removed. The main gadget keeps a dangling pointer, and the next USB connect or disconnect crashes in `kobject_uevent_env`.

An early version of the relay kept the accessory function in a second gadget and later removed it. The phone rebooted at the next unplug.

**Rule: never create or remove a second gadget. Only change function links inside the existing one.** For the same reason the relay never restarts `usb-moded`, since it is not known whether its start-up recreates the gadget.

## A session that dies after three seconds

Android Auto treats the head-unit-server connection as a wired one and watches Android's USB state. Android reads that from `/sys/class/android_usb/android0`. If the accessory function is in another gadget, `android0` stays "disconnected" and Android Auto closes the session (`Closing 1 FDs due to USB disconnect` in logcat).

## The phone vanishes from USB after a session

Restoring the old function links and binding the gadget by hand fails with `EBUSY` once `umtprd` has exited, which it does when its FunctionFS function is unbound. Let `usb-moded` rebuild its own configuration. Manual repair, no root needed:

```sh
U="gdbus call --system --dest com.meego.usb_moded --object-path /com/meego/usb_moded --method com.meego.usb_moded"
$U.set_mode charging_only; sleep 3; $U.set_mode mtp_adb
```

## The head unit server takes one connection

Per Android Auto process. A port check counts. The next real connection then gets no answer, or the process crashes with `IllegalStateException: Already connected` when a stale connection wakes up. Force-stop Android Auto and start the service again before each session, and never probe the port.

Start it without the UI (root inside the container):

```sh
am force-stop com.google.android.projection.gearhead
am start-foreground-service -n com.google.android.projection.gearhead/.companion.DeveloperHeadUnitNetworkService
```

## Black screen although the session is up

In order of discovery:

1. **Waydroid froze the container** because no Android window was visible. `lxc-attach` then hangs too. `waydroid prop set persist.waydroid.suspend false`.
2. **Encoder input surface cannot be allocated** (`Gralloc2: buffer descriptor contains invalid usage bits`, `GraphicBufferAllocator: Failed to allocate`, GL error 1285 in `CAR.WM.GLCOMPOSER`). Fixed by `debug.stagefright.c2inputsurface=-1`.
3. **`Frame stuck or lost in encoder!`** with `c2.mtk.avc.encoder`. Fixed by disabling the MediaTek encoders in the container.
4. **The emulator has no video sink.** OpenAuto's log says "GStreamer encountered a general resource error". Install `gstreamer1.0-x` and `gstreamer1.0-gl` in the image.

Things that did **not** help and were removed again: software rendering (SwiftShader), passing the host's `ro.vendor.arm.gralloc.*` properties into the container, patching the usage-bit check out of `libui.so`, hiding the host's Codec2 service through its VINTF fragment, and `c2inputsurface=1`.

## Settings disappear after a reboot

`waydroid-container.service` runs `waydroid upgrade -o` on every start. That rewrites `/var/lib/waydroid/lxc/waydroid/config` and `waydroid_base.prop`. Extra `lxc.mount.entry` lines must be re-added afterwards (a systemd drop-in with a second `ExecStartPre`), and properties belong in the `[properties]` section of `waydroid.cfg`.

## Waze says "Location disabled"

It does this when Android has no enabled `gps` provider at the moment Android Auto starts it, and it does not re-check. Permissions and Google's location-accuracy setting were not the cause. Register the test provider before a session, not with the first fix.

## The location service hangs

After several location clients were killed with a signal, `lomiri-location-service` stopped answering; the quick-settings toggle and the Settings page then disagreed. `sudo systemctl restart lomiri-location-service` fixes it. The GPS client therefore exits on request (a stop file) after stopping its `PositionSource`.

## "When safe, check your phone to start Android Auto"

A car Android Auto has not seen needs a confirmation on the phone (see [how-it-works.md](how-it-works.md)). Without an Android window the session waits forever; the relay's byte counter for phone→car stops at about 110 KB. In logcat: `Triggering FRX: car connection is not allowed`, `PREFLIGHT_UI_STARTING`. The first real-car test ended exactly here. The emulator does not show this by default because its vehicle id is fixed; use `run-openauto.sh --car-id <new>`.

## Android's window on the phone

Observed with Lomiri/qtmir 0.7.2 and Waydroid 1.6.3:

- On a fresh Waydroid session `waydroid show-full-ui` opens the window, and it survives app switching and locking.
- After the window has been swiped away in the app switcher, tapping the stock Waydroid icon does nothing. Lomiri does not start the launcher at all. The reason is not known. Opening the window from outside still works.
- In sessions that had been running for hours, `waydroid show-full-ui` sometimes created no window. Unconfirmed guess: Waydroid still counted a window as open that the shell no longer showed. Setting `waydroid.active_apps` to `none`, letting Android draw a frame, and then setting it to `Waydroid` is what the relay does, and that has worked every time so far.
- qtmir gives a Waydroid window its app entry from the window's app id, which must match a launcher file in `~/.local/share/applications/`. `NoDisplay=true` in `Waydroid.desktop` makes that lookup fail and no Android window is shown.

## Android hangs after asking for a window of an app without a launcher

After `waydroid app launch com.google.android.projection.gearhead` (Android Auto has no launcher icon) and a manual session restart, Android's `system_server` hung and was killed by its watchdog every minute: `WATCHDOG KILLING SYSTEM PROCESS: Blocked in handler on ui thread`, stack in `BLASTBufferQueue.nativeCreate`. The relay then logs `head unit server did not start` forever. The cause is not proven. Waydroid's compositor loops on `wl_display_roundtrip` until a new window is configured, so a window the shell never accepts would block it, and with it SurfaceFlinger. Recovery, no root: `waydroid session stop`; the relay starts the session again.

## Silence is not a dead car

An early relay ended the session when nothing had arrived from the car for 20 s. With a paused track and a static screen neither side sends anything (the emulator, at least, sends no pings), so a healthy session was cut off 25 s after pausing the music. A real head unit happened to send data all the time, which hid the problem. The relay now only gives up when its own write to the car has been blocked for 20 s.

## Smaller ones

- Writing an empty Python string to `UDC` writes nothing. Write `"\n"` to unbind.
- `pkill -f "pattern"` over SSH matches the shell that runs it. Use `pkill -f "[p]attern"`.
- Root is not allowed to inject mock locations until `cmd appops set root android:mock_location allow`.
- The host's logcat (`lxc-attach -n android -- logcat`) may use a different time zone than the container's.
- OpenAuto hangs after a session ends. Restart it.
- Do not set `NoDisplay=true` in `~/.local/share/applications/Waydroid.desktop`. Lomiri then rejects the file and cannot show any Android window.

## Open problems

- **The stock Waydroid icon** stops working once the window has been swiped away. Worked around with a second launcher that goes through the relay.
- **A complete session in a real car.** The one attempt so far stopped at the confirmation step, before that step was fixed.
- **Bluetooth** in Waydroid, for calls and for wireless Android Auto.
- **Battery:** suspend Waydroid when no car is connected.
- **Speed and bearing** in the injected location.
