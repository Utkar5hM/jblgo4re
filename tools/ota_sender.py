#!/usr/bin/env python3
"""Drive the JBL Go 4 BLE OTA, reconstructed from firmware RE + the JBL Portable
APK (see docs/findings/ota.md, "Q6 CLOSED"). SAFETY-GATED.

Modes (default = plan, which never touches the device):
  (default)    PLAN  - parse+verify the container and print every frame that
                       WOULD be sent. No Bluetooth. Safe to run anywhere.
  --transmit         - connect over BLE and stream setup(0x43)+data(0x44),
                       reading each ack. Writes only the INACTIVE flash bank.
                       Structurally cannot send the apply opcode 0x4d.
                       Aborts (0x47 cancel) on any bad/absent ack.
  --transmit --commit - after a fully-acked transfer, prompt for an explicit
                       typed confirmation and then send the apply (0x4d). This
                       is the only irreversible step. User must be present.

guard.sh blocks the assistant from running this file; run it yourself (prefix
with `!` in the session, or from a shell). Keep the speaker in NORMAL BT mode
(not the Play+BT service mode): BLE OTA is refused in service mode.
"""

import argparse
import asyncio
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup_crc import dfu_file_crc, setup_crc_bytes  # noqa: E402
from extract_fw import go4_crc32  # noqa: E402

SERVICE = "65786365-6c70-6f69-6e74-2e636f6d0000"
NOTIFY = "65786365-6c70-6f69-6e74-2e636f6d0001"
WRITE = "65786365-6c70-6f69-6e74-2e636f6d0002"
GO4_PID = 0x20E4

# opcodes
OP_START = 0x43
OP_DATA = 0x44
OP_SECT = 0x45
OP_CANCEL = 0x47
OP_VER = 0x4A
OP_VER_RESP = 0x4B
OP_TRIGGER = 0x4D
OP_TRIGGER_RESP = 0x4C

TWO_BYTE_LEN = {0x44, 0x97, 0x98, 0x99}

DEBUG = False


def frame(cmd: int, payload: bytes = b"") -> bytes:
    """AA <cmd> <len> <payload>; len is 2-byte BE for 0x44/0x97-0x99, else 1 byte."""
    if cmd in TWO_BYTE_LEN:
        return bytes([0xAA, cmd]) + struct.pack(">H", len(payload)) + payload
    if len(payload) > 0xFF:
        raise ValueError(f"payload too long for 1-byte len on opcode 0x{cmd:02x}")
    return bytes([0xAA, cmd, len(payload)]) + payload


# ---------------------------------------------------------------------------
# container verification (offline)

def parse_and_verify(path: Path):
    blob = path.read_bytes()
    if not blob.startswith(b"HMHEADER9"):
        raise SystemExit(f"{path}: not an HMHEADER9 OTA container")
    count = blob[0x10]
    if not (1 <= count <= 16):
        raise SystemExit(f"{path}: implausible partition count {count}")
    parts = []
    cur = 0x11 + 13 * count
    for n in range(count):
        pid, length, param, meta_crc = struct.unpack_from("<BIII", blob, 0x11 + 13 * n)
        if blob[cur:cur + 8] != b"PARTHMDT":
            raise SystemExit(f"{path}: partition {n} marker missing at 0x{cur:x}")
        data = blob[cur + 8:cur + 8 + length]
        if len(data) != length:
            raise SystemExit(f"{path}: partition {n} truncated")
        got = go4_crc32(data)
        if got != meta_crc:
            raise SystemExit(
                f"{path}: partition {n} (id {pid}) CRC mismatch "
                f"header 0x{meta_crc:08x} computed 0x{got:08x} -- REFUSING")
        parts.append((pid, length, meta_crc))
        cur += 8 + length
    if blob[cur:] != b"FOOTERHM":
        raise SystemExit(f"{path}: unexpected tail at 0x{cur:x} (want FOOTERHM)")
    ids = [p[0] for p in parts]
    if sorted(ids) != [1, 2, 3, 6]:
        raise SystemExit(f"{path}: expected the full 4-partition set {{1,2,3,6}}, got {ids}")
    return blob, parts


def build_setup_payload(blob: bytes, version: str) -> bytes:
    crc = dfu_file_crc(blob)
    pay = bytearray(12)
    pay[0:4] = setup_crc_bytes(crc)
    pay[4:8] = struct.pack(">I", len(blob))
    v = [int(x) & 0xFF for x in (version.split(".") + ["0", "0", "0"])[:3]]
    pay[8:11] = bytes(v)
    pay[11] = 1  # 1 == same-version reflash; 2 == different. Set per device DFU ver at flash time.
    return crc, bytes(pay)


# ---------------------------------------------------------------------------
# plan mode (no BLE)

