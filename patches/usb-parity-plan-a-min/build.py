#!/usr/bin/env python3
"""Offline build of usb-parity-plan-a-min (stage0, STOCK base).

Plan A' (MINIMAL / "test the core"): make a NORMAL boot (byte0 != 2) bring up
USB audio when a cable is plugged, so USB audio runs through the normal DSP/EQ
chain with the physical buttons live (buttons.md round 6: the main Vol+- gate is
HFP call state, not service mode; byte0 never reaches main).

HARD SAFETY (Q5: no ROM dump, no host bank-rollback => a non-booting stage0 is a
brick). Our only recovery is the "no-USB-boot window": a boot with NO cable must
behave byte-for-byte like stock so BLE/OTA stays alive and we can re-flash to
revert. Every changed byte below is therefore either (a) on a USB-only path
(plug handler / USB-start thunk) or (b) a value-only change that can't alter
control flow (version digit). None is on the reset/scatter-load/BLE-init path.

Edits:
  HOOK  @0x59428 : in the USB plug path of FUN_000593bc, replace
                   `mov.w r0,#0xc00` with `bl CAVE`. CAVE (if byte0!=2) posts
                   event 0x806 (USB audio setup, router 0x4f7c8 -> 0x4fdc4), then
                   restores r0/r1/r2 and returns so the original 0xc00 plug event
                   is still posted by the untouched tail-call at 0x59470.
                   Runs ONLY on a cable state-change (handler early-returns at
                   0x593cc otherwise), never on a no-USB boot.
  CAVE  @0x5e3b8 : 32 bytes placed in the 68-byte 0xFF erased-flash pad in the
                   stage0 tail (0x5e3b8..0x5e3fb). XIP flash => executable
                   (resetPC 0x40071). OUTSIDE the inner metadata CRC
                   [0x40000:0x5e39c) (so the inner CRC is unaffected by it), but
                   INSIDE the partition so the outer per-partition go4 CRC (which
                   repack recomputes) covers it. Reached only via HOOK = USB-only.
  EDIT1 @0x4f278 : v1 verbatim -- USB-start thunk also resends the stored EQ
                   (bl 0x43184) so USB audio isn't the default-preset "raw" sound.
                   Runs only at USB start.
  EDIT4 @0x56622 : version-display last digit `adds r1,#0x30` -> `adds r1,#0x32`
                   => device reports 0.6.4.2 (distinct from stock 0 / v3 1), a
                   value-only change = proof-of-apply via `jblgo4.py info`.

Recomputes the inner metadata go4 CRC over [0x40000:0x5e39c) (covers HOOK/EDIT1/
EDIT4; the CAVE is after it), repacks the 4-partition container (outer CRCs), then
re-extracts to re-validate every outer CRC and confirm only stage0 changed.
Never transmits anything.
"""
import struct, sys, pathlib, tempfile, hashlib, json
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from extract_fw import go4_crc32, extract
import repack_fw

BASE = 0x40000
STAGE0 = ROOT / "captures/firmware0640/stage0_40000.bin"
CONTAINER = ROOT / "captures/Go4_ota_all0640.bin"
OUT = ROOT / "captures/patch-candidates/usb-parity-plan-a-min"

# ---- HOOK: plug path posts 0x806 (USB audio) on normal boot ----------------
HOOK_ADDR = 0x59428
HOOK_OLD  = bytes.fromhex("4ff44060")   # mov.w r0,#0xc00
HOOK_NEW  = bytes.fromhex("04f0c6ff")   # bl 0x5e3b8  (keystone-verified)

# ---- CAVE: in the 0xFF tail pad (outside inner CRC) ------------------------
CAVE_ADDR = 0x5e3b8
CAVE_OLD  = b"\xff" * 32
# push{lr}; bl 0x59a14; cmp r0,#2; beq 0x5e3ce; movs r1,#0; movs r2,#0;
# movw r0,#0x806; bl 0x51ff8; movs r1,#0; movs r2,#0; movw r0,#0xc00; pop{pc}
CAVE_NEW  = bytes.fromhex("00b5fbf72bfb022805d00021002240f60600f3f715fe0021002240f6004000bd")

# ---- EDIT1 (v1): EQ resend at USB start ------------------------------------
EDIT1_ADDR = 0x4f278
EDIT1_OLD  = bytes.fromhex("10b5" "0124" "2022" "2146" "0020" "00f045f9" "2046" "10bd" "0000")
EDIT1_NEW  = bytes.fromhex("10b5" "2022" "0121" "0020" "00f046f9" "f3f77eff" "0120" "10bd")

# ---- EDIT4: version-display bump 0.6.4.0 -> 0.6.4.2 ------------------------
EDIT4_ADDR = 0x56622
EDIT4_OLD  = bytes.fromhex("3031")   # adds r1,#0x30
EDIT4_NEW  = bytes.fromhex("3231")   # adds r1,#0x32

