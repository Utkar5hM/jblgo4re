#!/usr/bin/env python3
"""Offline build of usb-parity-v3 (stage0, in place, same-size).

v3 = v2 + a firmware VERSION-DISPLAY bump 0.6.4.0 -> 0.6.4.1 so the running
device reports the new version in the BLE 0x41->0x42 reply and via jblgo4.py info.

IMPORTANT (see README.md, "version-display chain"): the 0x42 version string is
NOT read from the OTA container at all. It is read from config property item
0x1a (a factory-provisioned, NON-OTA config/NVM store with no firmware writer
and not in the apply-time migration set). Bumping the container descriptor
"parameter" version therefore would NOT change the 0x42 reply. The only place in
the OTA that feeds the 0x42 reply is the stage0 formatter FUN_000565d0, which
turns item 0x1a (raw 0x2806) into the ASCII "v0.6.40" at RAM struct+0x40. We bump
the LAST build digit there, so FUN_00050286 emits aa 42 04 00 06 04 01.

All edits are applied to the STOCK stage0 image (same mechanics as v2).

EDIT1 @0x4f278 (v1): USB-start thunk also resends the stored EQ (adds bl 0x43184).
EDIT2 @0x4d686 (v1): boot-mode key filter whitelists 0xfxx (Vol+-), 0x600, 0xa01.
EDIT3 @0x4cd80 (v2): NOP the scanner-start gate branch (force button scanner on).
EDIT4 @0x56622 (v3): FUN_000565d0 last-digit formatter `adds r1,#0x30` ->
       `adds r1,#0x31`. The build digit r1 = item0x1a[hi]%10 = 0 on 0.6.4.0
       (confirmed live: aa 42 04 00 06 04 00), so r1 becomes '1' -> 0.6.4.1.
       Covered by the inner stage0 metadata go4crc (0x56622 < 0x5e39c), which we
       recompute. NOT a descriptor field, so the descriptor-table CRC16 at the
       container +0x1d4 is untouched.

Recomputes the inner metadata go4crc, repacks the full 4-partition container with
correct outer descriptor CRCs, then re-extracts to re-validate every outer CRC and
confirm only stage0 changed. Also byte-diffs the v3 container against the v2
container. Never transmits anything.
"""
import struct, sys, pathlib, tempfile, hashlib
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from extract_fw import go4_crc32, extract
import repack_fw

BASE = 0x40000
STAGE0 = ROOT / "captures/firmware0640/stage0_40000.bin"
CONTAINER = ROOT / "captures/Go4_ota_all0640.bin"
V2_CONTAINER = ROOT / "captures/patch-candidates/usb-parity-v2/Go4_ota_all0640_usbparity_v2.bin"
OUT = ROOT / "captures/patch-candidates/usb-parity-v3"

# ---- v1 EDIT1: EQ resend at USB start -------------------------------------
EDIT1_ADDR = 0x4f278
EDIT1_OLD  = bytes.fromhex("10b5" "0124" "2022" "2146" "0020" "00f045f9" "2046" "10bd" "0000")
EDIT1_NEW  = bytes.fromhex("10b5" "2022" "0121" "0020" "00f046f9" "f3f77eff" "0120" "10bd")

# ---- v1 EDIT2: boot-mode key filter whitelist -----------------------------
EDIT2_ADDR = 0x4d686
EDIT2_OLD  = bytes.fromhex("1748" "0021" "30f81120" "a242" "02d0" "491c" "0229" "f8d3" "0229" "17d0")
EDIT2_NEW  = bytes.fromhex("200a" "0f28" "07d0" "b4f5c06f" "04d0" "a4f60020" "0128" "18d1" "00bf")

# ---- v2 EDIT3: force scanner start (post msg 0x700) ------------------------
EDIT3_ADDR = 0x4cd80
EDIT3_OLD  = bytes.fromhex("08d0")   # beq 0x4cd94
EDIT3_NEW  = bytes.fromhex("00bf")   # nop

