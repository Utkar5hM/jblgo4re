#!/usr/bin/env python3
"""Temporarily enable Go 4 USB diagnostic key reports and listen for buttons.

Experimental: the commands and framing are reconstructed from the 0.6.4.0
stage-0 image. The live service-mode CDC parser has not been confirmed to reply.
The KIN/KOF commands change only a RAM gate in that image; no flash is written.
"""

import argparse
import datetime as dt
import time

import usb.core
import usb.util

from cdc_version import IN_ENDPOINT, INTERFACE, OUT_ENDPOINT, PID, VID, make_frame


def send(device, command: bytes) -> None:
    frame = make_frame(command)
    sent = device.write(OUT_ENDPOINT, frame, timeout=2000)
    if sent != len(frame):
        raise RuntimeError(f"short USB write: {sent}/{len(frame)}")
    print(f"TX {command.decode('ascii').strip()} ({sent} bytes)", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=20)
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be positive")

    device = usb.core.find(idVendor=VID, idProduct=PID)
    if device is None:
        parser.error("Go 4 service-mode device 0ac8:bb91 is not connected")
    device.get_active_configuration()
    if device.is_kernel_driver_active(INTERFACE):
        parser.error("interface 3 has a kernel driver; refusing to detach it")
    usb.util.claim_interface(device, INTERFACE)
    enabled = False
    try:
        send(device, b"AT+HMDevKIN\r\n")
        enabled = True
        deadline = time.monotonic() + args.seconds
        print("Press Volume+, Volume-, and Play now; listening on CDC IN 0x83.", flush=True)
        while time.monotonic() < deadline:
            try:
                reply = bytes(device.read(IN_ENDPOINT, 64, timeout=500))
            except usb.core.USBTimeoutError:
                continue
            stamp = dt.datetime.now(dt.timezone.utc).isoformat()
            print(f"RX {stamp} {reply.hex(' ')} {reply.decode('ascii', 'replace')!r}", flush=True)
    finally:
        try:
            if enabled:
                send(device, b"AT+HMDevKOF\r\n")
        finally:
            usb.util.release_interface(device, INTERFACE)
            usb.util.dispose_resources(device)


if __name__ == "__main__":
    main()
