#!/bin/sh
# Waydroid on the Plinius (Halium 14 host, HALIUM_13 vendor image): the host Mali
# driver (libGLES_mali.so via libGLES_meow) needs Android 14 / MediaTek libraries
# the Android 13 container lacks. Copy them from the host into Waydroid's vendor
# overlay, switch back to the host GPU, restart, wait for boot, save the log.
#   sudo sh waydroid-mali-libs.sh          apply + test
#   sudo sh waydroid-mali-libs.sh --remove remove the copied libraries
set -u
OV=/var/lib/waydroid/overlay/vendor
OUT=/home/phablet/android-auto/diag
LIST="android.hardware.graphics.allocator-V2-ndk.so:/android/system
android.hardware.graphics.common-V5-ndk.so:/android/system
android.hardware.graphics.common-V4-ndk.so:/android/apex/com.android.vndk.v34
libged.so:/vendor
libgpud.so:/vendor
libgralloc_extra.so:/vendor
libladder.so:/vendor
libgralloc_metadata.so:/vendor
libgralloctypes_mtk.so:/vendor
arm.mali.platform-V2-ndk.so:/vendor"

for d in lib lib64; do
    mkdir -p $OV/$d
    echo "$LIST" | while IFS=: read lib src; do
        if [ "${1:-}" = "--remove" ]; then rm -f $OV/$d/$lib; continue; fi
        [ -f $src/$d/$lib ] && cp -p $src/$d/$lib $OV/$d/ && echo "  $d/$lib"
    done
done
[ "${1:-}" = "--remove" ] && { echo "removed"; exit 0; }

grep -E "ro.hardware.(egl|gralloc)" /var/lib/waydroid/waydroid_base.prop

# restart and wait for Android to boot
U=phablet; R=/run/user/$(id -u $U)
runuser -u $U -- env XDG_RUNTIME_DIR=$R DBUS_SESSION_BUS_ADDRESS=unix:path=$R/bus waydroid session stop >/dev/null 2>&1
sleep 3
runuser -u $U -- env XDG_RUNTIME_DIR=$R DBUS_SESSION_BUS_ADDRESS=unix:path=$R/bus \
    systemd-run --user --unit=waydroid-session-$(date +%s) waydroid session start >/dev/null 2>&1
echo "waiting up to 3 min for Android to boot ..."
B=0
for i in $(seq 1 60); do
    sleep 3
    B=$(lxc-attach -P /var/lib/waydroid/lxc -n waydroid --clear-env -- /system/bin/getprop sys.boot_completed 2>/dev/null)
    [ "$B" = 1 ] && break
done
echo "sys.boot_completed=$B"
lxc-attach -P /var/lib/waydroid/lxc -n waydroid --clear-env -- /system/bin/logcat -d -b all > $OUT/logcat2.txt 2>&1
chown -R phablet:phablet $OUT
echo "log in $OUT/logcat2.txt"
