#!/bin/sh
# One Android Auto video test round (run with sudo):
#   fresh head unit server [+ optional c2inputsurface value], wait for the simulator to
#   connect (click the WiFi tile when told), then print what the video pipeline did.
#   sudo sh aa-test.sh [c2inputsurface]
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
A="lxc-attach -P /var/lib/waydroid/lxc -n waydroid --clear-env --"
OUT=/home/phablet/android-auto/diag/aa-test.txt
mkdir -p /home/phablet/android-auto/diag
sh $HERE/aa-reset.sh "${1:-}" || exit 1
echo ">>> NOW click the WiFi tile in the simulator (waiting up to 2 min) <<<"
for i in $(seq 1 120); do
    sleep 1
    $A /system/bin/logcat -d -s CAR.VIDEO | grep -q "Choosing codec" && break
done
sleep 12
$A /system/bin/logcat -d -b all > $OUT 2>&1
chown phablet:phablet $OUT
echo "== video pipeline:"
grep -E "CAR\.VIDEO|CAR\.MEDIA\.VIDEO|CAR\.WM |Codec2Client: (Create|connect|Available)|createInputSurface|GraphicBufferSource|C2OMXNode|Gralloc|GraphicBufferAllocator|BufferQueueProducer|GLCOMPOSER|Critical error|eglp_|persistent input|Codec2 (component|service)|C2Soft|CCodecBufferChannel.*(error|fail)|invalid usage" $OUT \
  | grep -v -E "^\s*at |ConnLogger|nfc" | cut -c19-200 | awk '!seen[$0]++' | head -40
