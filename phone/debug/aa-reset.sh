#!/bin/sh
# Fresh Android Auto head unit server inside Waydroid (run with sudo).
#   sudo sh aa-reset.sh [c2inputsurface-value]
# Optional arg sets debug.stagefright.c2inputsurface (1 = encoder input surface is
# created by the Codec2 service instead of the container's OMX service).
set -u
A="lxc-attach -P /var/lib/waydroid/lxc -n waydroid --clear-env --"
PKG=com.google.android.projection.gearhead
if [ -n "${1:-}" ]; then
    $A /system/bin/setprop debug.stagefright.c2inputsurface "$1"
    echo "debug.stagefright.c2inputsurface=$($A /system/bin/getprop debug.stagefright.c2inputsurface)"
fi
$A /system/bin/logcat -c
$A /system/bin/am force-stop $PKG
sleep 1
$A /system/bin/am start-foreground-service -n $PKG/.companion.DeveloperHeadUnitNetworkService
for i in $(seq 1 20); do
    sleep 1
    $A /system/bin/logcat -d -s GH.DHUService | grep -q "Network server running" && { echo "head unit server running"; exit 0; }
done
echo "head unit server did not report running (check the log)"
