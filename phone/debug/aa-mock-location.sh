#!/bin/sh
# Feed a fixed position into Android (Waydroid) as the "gps" provider, to test whether
# apps such as Waze accept injected locations. Run with sudo.
#   sudo sh aa-mock-location.sh <lat> <lon> [seconds, default 120]
#   sudo sh aa-mock-location.sh --stop
set -u
A="lxc-attach -P /var/lib/waydroid/lxc -n waydroid --clear-env --"
if [ "${1:-}" = "--stop" ]; then
    $A /system/bin/cmd location providers remove-test-provider gps
    echo "test provider removed"; exit 0
fi
LAT=${1:?usage: aa-mock-location.sh <lat> <lon> [seconds]}; LON=${2:?missing <lon>}; SECS=${3:-120}
$A /system/bin/cmd location set-location-enabled true
# injecting locations needs the MOCK_LOCATION app-op; we call as root (uid 0)
$A /system/bin/cmd appops set root android:mock_location allow
$A /system/bin/cmd location providers add-test-provider gps --supportsAltitude --supportsSpeed --supportsBearing 2>&1 | grep -v "^$" | head -2
if $A /system/bin/cmd location providers set-test-provider-enabled gps true 2>&1 | grep -q SecurityException; then
    echo "still not allowed to inject locations - stopping"; exit 1
fi
echo "feeding $LAT,$LON as GPS for $SECS s (Ctrl-C to stop early) ..."
$A /system/bin/sh -c "i=0; while [ \$i -lt $SECS ]; do cmd location providers set-test-provider-location gps --location $LAT,$LON --accuracy 5 || exit 1; i=\$((i+1)); sleep 1; done" 2>&1 | head -5
echo "done (provider stays registered; --stop removes it)"
