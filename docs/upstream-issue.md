# Waydroid on a Halium 14 MediaTek device: no HALIUM_14 vendor image, GPU and video-encoder fixes needed (Volla Phone Plinius)

> Draft of a report for the UBports Waydroid packaging project. Not filed yet.

**Project:** ubports/development/core/packaging/waydroid
**Related:** !38 (host AIDL Codec2 stores), !27/!33, waydroid/waydroid#2410, waydroid/waydroid#2229

## Device / versions

- Volla Phone Plinius (`ansuz`), MediaTek MT6878, Mali GPU (DDK r44, `libGLES_meow` → `libGLES_mali`). The host vendor exposes gralloc5 (`IMapper @5.0/mediatek`, AIDL allocator V2).
- Ubuntu Touch 24.04 (Halium 14, GKI android14-6.1), `waydroid 1.6.3-0ubports1~20260918…+ubports24.04.2`.
- Image: `lineage-20.0-20260927-GAPPS-waydroid_arm64` (Android 13).

## 1. `waydroid init` fails: no HALIUM_14 vendor channel

`get_vendor_type()` gives `HALIUM_14` (from `ro.vndk.version` 34), but `https://ota.waydro.id/vendor/waydroid_arm64/HALIUM_14.json` returns 404:

```
ERROR: Failed to get vendor OTA channel: https://ota.waydro.id/vendor/waydroid_arm64/HALIUM_14.json
```

The Plinius thread on the forum hits the same wall. Workaround: a local channel holding a copy of `HALIUM_13.json` under the name `HALIUM_14.json`, passed with `waydroid init -s GAPPS -v file:///…`.

## 2. With the HALIUM_13 vendor, the container boot-loops: the host Mali driver needs Android 14 libraries

The hwcomposer, surfaceflinger and zygote crash in a loop (SIGSEGV in `eglGetDisplay`):

```
E libMEOW : load_driver(/vendor/lib64/egl/libGLES_mali.so): dlopen failed: library "android.hardware.graphics.allocator-V2-ndk.so" not found: needed by /vendor/lib64/egl/mt6878/libGLES_mali.so in namespace sphal
```

Copying these host libraries into `/var/lib/waydroid/overlay/vendor/lib64` (plus the three framework ones into `lib`) fixes it. Android then boots on the Mali GPU (OpenGL ES 3.2 v1.r44p1) and normal apps render fine:

| library | source on the host |
|---|---|
| android.hardware.graphics.allocator-V2-ndk.so | /android/system |
| android.hardware.graphics.common-V5-ndk.so | /android/system |
| android.hardware.graphics.common-V4-ndk.so | /android/apex/com.android.vndk.v34 |
| libged.so, libgpud.so, libgralloc_extra.so, libladder.so, libgralloc_metadata.so, libgralloctypes_mtk.so, arm.mali.platform-V2-ndk.so | /vendor |

Software rendering (`gralloc=default`, `egl=swiftshader`) does not work as a fallback: surfaceflinger aborts.

A HALIUM_14 vendor image, or shipping or bind-mounting these libraries automatically, would make Waydroid work out of the box on this class of device.

## 3. Video encoding from a GL surface fails by default (affects Android Auto, screen recording, video calls…)

Use case: Android Auto running in Waydroid, with its developer "head unit server" bridged to a car or head unit. The connection, TLS, service discovery, audio and input channels all work. **By default no video frames are produced**, because the encoder's input surface can't be allocated or connected. A workaround is in (c).

**a) Default path (OMX `GraphicBufferSource` in the 32-bit `vendor.media.omx`)**

The Mali producer sets usage bits that this libui (Gralloc2 fallback, since mapper 4/3 aren't present) rejects:

```
E Gralloc2: buffer descriptor contains invalid usage bits 0x1e000000000
E GraphicBufferAllocator: Failed to allocate (800 x 480) layerCount 1 format 1 usage 10203: -22
E BufferQueueProducer: [GraphicBufferSource] dequeueBuffer: createGraphicBuffer failed
W mali: eglp_window_next_render_target, get next target buffer for the winsys surface failed.
E CAR.WM.GLCOMPOSER: window draw: glError 1285
```

- Passing the host `ro.vendor.arm.gralloc.*` props into the container changes nothing.
- As an experiment I patched the VNDK `libui.so` to strip the unknown bits. Allocation still fails (`GraphicBufferAllocator … : 3`): the 32-bit process has no working gralloc at all, since the host ships no 32-bit vendor graphics libraries.
- This happens with both `c2.mtk.avc.encoder` and `c2.android.avc.encoder`.

**b) `debug.stagefright.c2inputsurface=1`**

The input surface always comes from the host MTK store `"default"` (HIDL `android.hardware.media.c2@1.2::IComponentStore/default`, declared through `vendor_extra/etc/vintf/manifest/manifest_media_c2_V1_2_default.xml`). Connecting it fails:

```
I Codec2Client: CreateInputSurface -- input surface obtained from service "default"
E Codec2Client: connectToInputSurface -- transaction failed
E CCodec  : Codec2 component "c2.mtk.avc.encoder" died.
I MediaPlayerService: Codec2 service "default" died.
```

- With the MTK encoders disabled through a patched `media_codecs_c2.xml`, the same happens with `c2.android.avc.encoder`, and then the `"software"` service dies instead.
- Hiding the `default` VINTF fragment (an empty manifest bind-mounted over it) does **not** remove `"default"` from the service list, so it seems to be forwarded from the host regardless.
- The host's own logcat shows no crash record for the MTK service.

**c) Workaround that works: `debug.stagefright.c2inputsurface=-1` plus the software encoder**

With `-1`, CCodec creates the `OmxGraphicBufferSource` inside the calling 64-bit app process, which can allocate gralloc buffers. Frames then reach the encoder. With `c2.mtk.avc.encoder` they never come out (`CAR.WM: Frame stuck or lost in encoder!`); with the MTK encoders disabled (patched `media_codecs_c2.xml` bind-mounted over `vendor_extra/etc/`) `c2.android.avc.encoder` produces a working H.264 stream and Android Auto projects to a head unit.

Setting `debug.stagefright.c2inputsurface=-1` by default on hosts without a working 32-bit gralloc might be worth considering.

### Questions

1. Are HALIUM_14 vendor images (or arm64 Android 16 images for !38 / #2410) planned or available on some channel? Would those images route encoder input surfaces through the host's gralloc5 stack?
2. Is `connectToInputSurface` across the container↔host Codec2 bridge expected to work for HIDL stores, or only for the AIDL stores from !38?
3. Would you accept a patch that bind-mounts the host graphics libraries from section 2 into the container for HALIUM_14 hosts using the HALIUM_13 vendor?

I can test on the Plinius and provide full logcats.
