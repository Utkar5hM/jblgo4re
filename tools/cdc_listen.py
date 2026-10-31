#!/usr/bin/env python3
"""Passively read the Go 4 service-mode USB CDC bulk IN endpoint."""

import argparse
import datetime as dt
import time

import usb.core
import usb.util


VID = 0x0AC8
PID = 0xBB91
INTERFACE = 3
IN_ENDPOINT = 0x83


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=15)
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be positive")

    device = usb.core.find(idVendor=VID, idProduct=PID)
    if device is None:
        parser.error("Go 4 service-mode device 0ac8:bb91 is not connected")
    try:
        device.get_active_configuration()
        if device.is_kernel_driver_active(INTERFACE):
            parser.error("interface 3 has a kernel driver; this tool will not detach it")
        usb.util.claim_interface(device, INTERFACE)
    except usb.core.USBError as error:
        parser.error(f"cannot open USB interface: {error}")

    deadline = time.monotonic() + args.seconds
    print("Listening on 0ac8:bb91 interface 3, endpoint 0x83; no data will be sent.", flush=True)
    try:
        while time.monotonic() < deadline:
            try:
                payload = bytes(device.read(IN_ENDPOINT, 64, timeout=500))
            except usb.core.USBTimeoutError:
                continue
            stamp = dt.datetime.now(dt.timezone.utc).isoformat()
            print(stamp, payload.hex(" "), repr(payload.decode("ascii", "replace")), flush=True)
    finally:
        usb.util.release_interface(device, INTERFACE)
        usb.util.dispose_resources(device)


if __name__ == "__main__":
    main()
