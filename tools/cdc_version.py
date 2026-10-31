#!/usr/bin/env python3
"""Query the Go 4 service-mode firmware version over USB CDC bulk endpoints.

This sends only the AT+HMDevVER query found in the archived stage-0 firmware.
It does not issue any state-changing command or firmware update.
"""

import datetime as dt

import usb.core
import usb.util


VID = 0x0AC8
PID = 0xBB91
INTERFACE = 3
OUT_ENDPOINT = 0x04
IN_ENDPOINT = 0x83
FRAME_SIZE = 60
COMMAND = b"AT+HMDevVER\r\n"


def crc16_ccitt(data: bytes) -> int:
    value = 0
    for byte in data:
        value ^= byte << 8
        for _ in range(8):
            value = ((value << 1) ^ (0x1021 if value & 0x8000 else 0)) & 0xFFFF
    return value


def make_frame() -> bytes:
    frame = bytearray(FRAME_SIZE)
    frame[:4] = bytes((0x0F, 0xF0, len(COMMAND), 0))
    frame[4 : 4 + len(COMMAND)] = COMMAND
    checksum = crc16_ccitt(frame[:58])
    frame[58:60] = checksum.to_bytes(2, "little")
    return bytes(frame)


def main() -> None:
    device = usb.core.find(idVendor=VID, idProduct=PID)
    if device is None:
        raise SystemExit("Go 4 service-mode device 0ac8:bb91 is not connected")
    device.get_active_configuration()
    if device.is_kernel_driver_active(INTERFACE):
        raise SystemExit("Interface 3 has a kernel driver; refusing to detach it")
    usb.util.claim_interface(device, INTERFACE)
    try:
        frame = make_frame()
        print(f"TX {dt.datetime.now(dt.timezone.utc).isoformat()} {frame.hex(' ')}", flush=True)
        sent = device.write(OUT_ENDPOINT, frame, timeout=2000)
        print(f"Wrote {sent}/{len(frame)} bytes", flush=True)
        if sent != len(frame):
            raise SystemExit("Short USB write")
        for _ in range(5):
            try:
                reply = bytes(device.read(IN_ENDPOINT, 64, timeout=500))
            except usb.core.USBTimeoutError:
                continue
            stamp = dt.datetime.now(dt.timezone.utc).isoformat()
            print(f"RX {stamp} {reply.hex(' ')} {reply.decode('ascii', 'replace')!r}", flush=True)
    finally:
        usb.util.release_interface(device, INTERFACE)
        usb.util.dispose_resources(device)


if __name__ == "__main__":
    main()
