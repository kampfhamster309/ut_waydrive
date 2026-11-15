#!/bin/sh
# Make the working Android Auto video setup permanent, including across reboots.
# Run with sudo from ~/android-auto. Restarts Waydroid.
#   1. copies the Android Auto scripts to /userdata/android-auto (root-owned, OTA-proof)
#   2. debug.stagefright.c2inputsurface=-1 in waydroid.cfg [properties]
#      (encoder input surface is created inside the calling 64-bit app)
#   3. systemd drop-in for waydroid-container.service that re-adds the codec override
#      after every 'waydroid upgrade -o' (which runs on each service start)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
DST=/userdata/android-auto
WCFG=/var/lib/waydroid/waydroid.cfg
DROPIN=/etc/systemd/system/waydroid-container.service.d
U=phablet; R=/run/user/$(id -u $U)
SESS="runuser -u $U -- env XDG_RUNTIME_DIR=$R DBUS_SESSION_BUS_ADDRESS=unix:path=$R/bus"
A="lxc-attach -P /var/lib/waydroid/lxc -n waydroid --clear-env --"

mkdir -p $DST/gps
cp $HERE/aa-bridge.py $HERE/aa-gps-bridge.py $HERE/waydroid-lxc-extra.sh $HERE/aa-grant-location.sh $HERE/aa-bridge.service $DST/
cp $HERE/gps/pos.qml $DST/gps/
chown -R root:root $DST; chmod -R go-w $DST; chmod 755 $DST $DST/gps
echo "scripts installed in $DST"

python3 - "$WCFG" <<'PY'
import sys, configparser
p = sys.argv[1]
c = configparser.ConfigParser(); c.optionxform = str; c.read(p)
if not c.has_section("properties"): c.add_section("properties")
c.set("properties", "debug.stagefright.c2inputsurface", "-1")
with open(p, "w") as f: c.write(f)
PY

mkdir -p $DROPIN
printf '[Service]\nExecStartPre=-/bin/sh %s/waydroid-lxc-extra.sh\n' "$DST" > $DROPIN/android-auto.conf
systemctl daemon-reload

$SESS waydroid session stop >/dev/null 2>&1; sleep 2
systemctl restart waydroid-container
sleep 2
echo "container config: $(grep -c 'android-auto: software video encoder' /var/lib/waydroid/lxc/waydroid/config) override entry"
echo "base props:       $(grep c2inputsurface /var/lib/waydroid/waydroid_base.prop)"
$SESS systemd-run --user --unit=waydroid-session-$(date +%s) waydroid session start >/dev/null 2>&1
echo "waiting for Android to boot ..."
for i in $(seq 1 60); do sleep 3; [ "$($A /system/bin/getprop sys.boot_completed 2>/dev/null)" = 1 ] && break; done
$SESS waydroid prop set persist.waydroid.suspend false >/dev/null 2>&1
echo "H.264 encoders: $($A /system/bin/sh -c 'dumpsys media.player | grep -E "Encoder \"" | grep -i avc' | tr -s ' ' | tr '\n' ' ')"
echo "c2inputsurface: $($A /system/bin/getprop debug.stagefright.c2inputsurface)"
