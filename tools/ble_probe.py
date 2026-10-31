#!/usr/bin/env python3
"""Read the Go 4's product ID, firmware version, and battery over BLE.

Only JBL read requests (AA 41 00 and AA 11 00) are sent. No settings or
firmware update commands are used. Names, serials, and Bluetooth addresses
received from the speaker are deliberately not printed.
"""

import argparse
import asyncio

from bleak import BleakClient, BleakScanner

SERVICE = "65786365-6c70-6f69-6e74-2e636f6d0000"
NOTIFY = "65786365-6c70-6f69-6e74-2e636f6d0001"
WRITE = "65786365-6c70-6f69-6e74-2e636f6d0002"
GO4_PID = 0x20E4


def product_id(advertisement):
    data = advertisement.manufacturer_data.get(0x0057, b"")
    return int.from_bytes(data[:2], "little") if len(data) >= 2 else None


def decode(data):
    """Return only non-identifying fields from a complete short JBL frame."""
    # Some 0x42 replies append a status byte after the declared frame length.
    if len(data) < 3 or data[0] != 0xAA or len(data) < 3 + data[2]:
        return None
    command, body = data[1], data[3:3 + data[2]]
    if command == 0x42 and len(body) >= 4:
        return ("firmware", ".".join(map(str, body[:4])))
    if command == 0x12 and len(body) >= 3 and body[0] == 0:
        token, value = body[1], body[2:]
        if token == 0x42 and len(value) >= 2:
            return ("product_id", f"0x{int.from_bytes(value[:2], 'big'):04x}")
        if token == 0x44:
            return ("battery", f"{value[0] & 0x7f}%" + (" (charging)" if value[0] & 0x80 else ""))
        if token == 0x4D:
            return ("firmware_code", value.decode("ascii", errors="replace"))
    return None


async def probe(address, scan_seconds):
    seen = await BleakScanner.discover(timeout=scan_seconds, return_adv=True)
    matches = [(device, product_id(ad)) for device, ad in seen.values()
               if product_id(ad) == GO4_PID and (address is None or device.address.lower() == address.lower())]
    if not matches:
        raise SystemExit("No advertising Go 4 found. Ensure it is powered on and near the host.")
    if len(matches) != 1:
        raise SystemExit("Multiple Go 4 speakers found; pass --address to choose one.")
    device, pid = matches[0]
    print(f"advertised_product_id: 0x{pid:04x}")
    async with BleakClient(device, timeout=20) as client:
        if SERVICE not in [service.uuid for service in client.services]:
            raise SystemExit("Go 4 control service is unavailable.")
        found = {}

        def notification(_characteristic, payload):
            item = decode(bytes(payload))
            if item:
                found[item[0]] = item[1]
                print(f"{item[0]}: {item[1]}", flush=True)

        await client.start_notify(NOTIFY, notification)
        for packet in (bytes.fromhex("aa4100"), bytes.fromhex("aa1100")):
            await client.write_gatt_char(WRITE, packet, response=True)
            await asyncio.sleep(2)
        await client.stop_notify(NOTIFY)
        if "firmware" not in found:
            raise SystemExit("Control service replied, but no firmware version was received.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", help="LE address when multiple Go 4 speakers are advertising")
    parser.add_argument("--scan-seconds", type=float, default=10)
    args = parser.parse_args()
    asyncio.run(probe(args.address, args.scan_seconds))


if __name__ == "__main__":
    main()
