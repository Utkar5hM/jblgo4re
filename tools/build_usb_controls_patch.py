#!/usr/bin/env python3
"""Build an offline 0.6.4.0 stage0 USB EQ/key-report patch candidate.

This changes only the extracted stage0 image. It does not contact a device.
The source image hash, hook bytes, and erased tail cave are pinned so the
patch cannot silently apply to a different firmware build.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct


LOAD_ADDRESS = 0x40000
EXPECTED_SIZE = 0x1E400
EXPECTED_SHA256 = "0d7b8f82fa37732367a77f46af607297abfd06197f502d5b23e420a96fcd8750"

USB_MODE_HOOK = 0x4F278
USB_MODE_EXPECTED = bytes.fromhex("10 b5 01 24")
KEY_REPORT_HOOK = 0x4D6FC
KEY_REPORT_EXPECTED = bytes.fromhex("70 b5 05 46")

# The final 60 bytes of the stage0 partition are erased padding. Preserve the
# final four bytes, which are non-erased image data immediately after the cave.
CAVE = 0x5E3C0
CAVE_SIZE = 60

EQ_SENDER = 0x43184
VOLUME_SENDER = 0x4F510
KEY_GATE = 0x52610
USB_MODE_GETTER = 0x4F4D2
KEY_EVENT_POST = 0x4D6E8


def _halfwords(*values: int) -> bytes:
    return struct.pack("<" + "H" * len(values), *values)


def encode_thumb_branch(src: int, dst: int, *, link: bool) -> bytes:
    """Encode a Thumb-2 B.W or BL from even code addresses."""
    offset = dst - (src + 4)
    if offset & 1 or not -(1 << 24) <= offset < (1 << 24):
        raise ValueError(f"branch out of range or unaligned: {src:#x}->{dst:#x}")
    s = (offset >> 24) & 1
    i1 = (offset >> 23) & 1
    i2 = (offset >> 22) & 1
    imm10 = (offset >> 12) & 0x3FF
    imm11 = (offset >> 1) & 0x7FF
    j1 = (~(i1 ^ s)) & 1
    j2 = (~(i2 ^ s)) & 1
    first = 0xF000 | (s << 10) | imm10
    second = (0xD000 if link else 0x9000) | (j1 << 13) | (j2 << 11) | imm11
    return _halfwords(first, second)


def decode_thumb_branch(src: int, encoded: bytes) -> int:
    """Decode a wide Thumb branch to verify generated hook/call targets."""
    first, second = struct.unpack("<HH", encoded)
    s = (first >> 10) & 1
    j1 = (second >> 13) & 1
    j2 = (second >> 11) & 1
    i1 = (~(j1 ^ s)) & 1
    i2 = (~(j2 ^ s)) & 1
    immediate = (
        (s << 24) | (i1 << 23) | (i2 << 22) |
        ((first & 0x3FF) << 12) | ((second & 0x7FF) << 1)
    )
    if immediate & (1 << 24):
        immediate -= 1 << 25
    return src + 4 + immediate


def off(address: int) -> int:
    if address < LOAD_ADDRESS:
        raise ValueError(f"address below stage0 load address: {address:#x}")
    return address - LOAD_ADDRESS


def build(source: bytes) -> tuple[bytes, dict[str, object]]:
    if len(source) != EXPECTED_SIZE:
        raise ValueError(f"expected {EXPECTED_SIZE:#x}-byte stage0, got {len(source):#x}")
    source_hash = hashlib.sha256(source).hexdigest()
    if source_hash != EXPECTED_SHA256:
        raise ValueError(f"unexpected stage0 SHA-256: {source_hash}")
    if source[off(USB_MODE_HOOK):off(USB_MODE_HOOK) + 4] != USB_MODE_EXPECTED:
        raise ValueError("USB-mode hook bytes do not match the analyzed 0.6.4.0 image")
    if source[off(KEY_REPORT_HOOK):off(KEY_REPORT_HOOK) + 4] != KEY_REPORT_EXPECTED:
        raise ValueError("key-report hook bytes do not match the analyzed 0.6.4.0 image")
    cave_start = off(CAVE)
    cave_end = cave_start + CAVE_SIZE
    if source[cave_start:cave_end] != b"\xff" * CAVE_SIZE:
        raise ValueError("reserved stage0 tail cave is no longer entirely erased")

    # USB start keeps the stock level setup, then re-sends the current profile
    # via the already-created configuration channel (ID 0x0a).
    eq_stub = bytearray()
    eq_stub += _halfwords(0xB510, 0x2401, 0x2220, 0x4621, 0x2000)
    eq_stub += encode_thumb_branch(CAVE + len(eq_stub), VOLUME_SENDER, link=True)
    eq_stub += encode_thumb_branch(CAVE + len(eq_stub), EQ_SENDER, link=True)
    eq_stub += _halfwords(0x4620, 0xBD10)

    # Keep the diagnostic gate available, but also forward physical key masks
    # while USB mode getter 0x4f4d2 reports its established active value 2.
    key_stub_address = CAVE + len(eq_stub)
    key_stub = bytearray()
    key_stub += _halfwords(0xB530, 0x4604, 0x460D)
    key_stub += encode_thumb_branch(key_stub_address + len(key_stub), KEY_GATE, link=True)
    key_stub += _halfwords(0x2800, 0xD103)
    key_stub += encode_thumb_branch(key_stub_address + len(key_stub), USB_MODE_GETTER, link=True)
    key_stub += _halfwords(0x2802, 0xD105, 0x2201, 0x4620, 0x4629)
    key_stub += encode_thumb_branch(key_stub_address + len(key_stub), KEY_EVENT_POST, link=True)
    key_stub += _halfwords(0x2001, 0xBD30)

    payload = eq_stub + key_stub
    if len(payload) > CAVE_SIZE:
        raise ValueError(f"patch payload ({len(payload)} bytes) exceeds cave ({CAVE_SIZE})")

    result = bytearray(source)
    result[off(USB_MODE_HOOK):off(USB_MODE_HOOK) + 4] = encode_thumb_branch(
        USB_MODE_HOOK, CAVE, link=False
    )
    result[off(KEY_REPORT_HOOK):off(KEY_REPORT_HOOK) + 4] = encode_thumb_branch(
        KEY_REPORT_HOOK, key_stub_address, link=False
    )
    result[cave_start:cave_start + len(payload)] = payload

    expected_branches = (
        (USB_MODE_HOOK, result[off(USB_MODE_HOOK):off(USB_MODE_HOOK) + 4], CAVE),
        (KEY_REPORT_HOOK, result[off(KEY_REPORT_HOOK):off(KEY_REPORT_HOOK) + 4], key_stub_address),
        (CAVE + 10, payload[10:14], VOLUME_SENDER),
        (CAVE + 14, payload[14:18], EQ_SENDER),
        (key_stub_address + 6, payload[len(eq_stub) + 6:len(eq_stub) + 10], KEY_GATE),
        (key_stub_address + 14, payload[len(eq_stub) + 14:len(eq_stub) + 18], USB_MODE_GETTER),
        (key_stub_address + 28, payload[len(eq_stub) + 28:len(eq_stub) + 32], KEY_EVENT_POST),
    )
    for src, encoded, target in expected_branches:
        if decode_thumb_branch(src, encoded) != target:
            raise ValueError(f"bad Thumb branch encoding at {src:#x}")

    manifest: dict[str, object] = {
        "status": "offline exploratory candidate; not runtime validated; not for flashing",
        "source_sha256": source_hash,
        "patched_sha256": hashlib.sha256(result).hexdigest(),
        "load_address": hex(LOAD_ADDRESS),
        "hooks": [
            {
                "address": hex(USB_MODE_HOOK),
                "old": USB_MODE_EXPECTED.hex(" "),
                "new": result[off(USB_MODE_HOOK):off(USB_MODE_HOOK) + 4].hex(" "),
                "behavior": "preserve DSP volume-level setup; then resend stored EQ profile",
            },
            {
                "address": hex(KEY_REPORT_HOOK),
                "old": KEY_REPORT_EXPECTED.hex(" "),
                "new": result[off(KEY_REPORT_HOOK):off(KEY_REPORT_HOOK) + 4].hex(" "),
                "behavior": "forward diagnostic key events when the USB-mode getter is 2",
            },
        ],
        "cave": {
            "address": hex(CAVE),
            "capacity": CAVE_SIZE,
            "used": len(payload),
            "eq_stub_bytes": len(eq_stub),
            "key_stub_address": hex(key_stub_address),
            "key_stub_bytes": len(key_stub),
            "code_hex": payload.hex(" "),
        },
        "unresolved": [
            "Whether the channel-0x0a profile command changes the USB PCM DSP path.",
            "Whether diagnostic CDC key reports are emitted in active USB mode on hardware.",
            "Which raw key masks correspond to Vol+, Vol-, and Play on this unit.",
            "No recovery path or live OTA acceptance is established.",
            "The powered-USB shutdown path is not changed; battery cutoffs remain intact.",
        ],
    }
    return bytes(result), manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="extracted stage0_40000.bin")
    parser.add_argument("output", type=Path, help="write candidate stage0 image here")
    parser.add_argument("--manifest", type=Path, help="optional JSON patch manifest")
    args = parser.parse_args()

    patched, manifest = build(args.source.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(patched)
    encoded_manifest = json.dumps(manifest, indent=2) + "\n"
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(encoded_manifest)
    print(encoded_manifest, end="")
    print(f"wrote offline candidate: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
