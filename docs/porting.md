# Porting to another phone

What is generic, what is specific to the Volla Phone Plinius, and how to find your own values.

## Generic

- `aa-bridge.py`, as long as the phone uses a configfs gadget managed by `usb-moded` and the kernel has `f_accessory`. Check the constants at the top: gadget path (`/sys/kernel/config/usb_gadget/g1`), configuration name (`c.1`), user name (`phablet`).
- `aa-gps-bridge.py` and `gps/pos.qml`, on any Ubuntu Touch with Qt Positioning's `lomiri` plugin.
- `waydroid-install-splits.sh`, `aa-grant-location.sh`, the `debug/` helpers, `headunit/`.
- The Android Auto behaviour: one connection per process, the USB-state check, the head unit server service name.

## Check on your device

| Question | How to check |
|---|---|
| Does the kernel have the accessory function? | `zcat /proc/config.gz \| grep F_ACC`. If not, the kernel needs `CONFIG_USB_CONFIGFS_F_ACC=y` and `CONFIG_USB_CONFIGFS_UEVENT=y`. |
| Does AOAP work at all? | `phone/debug/aoap-test.sh run` plus `host/aoap_host.py`. |
| Which gadget and which state device? | `ls /sys/kernel/config/usb_gadget/` and `ls /sys/class/android_usb/`. There should be exactly one of each. |
| Who manages the gadget? | `systemctl status usb-moded`. If something else does, the freeze and restore logic in `switch_to_accessory()` / `switch_to_normal()` needs adapting. |
| Does `usb-moded` answer on D-Bus? | `gdbus call --system --dest com.meego.usb_moded --object-path /com/meego/usb_moded --method com.meego.usb_moded.mode_request` |
| Does a Waydroid vendor image exist for your Halium version? | `curl -sI https://ota.waydro.id/vendor/waydroid_arm64/HALIUM_<n>.json` |

## Probably different

- **GPU libraries** (`waydroid-mali-libs.sh`). Only needed when the container's Android is older than the host's vendor partition and the GPU driver fails to load. The list is for MediaTek MT6878 / Mali.
- **Video encoder.** `waydroid-lxc-extra.sh` disables `c2.mtk.avc.encoder` and `c2.mtk.hevc.encoder` by patching the host's `/vendor/etc/media_codecs_c2.xml`. On another SoC the hardware encoder may simply work, or have another name (`dumpsys media.player | grep Encoder` inside the container). Try without the override first: if Android Auto's logcat shows `Frame stuck or lost in encoder!`, you need it.
- **`debug.stagefright.c2inputsurface=-1`.** Needed here because the 32-bit OMX service in the container cannot allocate graphics buffers. Harmless to keep.
- **Vendor channel workaround.** Only for hosts without a matching Waydroid vendor image.

## With a newer Waydroid image

Work is under way upstream to let Android 16 Waydroid images use a Halium host's gralloc5 and Codec2 services directly. With such an image, the GPU library copy, the encoder override and possibly the input-surface setting may all be unnecessary. The relay and the GPS bridge would stay the same.

## If something does not work

The relay writes Android's logcat of the last session to `/userdata/android-auto/diag/aa-last-session.txt`. Useful greps:

```sh
grep -E "CAR\.SERVICE: (Car connection state|Critical)|USB disconnect|Frame stuck|CAR\.VIDEO: Choosing" aa-last-session.txt
grep -E "Gralloc|GraphicBufferAllocator|GLCOMPOSER|createInputSurface" aa-last-session.txt
```

`phone/debug/aa-test.sh` runs one session against the emulator over TCP and prints the video-pipeline lines, which separates Android-side problems from USB-side ones.
