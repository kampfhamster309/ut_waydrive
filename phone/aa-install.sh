#!/bin/sh
# Install Android Auto support so it works without a PC. Run with sudo from ~/android-auto.
#   sudo sh aa-install.sh            install / update
#   sudo sh aa-install.sh --remove   stop and remove the relay service (Waydroid setup stays)
# What it does:
#   1. stops a relay that was started by hand
#   2. waydroid-aa-persist.sh: scripts to /userdata/android-auto, video settings,
#      systemd drop-in for waydroid-container, restart Waydroid
#   3. installs and starts aa-bridge.service (starts at every boot)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
DST=/userdata/android-auto
UNIT=/etc/systemd/system/aa-bridge.service

if [ "${1:-}" = "--remove" ]; then
    systemctl disable --now aa-bridge 2>/dev/null
    rm -f $UNIT; systemctl daemon-reload
    echo "aa-bridge service removed"; exit 0
fi

echo "== 1. stopping relays"
systemctl stop aa-bridge 2>/dev/null
pkill -TERM -f "[a]a-bridge.py" 2>/dev/null && sleep 6
pkill -TERM -f "[a]a-gps-bridge.py" 2>/dev/null && sleep 3
U=phablet; R=/run/user/$(id -u $U)
runuser -u $U -- env XDG_RUNTIME_DIR=$R DBUS_SESSION_BUS_ADDRESS=unix:path=$R/bus waydroid session stop >/dev/null 2>&1
sleep 2; systemctl stop waydroid-container 2>/dev/null

echo "== 2. Waydroid setup (restarts Waydroid, about a minute)"
sh $HERE/waydroid-aa-persist.sh || exit 1

echo "== 3. relay service"
cp $DST/aa-bridge.service $UNIT
systemctl daemon-reload
systemctl enable aa-bridge >/dev/null 2>&1
systemctl restart aa-bridge
sleep 12
systemctl is-enabled aa-bridge; systemctl is-active aa-bridge
journalctl -u aa-bridge --no-pager -n 8 | cut -c40-
