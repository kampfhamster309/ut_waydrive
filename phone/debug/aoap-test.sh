#!/bin/sh
# AOAP (Android Open Accessory) proof of concept for Ubuntu Touch on the Plinius.
# The car (or a PC acting as the car) is the USB host and asks the phone to switch
# into "accessory mode". Android does this in UsbDeviceManager; here we do it by hand
# with the kernel's f_accessory function (CONFIG_USB_CONFIGFS_F_ACC=y).
#
#   sudo sh aoap-test.sh run      arm, wait for the host's ACCESSORY_START, re-enumerate
#                                 as 18d1:2d00, echo whatever the host sends for 60 s,
#                                 then restore the normal gadget
#   sudo sh aoap-test.sh restore  put the normal gadget back (if run was interrupted)
set -u
G=/sys/kernel/config/usb_gadget/g1
C=$G/configs/c.1
F=$G/functions/accessory.gs2
SAVE=/run/aoap-test.saved

log() { echo "[aoap] $*"; }

restore() {
    log "restoring normal gadget"
    UDC=$(ls /sys/class/udc | head -1)
    echo "" > $G/UDC 2>/dev/null
    rm -f $C/accessory.gs2
    if [ -f $SAVE ]; then
        . $SAVE
        echo "$VID" > $G/idVendor
        echo "$PID" > $G/idProduct
        for f in $LINKS; do [ -e $C/$f ] || ln -s $G/functions/$f $C/$f; done
    fi
    rmdir $F 2>/dev/null
    echo "$UDC" > $G/UDC 2>/dev/null
    systemctl start usb-moded
    rm -f $SAVE
    log "done: $(cat $G/idVendor):$(cat $G/idProduct) functions: $(ls $C | grep -v -e bm -e Max -e strings | tr '\n' ' ')"
}

run() {
    [ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
    LINKS=$(cd $C && for l in *; do [ -L "$l" ] && echo "$l"; done | tr '\n' ' ')
    printf 'VID=%s\nPID=%s\nLINKS="%s"\n' "$(cat $G/idVendor)" "$(cat $G/idProduct)" "$LINKS" > $SAVE
    trap restore EXIT INT TERM

    mkdir -p $F || { log "cannot create accessory function"; exit 1; }
    sleep 0.5
    ls -l /dev/usb_accessory || { log "no /dev/usb_accessory"; exit 1; }
    log "armed. Now run on the PC:  python3 aoap_host.py"
    log "waiting up to 120 s for ACCESSORY=START ..."

    timeout 120 udevadm monitor --kernel --property --subsystem-match=misc 2>/dev/null | \
        grep -m1 -q "ACCESSORY=START"
    if [ $? -ne 0 ]; then log "no ACCESSORY_START from host (timeout)"; exit 1; fi
    log "host sent ACCESSORY_START, re-enumerating as 18d1:2d00"

    systemctl stop usb-moded
    UDC=$(ls /sys/class/udc | head -1)
    echo "" > $G/UDC 2>/dev/null   # usb-moded may already have unbound it
    for f in $LINKS; do rm -f $C/$f; done
    echo 0x18d1 > $G/idVendor
    echo 0x2d00 > $G/idProduct
    ln -s $F $C/accessory.gs2
    echo "$UDC" > $G/UDC
    log "accessory gadget up; echoing host data for 60 s"

    timeout 60 python3 - <<'EOF'
import os, time
fd = os.open("/dev/usb_accessory", os.O_RDWR)
n = 0
while True:
    data = os.read(fd, 16384)
    if not data:
        time.sleep(0.05); continue
    n += 1
    print(f"[aoap] got {len(data)} bytes: {data[:32]!r}", flush=True)
    os.write(fd, b"ECHO:" + data)
EOF
    log "echo loop ended"
}

case "${1:-}" in
    run) run ;;
    restore) restore ;;
    *) echo "usage: sudo sh $0 run|restore"; exit 1 ;;
esac
