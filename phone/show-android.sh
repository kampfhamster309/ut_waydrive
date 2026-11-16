#!/bin/sh
# Open Android's screen (Waydroid full UI) as a window on the phone. No root needed:
# the relay service (aa-bridge) picks the request up within a second and does it.
# Use this instead of "waydroid show-full-ui", which does nothing when Waydroid still
# believes an old window is open.
f="/run/user/$(id -u)/aa-show-android"
: > "$f" || { echo "cannot write $f" >&2; exit 1; }
n=0
while [ -e "$f" ] && [ $n -lt 10 ]; do sleep 0.5; n=$((n+1)); done
if [ -e "$f" ]; then
    echo "aa-bridge did not pick the request up (systemctl is-active aa-bridge?)" >&2
    rm -f "$f"; exit 1
fi
echo "requested; see: journalctl -u aa-bridge -n 3 --no-pager"