EDITS = [
    ("HOOK",  HOOK_ADDR,  HOOK_OLD,  HOOK_NEW),
    ("CAVE",  CAVE_ADDR,  CAVE_OLD,  CAVE_NEW),
    ("EDIT1", EDIT1_ADDR, EDIT1_OLD, EDIT1_NEW),
    ("EDIT4", EDIT4_ADDR, EDIT4_OLD, EDIT4_NEW),
]
INNER_CRC_LEN_OFF = 0x1e39c   # <I> code_len
INNER_CRC_OFF     = 0x1e3a0   # <I> crc


def apply(buf, name, addr, old, new):
    off = addr - BASE
    assert len(old) == len(new), (name, len(old), len(new))
    cur = bytes(buf[off:off + len(old)])
    if cur != old:
        raise SystemExit(f"{name} @{addr:#x}: expected {old.hex()} found {cur.hex()}")
    buf[off:off + len(new)] = new


def main():
    img = bytearray(STAGE0.read_bytes())
    for name, addr, old, new in EDITS:
        apply(img, name, addr, old, new)

    code_len, old_crc = struct.unpack_from("<II", img, INNER_CRC_LEN_OFF)
    assert code_len == 0x1e39c, hex(code_len)
    assert (CAVE_ADDR - BASE) >= code_len, "cave must be outside the inner CRC range"
    new_crc = go4_crc32(img[:code_len])
    struct.pack_into("<I", img, INNER_CRC_OFF, new_crc)
    print(f"inner metadata CRC {old_crc:#010x} -> {new_crc:#010x} (go4crc over [0x40000:0x5e39c))")

    OUT.mkdir(parents=True, exist_ok=True)
    part = OUT / "stage0_patched.bin"
    part.write_bytes(img)
    assert len(img) == STAGE0.stat().st_size

    container = OUT / "Go4_ota_all0640_plan_a_min.bin"
    repack_fw.repack(CONTAINER, 1, part, container)
    print(f"repacked -> {container}")

    rex = OUT / "extract"
    extract(container, rex)                       # validates all 4 outer CRCs
    stock_rex = pathlib.Path(tempfile.mkdtemp()) / "stock"
    extract(CONTAINER, stock_rex)

    new_man = json.loads((rex / "manifest.json").read_text())
    (OUT / "stage0.bin").write_bytes((rex / f"{new_man['partitions'][0]['name']}.bin").read_bytes())

    expected = set()
    for name, addr, old, new in EDITS:
        for i in range(len(new)):
            if old[i] != new[i]:
                expected.add(addr - BASE + i)
    for i in range(4):
        expected.add(INNER_CRC_OFF + i)

    print("\npartition comparison (plan-a-min vs stock):")
    for p in new_man["partitions"]:
        nb = (rex / f"{p['name']}.bin").read_bytes()
        sb = (stock_rex / f"{p['name']}.bin").read_bytes()
        diff_off = {i for i, (a, b) in enumerate(zip(nb, sb)) if a != b}
        if p["partition_id"] == 1:
            unexpected = diff_off - expected
            print(f"  {p['name']} (id 1): {len(diff_off)} differ; expected {len(expected)}; "
                  f"unexpected {sorted(hex(x) for x in unexpected)}")
            assert not unexpected and diff_off == expected, (sorted(map(hex, diff_off)), sorted(map(hex, expected)))
        else:
            same = hashlib.sha256(nb).hexdigest() == hashlib.sha256(sb).hexdigest()
            print(f"  {p['name']} (id {p['partition_id']}): {'IDENTICAL' if same else 'CHANGED!'}")
            assert same, p["name"]

    print("\ndisassembly of edits from re-extracted stage0:")
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    data = (OUT / "stage0.bin").read_bytes()
    for name, addr, old, new in EDITS:
        code = data[addr - BASE: addr - BASE + len(new)]
        assert code == new, (name, code.hex(), new.hex())
        print(f"  {name} @{addr:#x}:")
        for ins in md.disasm(code, addr):
            print(f"    {ins.address:#07x}  {ins.bytes.hex():<10} {ins.mnemonic} {ins.op_str}")

    blob = container.read_bytes()
    md5 = hashlib.md5(blob).hexdigest()
    cfg = {"version": "0.6.4.2", "targetPID": "20e4", "md5": md5,
           "binUrl": "local/Go4_ota_all0640_plan_a_min.bin",
           "note": "LOCAL experimental build usb-parity-plan-a-min. NOT an official Harman image."}
    (OUT / "Go4_ota_all0640_plan_a_min.bin.json").write_text(json.dumps(cfg, indent=2))

    print(f"\ncontainer: {container}\n  size: {len(blob)}\n  md5:  {md5}")
    print(f"  wrote config json (version 0.6.4.2) alongside")


if __name__ == "__main__":
    main()
