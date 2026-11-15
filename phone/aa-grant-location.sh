#!/bin/sh
# Grant location permissions to navigation apps inside Waydroid without the Android UI.
# Run with sudo.   sudo sh aa-grant-location.sh [package ...]   (default: com.waze)
A="lxc-attach -P /var/lib/waydroid/lxc -n waydroid --clear-env --"
[ $# -eq 0 ] && set -- com.waze
for PKG in "$@"; do
    for P in ACCESS_FINE_LOCATION ACCESS_COARSE_LOCATION ACCESS_BACKGROUND_LOCATION POST_NOTIFICATIONS; do
        $A /system/bin/pm grant $PKG android.permission.$P 2>&1 | grep -v "^$" | head -1
    done
    echo "$PKG:"
    $A /system/bin/sh -c "dumpsys package $PKG | grep -E 'ACCESS_(FINE|COARSE|BACKGROUND)_LOCATION: granted' | sed 's/^ */  /'"
done