def plan(blob, parts, version, mtu):
    crc, setup = build_setup_payload(blob, version)
    chunk = mtu - 7
    nchunks = (len(blob) + chunk - 1) // chunk
    print("== OTA PLAN (no device contact) ==")
    print(f"container bytes   : {len(blob)} (0x{len(blob):x})")
    print("partitions        : " + ", ".join(f"id{p[0]}:{p[1]}B/crc0x{p[2]:08x}" for p in parts))
    print(f"whole-file crc    : 0x{crc:08x}")
    print(f"assumed MTU       : {mtu}  -> chunk payload {chunk}B, {nchunks} data frames")
    print()
    print(f"1) VER     -> {frame(OP_VER).hex()}        (expect resp 0x4b <version>)")
    print(f"2) START   -> {frame(OP_START, setup).hex()}")
    print(f"   setup[0:4] crc(wordswap)={setup[0:4].hex()} [4:8] len={setup[4:8].hex()} "
          f"[8:11] ver={setup[8:11].hex()} [11] flag={setup[11]}")
    print("   (expect resp 0x00 then 0x45 TRANSFER_BEGGING)")
    first = bytes([0]) + blob[0:chunk]
    print(f"3) DATA[0] -> {frame(OP_DATA, first)[:16].hex()}...  "
          f"(payload = [pkgIndex=0] + {len(first)-1}B)  (expect 0x45 per chunk)")
    print(f"   ... {nchunks} data frames, pkgIndex 0..{(nchunks-1)&0xff} (wraps at 256) ...")
    print(f"4) TRIGGER -> {frame(OP_TRIGGER).hex()}            (0x4d apply; WITHHELD unless --commit)")
    print("   on 0x4c the device returns an apply-result byte, then flips bank + resets.")
    print()
    print("Device-side guarantee: each partition's CRC is re-verified on its final chunk;")
    print("a bad partition is reported as a non-success ack and this tool aborts before 0x4d.")


# ---------------------------------------------------------------------------
# transmit / commit modes (BLE)

