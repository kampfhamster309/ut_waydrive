#!/bin/sh
# Dump Android-side diagnostics from Waydroid into ~/android-auto/diag (run with sudo).
#   sudo sh waydroid-diag.sh [package-to-launch]
set -u
OUT=/home/phablet/android-auto/diag; mkdir -p $OUT
A="lxc-attach -P /var/lib/waydroid/lxc -n waydroid --clear-env --"
if [ -n "${1:-}" ]; then
    $A /system/bin/logcat -c
    $A /system/bin/am start -W "$(${A} /system/bin/cmd package resolve-activity --brief "$1" | tail -1)" > $OUT/launch.txt 2>&1
    sleep 8
fi
$A /system/bin/logcat -d -b all > $OUT/logcat3.txt 2>&1
$A /system/bin/dumpsys window windows > $OUT/windows.txt 2>&1
$A /system/bin/dumpsys activity activities > $OUT/activities.txt 2>&1
$A /system/bin/dumpsys SurfaceFlinger > $OUT/surfaceflinger.txt 2>&1
$A /system/bin/getprop > $OUT/props.txt 2>&1
chown -R phablet:phablet $OUT
echo "saved to $OUT"
