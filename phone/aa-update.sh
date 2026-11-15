#!/bin/sh
# Copy updated relay files from ~/android-auto to /userdata/android-auto and restart the
# service (no Waydroid restart). Run with sudo.
HERE=$(cd "$(dirname "$0")" && pwd)
DST=/userdata/android-auto
cp $HERE/aa-bridge.py $HERE/aa-gps-bridge.py $HERE/waydroid-lxc-extra.sh $HERE/aa-grant-location.sh $HERE/aa-bridge.service $DST/
cp $HERE/gps/pos.qml $DST/gps/
chown -R root:root $DST; chmod -R go-w $DST
cmp -s $DST/aa-bridge.service /etc/systemd/system/aa-bridge.service || { cp $DST/aa-bridge.service /etc/systemd/system/; systemctl daemon-reload; }
systemctl restart aa-bridge
sleep 10
systemctl is-active aa-bridge
journalctl -u aa-bridge --no-pager -n 6 | cut -c40-
