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

## Smaller ones

- Writing an empty Python string to `UDC` writes nothing. Write `"\n"` to unbind.
- `pkill -f "pattern"` over SSH matches the shell that runs it. Use `pkill -f "[p]attern"`.
- Root is not allowed to inject mock locations until `cmd appops set root android:mock_location allow`.
- The host's logcat (`lxc-attach -n android -- logcat`) may use a different time zone than the container's.
- OpenAuto hangs after a session ends. Restart it.
- Do not set `NoDisplay=true` in `~/.local/share/applications/Waydroid.desktop`. Lomiri then rejects the file and cannot show any Android window.

## Open problems

- **Android windows on the phone.** With the Waydroid session started by the relay and running permanently, the Waydroid icon in the app drawer opens and closes at once, and `waydroid show-full-ui` from a shell, which worked at first, later showed nothing. Not understood yet. It matters because Android Auto's first-connection dialog appears on the phone.
- **Bluetooth** in Waydroid, for calls and for wireless Android Auto.
- **Battery:** suspend Waydroid when no car is connected.
- **Speed and bearing** in the injected location.
- **A real car** has not been tried.
