#!/usr/bin/env python3
"""Offline build of usb-parity-v2 (stage0, in place, same-size).

Layered on usb-parity-v1. All edits are applied to the STOCK stage0 image.

EDIT1 @0x4f278 (v1): USB-start thunk also resends the stored EQ (adds bl 0x43184).
EDIT2 @0x4d686 (v1): boot-mode key filter whitelists 0xfxx (Vol+-), 0x600, 0xa01.
EDIT3 @0x4cd80 (v2): NOP the scanner-start gate branch so msg 0x700 (scan start)
       is posted unconditionally. In service mode (chord-initiated reboot, power
       key not held at boot) the gate byte [0x200010b8+9] reads 0, so the stock
       code never starts the button scanner and no Vol+- events are ever produced.

Recomputes the inner metadata go4crc, repacks the full 4-partition container with
correct outer descriptor CRCs, then re-extracts to re-validate every outer CRC and
confirm only stage0 changed. Never transmits anything.
"""
import struct, sys, pathlib, tempfile, hashlib
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from extract_fw import go4_crc32, extract
import repack_fw

BASE = 0x40000
STAGE0 = ROOT / "captures/firmware0640/stage0_40000.bin"
CONTAINER = ROOT / "captures/Go4_ota_all0640.bin"
OUT = ROOT / "captures/patch-candidates/usb-parity-v2"

# ---- v1 EDIT1: EQ resend at USB start -------------------------------------
EDIT1_ADDR = 0x4f278
EDIT1_OLD  = bytes.fromhex("10b5" "0124" "2022" "2146" "0020" "00f045f9" "2046" "10bd" "0000")
EDIT1_NEW  = bytes.fromhex("10b5" "2022" "0121" "0020" "00f046f9" "f3f77eff" "0120" "10bd")

# ---- v1 EDIT2: boot-mode key filter whitelist -----------------------------
EDIT2_ADDR = 0x4d686
EDIT2_OLD  = bytes.fromhex("1748" "0021" "30f81120" "a242" "02d0" "491c" "0229" "f8d3" "0229" "17d0")
EDIT2_NEW  = bytes.fromhex("200a" "0f28" "07d0" "b4f5c06f" "04d0" "a4f60020" "0128" "18d1" "00bf")

# ---- v2 EDIT3: force scanner start (post msg 0x700) ------------------------
# 0x4cd7e cmp r0,#0 ; 0x4cd80 beq 0x4cd94 (skip post if gate byte == 0)
# NOP the beq so the 0x700 post at 0x4cd82 is always reached.
EDIT3_ADDR = 0x4cd80
EDIT3_OLD  = bytes.fromhex("08d0")   # beq 0x4cd94
EDIT3_NEW  = bytes.fromhex("00bf")   # nop

EDITS = [
    ("EDIT1", EDIT1_ADDR, EDIT1_OLD, EDIT1_NEW),
    ("EDIT2", EDIT2_ADDR, EDIT2_OLD, EDIT2_NEW),
    ("EDIT3", EDIT3_ADDR, EDIT3_OLD, EDIT3_NEW),
]


def apply(buf, name, addr, old, new):
    off = addr - BASE
    assert len(old) == len(new), (name, addr, len(old), len(new))
    cur = bytes(buf[off:off + len(old)])
    if cur != old:
        raise SystemExit(f"{name} @{addr:#x}: expected {old.hex()} found {cur.hex()}")
    buf[off:off + len(new)] = new


def disasm_check():
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    data = (OUT / "stage0.bin").read_bytes()  # re-extracted stage0
    for name, addr, old, new in EDITS:
        code = data[addr - BASE: addr - BASE + len(new)]
        assert code == new, (name, code.hex(), new.hex())
        print(f"  {name} @{addr:#x}:")
        for ins in md.disasm(code, addr):
            print(f"    {ins.address:#07x}  {ins.bytes.hex():<10} {ins.mnemonic} {ins.op_str}")


def main():
    img = bytearray(STAGE0.read_bytes())
    for name, addr, old, new in EDITS:
        apply(img, name, addr, old, new)

    code_len, old_crc = struct.unpack_from("<II", img, 0x1e39c)
    new_crc = go4_crc32(img[:code_len])
    struct.pack_into("<I", img, 0x1e3a0, new_crc)
    print(f"inner metadata CRC {old_crc:#010x} -> {new_crc:#010x}")

    OUT.mkdir(parents=True, exist_ok=True)
    part = OUT / "stage0_patched.bin"
    part.write_bytes(img)
    assert len(img) == STAGE0.stat().st_size

    container = OUT / "Go4_ota_all0640_usbparity_v2.bin"
    repack_fw.repack(CONTAINER, 1, part, container)
    print(f"repacked -> {container}")

    # --- re-extract: validates all 4 outer partition CRCs (raises on any mismatch)
    rex = OUT / "extract"
    extract(container, rex)
    stock_rex = pathlib.Path(tempfile.mkdtemp()) / "stock"
    extract(CONTAINER, stock_rex)

    # map names -> files for both
    import json
    new_man = json.loads((rex / "manifest.json").read_text())
    (OUT / "stage0.bin").write_bytes((rex / f"{new_man['partitions'][0]['name']}.bin").read_bytes())

    # expected differing offsets in stage0: each edit's changed bytes + 4-byte inner CRC
    expected = set()
    for name, addr, old, new in EDITS:
        for i in range(len(new)):
            if old[i] != new[i]:
                expected.add(addr - BASE + i)
    for i in range(4):
        expected.add(0x1e3a0 + i)

    print("partition comparison (patched vs stock):")
    for p in new_man["partitions"]:
        nf = rex / f"{p['name']}.bin"
        sf = stock_rex / f"{p['name']}.bin"
        nb, sb = nf.read_bytes(), sf.read_bytes()
        diff_off = {i for i, (a, b) in enumerate(zip(nb, sb)) if a != b}
        if p["partition_id"] == 1:
            unexpected = diff_off - expected
            print(f"  {p['name']} (id 1): {len(diff_off)} byte(s) differ; "
                  f"expected {len(expected)}; unexpected {sorted(hex(x) for x in unexpected)}")
            assert not unexpected and diff_off == expected, (sorted(diff_off), sorted(expected))
        else:
            same = hashlib.sha256(nb).hexdigest() == hashlib.sha256(sb).hexdigest()
            print(f"  {p['name']} (id {p['partition_id']}): {'IDENTICAL' if same else 'CHANGED!'}")
            assert same, p["name"]

    print("\ndisassembly of edited regions from re-extracted stage0:")
    disasm_check()


if __name__ == "__main__":
    main()
