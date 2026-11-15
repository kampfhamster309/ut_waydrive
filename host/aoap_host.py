#!/usr/bin/env python3
"""Play the car's side of the AOAP handshake against the phone (PC = USB host).

Sends ACCESSORY_GET_PROTOCOL (51), the identifying strings (52) the way an Android
Auto head unit does, ACCESSORY_START (53), then waits for the phone to come back as
18d1:2d00/2d01 and exchanges one test message over the bulk endpoints.
"""
import sys, time
import usb.core, usb.util

PHONE = (0x0E8D, 0x201D)
ACC_PIDS = (0x2D00, 0x2D01)
STRINGS = ["Android", "Android Auto", "Android Auto", "2.0.1",
           "https://www.android.com/auto/", "HU-AAAAAA001"]

dev = usb.core.find(idVendor=PHONE[0], idProduct=PHONE[1])
if dev is None:
    dev = usb.core.find(idVendor=0x18D1, custom_match=lambda d: d.idProduct in ACC_PIDS)
    if dev is None:
        sys.exit("phone not found on USB")
    print("phone is already in accessory mode")
else:
    ver = dev.ctrl_transfer(0xC0, 51, 0, 0, 2)
    proto = ver[0] | ver[1] << 8
    print(f"AOAP protocol version: {proto}")
    if proto < 1:
        sys.exit("phone does not speak AOAP (is aoap-test.sh run armed?)")
    for i, s in enumerate(STRINGS):
        dev.ctrl_transfer(0x40, 52, 0, i, s.encode() + b"\0")
    dev.ctrl_transfer(0x40, 53, 0, 0, None)
    print("sent ACCESSORY_START, waiting for re-enumeration ...")
    dev = None
    for _ in range(40):
        time.sleep(0.5)
        dev = usb.core.find(idVendor=0x18D1, custom_match=lambda d: d.idProduct in ACC_PIDS)
        if dev:
            break
    if dev is None:
        sys.exit("phone did not come back as 18d1:2d00/2d01")

print(f"accessory device: {dev.idVendor:04x}:{dev.idProduct:04x}")
try:
    dev.set_configuration()
except usb.core.USBError:
    pass
intf = dev.get_active_configuration()[(0, 0)]
ep_out = usb.util.find_descriptor(intf, custom_match=lambda e:
    usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT)
ep_in = usb.util.find_descriptor(intf, custom_match=lambda e:
    usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN)
time.sleep(1)
msg = b"hello from the fake car"
ep_out.write(msg)
reply = bytes(ep_in.read(16384, timeout=5000))
print(f"reply: {reply!r}")
print("AOAP round trip OK" if reply == b"ECHO:" + msg else "unexpected reply")
