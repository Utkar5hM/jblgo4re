#!/usr/bin/env python3
"""Offline build of usb-parity-v1 (stage0, in place, same-size).

EDIT1 @0x4f278: USB-start thunk also resends stored EQ (adds bl 0x43184).
EDIT2 @0x4d686: boot-mode key filter whitelists 0xfxx (Vol+-), 0x600, 0xa01.
Recomputes the inner metadata go4crc, then repacks a full 4-partition
container with correct outer descriptor CRCs. Never transmits anything.
"""
import struct, sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from extract_fw import go4_crc32
import repack_fw

BASE = 0x40000
STAGE0 = ROOT / "captures/firmware0640/stage0_40000.bin"
CONTAINER = ROOT / "captures/Go4_ota_all0640.bin"
OUT = ROOT / "captures/patch-candidates/usb-parity-v1"

EDIT1_ADDR = 0x4f278
EDIT1_OLD  = bytes.fromhex("10b5" "0124" "2022" "2146" "0020" "00f045f9" "2046" "10bd" "0000")
EDIT1_NEW  = bytes.fromhex("10b5" "2022" "0121" "0020" "00f046f9" "f3f77eff" "0120" "10bd")

EDIT2_ADDR = 0x4d686
EDIT2_OLD  = bytes.fromhex("1748" "0021" "30f81120" "a242" "02d0" "491c" "0229" "f8d3" "0229" "17d0")
EDIT2_NEW  = bytes.fromhex("200a" "0f28" "07d0" "b4f5c06f" "04d0" "a4f60020" "0128" "18d1" "00bf")

def apply(buf, addr, old, new):
    off = addr - BASE
    assert len(old) == len(new), (addr, len(old), len(new))
    cur = bytes(buf[off:off+len(old)])
    if cur != old:
        raise SystemExit(f"@{addr:#x}: expected {old.hex()} found {cur.hex()}")
    buf[off:off+len(new)] = new

def main():
    img = bytearray(STAGE0.read_bytes())
    apply(img, EDIT1_ADDR, EDIT1_OLD, EDIT1_NEW)
    apply(img, EDIT2_ADDR, EDIT2_OLD, EDIT2_NEW)
    # recompute inner metadata CRC over [0:code_len]
    code_len, old_crc = struct.unpack_from("<II", img, 0x1e39c)
    new_crc = go4_crc32(img[:code_len])
    struct.pack_into("<I", img, 0x1e3a0, new_crc)
    print(f"inner metadata CRC {old_crc:#010x} -> {new_crc:#010x}")
    OUT.mkdir(parents=True, exist_ok=True)
    part = OUT / "stage0_patched.bin"
    part.write_bytes(img)
    assert len(img) == STAGE0.stat().st_size
    repack_fw.repack(CONTAINER, 1, part, OUT / "Go4_ota_all0640_usbparity.bin")

if __name__ == "__main__":
    main()