# ---- v3 EDIT4: version-display last-digit bump 0.6.4.0 -> 0.6.4.1 ----------
# 0x56622: adds r1,#0x30  (0x3130 LE "3031")  ->  adds r1,#0x31  (0x3131 LE "3131")
# r1 then = (item0x1a_hi % 10) + imm; stored to RAM struct+0x46 = 4th byte of 0x42.
EDIT4_ADDR = 0x56622
EDIT4_OLD  = bytes.fromhex("3031")
EDIT4_NEW  = bytes.fromhex("3131")

EDITS = [
    ("EDIT1", EDIT1_ADDR, EDIT1_OLD, EDIT1_NEW),
    ("EDIT2", EDIT2_ADDR, EDIT2_OLD, EDIT2_NEW),
    ("EDIT3", EDIT3_ADDR, EDIT3_OLD, EDIT3_NEW),
    ("EDIT4", EDIT4_ADDR, EDIT4_OLD, EDIT4_NEW),
]


def apply(buf, name, addr, old, new):
    off = addr - BASE
    assert len(old) == len(new), (name, addr, len(old), len(new))
    cur = bytes(buf[off:off + len(old)])
    if cur != old:
        raise SystemExit(f"{name} @{addr:#x}: expected {old.hex()} found {cur.hex()}")
    buf[off:off + len(new)] = new


def keystone_check():
    try:
        from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB
    except Exception as e:
        print(f"  keystone unavailable ({e}); relying on capstone disassembly")
        return
    ks = Ks(KS_ARCH_ARM, KS_MODE_THUMB)
    enc, _ = ks.asm("adds r1, #0x31", EDIT4_ADDR)
    asm_bytes = bytes(enc)
    assert asm_bytes == EDIT4_NEW, (asm_bytes.hex(), EDIT4_NEW.hex())
    print(f"  keystone: 'adds r1, #0x31' -> {asm_bytes.hex()} == EDIT4_NEW ok")


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
    keystone_check()

    img = bytearray(STAGE0.read_bytes())
    for name, addr, old, new in EDITS:
        apply(img, name, addr, old, new)

    code_len, old_crc = struct.unpack_from("<II", img, 0x1e39c)
    new_crc = go4_crc32(img[:code_len])
    struct.pack_into("<I", img, 0x1e3a0, new_crc)
    print(f"inner metadata CRC {old_crc:#010x} -> {new_crc:#010x} (go4crc over [0x40000:0x5e39c))")

    OUT.mkdir(parents=True, exist_ok=True)
    part = OUT / "stage0_patched.bin"
    part.write_bytes(img)
    assert len(img) == STAGE0.stat().st_size

    container = OUT / "Go4_ota_all0640_usbparity_v3.bin"
    repack_fw.repack(CONTAINER, 1, part, container)
    print(f"repacked -> {container}")

    # --- re-extract: validates all 4 outer partition CRCs (raises on any mismatch)
    rex = OUT / "extract"
    extract(container, rex)
    stock_rex = pathlib.Path(tempfile.mkdtemp()) / "stock"
    extract(CONTAINER, stock_rex)

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

    print("\npartition comparison (v3 vs stock):")
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

    # --- direct byte diff: v3 container vs v2 container ---
    print("\ncontainer byte diff (v3 vs v2):")
    v3 = container.read_bytes()
    v2 = V2_CONTAINER.read_bytes()
    assert len(v3) == len(v2), (len(v3), len(v2))
    cdiff = [i for i, (a, b) in enumerate(zip(v3, v2)) if a != b]
    for i in cdiff:
        print(f"  container 0x{i:06x}: {v2[i]:02x} -> {v3[i]:02x}")
    print(f"  total container bytes changed v2->v3: {len(cdiff)}")

    print("\ndisassembly of edited regions from re-extracted stage0:")
    disasm_check()

    md5 = hashlib.md5(v3).hexdigest()
    print(f"\nv3 container: {container}")
    print(f"  size: {len(v3)} bytes")
    print(f"  md5:  {md5}")


if __name__ == "__main__":
    main()