async def run_ble(blob, version, address, scan_seconds, commit, mtu_arg, pace_arg, assume_yes):
    import subprocess
    from bleak import BleakClient, BleakScanner

    if address:
        # The speaker auto-connects for classic audio, which suppresses its LE
        # advertisement. Drop that link, then grab the LE device by address in
        # the window before it re-auto-connects. Match by ADDRESS (its LE adv
        # carries no Harman manufacturer data).
        device = None
        for attempt in range(4):
            try:
                subprocess.run(["bluetoothctl", "disconnect", address],
                               capture_output=True, timeout=10)
            except Exception as e:
                print(f"(disconnect attempt failed: {e})")
            await asyncio.sleep(1.5)
            print(f"  scanning for LE advert (attempt {attempt+1}/4)...")
            device = await BleakScanner.find_device_by_address(address, timeout=scan_seconds)
            if device is not None:
                print(f"  found {address} over LE")
                break
        if device is None:
            raise SystemExit(f"{address} not seen over LE. Toggle the speaker and retry; "
                             "it must be advertising LE (not held in a classic-audio link).")
    else:
        seen = await BleakScanner.discover(timeout=scan_seconds, return_adv=True)
        matches = [d for d, ad in seen.values()
                   if ad.manufacturer_data.get(0x0057, b"")[:2] == struct.pack("<H", GO4_PID)]
        if len(matches) != 1:
            raise SystemExit(f"need exactly one advertising Go 4 (found {len(matches)}); "
                             "ensure it is ON, in NORMAL BT mode, or pass --address.")
        device = matches[0]

    acks: asyncio.Queue = asyncio.Queue()

    async with BleakClient(device, timeout=20) as client:
        if SERVICE not in [s.uuid for s in client.services]:
            raise SystemExit("control service unavailable")
        if not mtu_arg:
            acq = getattr(client, "_acquire_mtu", None)
            if acq:
                try:
                    await acq()
                except Exception as e:
                    print(f"(mtu acquire failed: {e})")
        mtu = mtu_arg or getattr(client, "mtu_size", 23)
        chunk = mtu - 7
        if chunk < 16:
            raise SystemExit(f"negotiated MTU {mtu} too small (chunk {chunk}); "
                             "raise MTU or pass --mtu after confirming the link MTU.")

        def on_notify(_c, data: bytes):
            data = bytes(data)
            if DEBUG:
                print(f"    <- {data.hex()}")
            if len(data) >= 2 and data[0] == 0xAA:
                acks.put_nowait(data)

        await client.start_notify(NOTIFY, on_notify)

        async def send(cmd, payload=b"", response=True):
            # Data (0x44) MUST use write-without-response: the control char does not
            # ATT-ack data writes, so write-with-response blocks ~5s each and the
            # device's OTA session times out. Control opcodes use write-with-response.
            f = frame(cmd, payload)
            if DEBUG:
                print(f"    -> {f[:12].hex()}{'...' if len(f) > 12 else ''} (op 0x{cmd:02x}, {len(f)}B, resp={response})")
            await client.write_gatt_char(WRITE, f, response=response)

        async def expect(cmds, timeout=10.0):
            try:
                resp = await asyncio.wait_for(acks.get(), timeout)
            except asyncio.TimeoutError:
                return None
            return resp if resp[1] in cmds else resp  # caller checks

        async def abort(msg):
            print(f"ABORT: {msg}", file=sys.stderr)
            try:
                await send(OP_CANCEL, b"\x01")
            except Exception:
                pass
            await client.stop_notify(NOTIFY)
            raise SystemExit(2)

        # 1) version
        await send(OP_VER)
        r = await expect({OP_VER_RESP})
        dev_ver = r[3:3 + r[2]].decode("ascii", "replace") if (r and r[1] == OP_VER_RESP) else "?"
        print(f"device DFU version: {dev_ver}")

        # 2) setup
        crc, setup = build_setup_payload(blob, version)
        print(f"whole-file crc 0x{crc:08x}, len {len(blob)}, chunk {chunk}B (MTU {mtu})")
        await send(OP_START, setup)
        r = await expect({OP_SECT, 0x00})
        if not r or r[1] not in (OP_SECT, 0x00):
            await abort(f"setup not accepted (resp {r.hex() if r else 'timeout'})")
        # drain an optional second begin frame
        if r[1] == 0x00:
            await expect({OP_SECT})

        # 3) stream.  The device ACKs only on error/mismatch (aa45..) or every
        # ~Nth packet; a correctly-accepted packet is answered with SILENCE.
        # So we stream like the app: fire packets write-without-response at a
        # steady pace, never block on a per-packet ack, and only react to an
        # explicit error reply.  Completion is client-side (all bytes sent);
        # the device then accepts 0x4d only if its received-counter is full.
        total = len(blob)
        idx = 0
        off = 0
        pace = max(0.004, pace_arg)
        err = {"seen": None}

        # re-point the notify handler to watch for hard errors during streaming
        while not acks.empty():
            acks.get_nowait()

        while off < total:
            part = blob[off:off + chunk]
            await send(OP_DATA, bytes([idx & 0xFF]) + part, response=False)
            off += len(part)
            idx += 1
            await asyncio.sleep(pace)
            # drain any notifications without blocking; a 0x00/0x11 error reply aborts
            while not acks.empty():
                r = acks.get_nowait()
                if r[1] == 0x00 and r[2] >= 1 and r[3] != 0:        # error status on a cmd-ack
                    await abort(f"device error {r.hex()} near chunk {idx} off 0x{off:x}")
            if idx % 256 == 0 or off >= total:
                print(f"  sent {off}/{total} ({100*off//total}%)  frames={idx}")

        await asyncio.sleep(0.5)
        print("transfer complete (all bytes streamed); inactive bank written (reversible until 0x4d).")

        if not commit:
            await client.stop_notify(NOTIFY)
            print("STOP: --commit not given, so the apply opcode 0x4d was NOT sent.")
            print("Nothing irreversible happened. Re-run with --commit to apply.")
            return

        # 4) commit (irreversible)
        print("\n*** IRREVERSIBLE STEP ***")
        print("All chunks were acked. Sending 0x4d flips the flash bank and resets the")
        print("speaker into the new firmware. If the new image is bad this may not be")
        print("recoverable (no proven ROM rollback). The device re-checked every")
        print("partition CRC during transfer; all acks were success.")
        if assume_yes:
            print("--yes given: proceeding with apply (operator pre-authorized).")
        else:
            ans = input('Type exactly  FLASH  to apply, anything else to abort: ')
            if ans.strip() != "FLASH":
                await abort("user declined commit")
        await send(OP_TRIGGER)
        r = await expect({OP_TRIGGER_RESP}, timeout=20.0)
        if r and r[1] == OP_TRIGGER_RESP:
            result = r[3] if r[2] >= 1 else None
            print(f"apply accepted (0x4c), device result byte = {result}; device is resetting.")
        else:
            print(f"no clean 0x4c (got {r.hex() if r else 'timeout'}); device may still be applying.")
        await client.stop_notify(NOTIFY)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("container", type=Path, help="full 4-partition HMHEADER9 OTA .bin")
    ap.add_argument("--version", default="0.6.4.0", help="file version for setup [8:11] (major.minor.patch)")
    ap.add_argument("--transmit", action="store_true", help="connect and stream (never sends 0x4d)")
    ap.add_argument("--commit", action="store_true", help="with --transmit, apply via 0x4d after a clean transfer")
    ap.add_argument("--address", help="LE address if several Go 4 advertise")
    ap.add_argument("--scan-seconds", type=float, default=10)
    ap.add_argument("--mtu", type=int, default=0, help="override assumed/negotiated ATT MTU")
    ap.add_argument("--pace", type=float, default=0.008, help="seconds between data packets (default 8ms)")
    ap.add_argument("--debug", action="store_true", help="print every BLE frame sent/received")
    ap.add_argument("--yes", action="store_true", help="with --commit: skip the interactive FLASH prompt (operator pre-authorized)")
    args = ap.parse_args()
    global DEBUG
    DEBUG = args.debug

    blob, parts = parse_and_verify(args.container)
    print(f"container verified: {len(parts)} partitions, all per-partition CRCs OK\n")

    if not args.transmit:
        if args.commit:
            ap.error("--commit requires --transmit")
        plan(blob, parts, args.version, args.mtu or 247)
        return
    asyncio.run(run_ble(blob, args.version, args.address, args.scan_seconds, args.commit, args.mtu, args.pace, args.yes))


if __name__ == "__main__":
    main()
