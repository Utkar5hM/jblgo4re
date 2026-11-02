#!/usr/bin/env python3
"""Offline build of usb-parity-hid (stage0, STOCK base + plan-a-min + HID).

GOAL: present a USB HID Consumer-Control interface so the physical Vol+/Vol-
buttons move the HOST PC's system volume (Volume Increment 0x00E9 / Volume
Decrement 0x00EA). Approach B: REPURPOSE the existing CDC interface (interfaces
2/3) into a single HID interface (interface 2), reusing EP 0x83 as the HID
interrupt-IN endpoint. CDC is confirmed dead on this unit, so it is dropped.

Play/Pause (0x00CD) is present in the report descriptor for completeness but is
NEVER sourced: 0x22/0x23 are main-partition events invisible to stage0. No main
changes are made.

BASE = STOCK stage0; this script re-applies plan-a-min's edits (normal-boot USB
enumeration + running scanner, both REQUIRED for HID to ever send a report),
then layers the HID edits, so the build is fully reproducible from the stock
image. plan-a-min EDIT4 (version digit) is bumped to 0.6.4.3 as proof-of-apply.

HARD SAFETY (Q5 recovery window): a boot with NO USB cable must be byte-for-byte
stock behaviour so BLE/OTA stays alive and we can always re-flash. Every changed
byte is on a USB-enumeration path (the descriptor blob, the USB std/HID request
handler) or a USB-event path (the Vol+- router, which also runs in BT mode but
there safely no-ops -- see below) or value-only (version digit, inner CRC). None
is on reset / scatter-load / BLE-init.

NO CDC CODE IS OVERWRITTEN. The HID logic fits without reclaiming CDC code:
  * report descriptor serving is an IN-PLACE patch of the std-interface handler
    0x5ac08 (GET_DESCRIPTOR type 0x22) -> hardcoded flash pointer+length;
  * the report descriptor bytes live in the 34 bytes freed INSIDE the config
    blob by shrinking CDC(59B)->HID(25B) (wrapped in one bLength-valid filler
    descriptor so the descriptor chain still walks to the string descriptors);
  * the send+routing cave fits in the stage0 tail 0xFF pad after plan-a-min.
The dead CDC code (AT parser / App USB Transmit task / transmit frame builder)
is simply left unreferenced by the new descriptor (no EP 0x04 OUT exists for the
host to feed, so the parser task blocks forever on empty input exactly as it
already does on this unit -- confirmed CDC-dead). Nothing dispatches into any
removed bytes because no bytes are removed.

Edits (all asserted against the STOCK image):
  --- plan-a-min base (verbatim, except EDIT4 digit) ---
  HOOK  @0x59428 : mov.w r0,#0xc00 -> bl 0x5e3b8 (plan-a-min USB-plug hook)
  CAVE0 @0x5e3b8 : 32B plan-a-min cave (post 0x806 on normal-boot plug)
  EDIT1 @0x4f278 : USB-start thunk also resends stored EQ (bl 0x43184)
  EDIT4 @0x56622 : adds r1,#0x30 -> #0x33  => reports 0.6.4.3 (proof-of-apply)
  --- HID (new) ---
  DESC  @0x5db34 : CDC block (59B) -> HID interface(9)+HID desc(9)+int-IN EP(7)
                   + filler(2) + 27B report descriptor + 5B pad (bLength chain
                   preserved to the strings at 0x5db6f).
  DTOT  @0x5dac0 : config wTotalLength 0x00b1 -> 0x008f
  DNIF  @0x5dac2 : config bNumInterfaces 4 -> 3
  RPTR  @0x5ac94 : std-if handler literal 0x20000558 -> 0x5db4f (&report desc)
  RGET  @0x5ac58 : std-if GET_DESCRIPTOR(0x22) body -> return (&report desc, 27)
  RHOOK @0x4f8d6 : Vol+- router bl 0x4f510 -> bl 0x5e3d8 (HID-send cave)
  CAVE1 @0x5e3d8 : 35B cave: call 0x4f510 (speaker step, keeps BT behaviour),
                   then send a 1-byte HID key-down then key-up on EP 0x83 via
                   0x5a298 (submit+wait). In BT/no-USB: 0x5a298 returns -5
                   (CDC-active flag 0x20000598[0]==0 because no SET_CONFIGURATION
                   ran), so the send is a harmless instant no-op and only the
                   speaker step happens -> BT Vol+- identical to stock.

Recomputes the inner metadata go4 CRC over [0x40000:0x5e39c) and repacks a full
4-partition container (outer CRCs recomputed by repack). Never transmits.
"""
import struct, sys, pathlib, tempfile, hashlib, json
ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from extract_fw import go4_crc32, extract
import repack_fw

BASE = 0x40000
STAGE0 = ROOT / "captures/firmware0640/stage0_40000.bin"
CONTAINER = ROOT / "captures/Go4_ota_all0640.bin"
OUT = ROOT / "captures/patch-candidates/usb-parity-hid-winfix"

# ---------------- plan-a-min base edits (stock base) ------------------------
HOOK_ADDR = 0x59428
HOOK_OLD  = bytes.fromhex("4ff44060")   # mov.w r0,#0xc00
HOOK_NEW  = bytes.fromhex("04f0c6ff")   # bl 0x5e3b8

CAVE0_ADDR = 0x5e3b8
CAVE0_OLD  = b"\xff" * 32
CAVE0_NEW  = bytes.fromhex("00b5fbf72bfb022805d00021002240f60600f3f715fe0021002240f6004000bd")

EDIT1_ADDR = 0x4f278
EDIT1_OLD  = bytes.fromhex("10b5" "0124" "2022" "2146" "0020" "00f045f9" "2046" "10bd" "0000")
EDIT1_NEW  = bytes.fromhex("10b5" "2022" "0121" "0020" "00f046f9" "f3f77eff" "0120" "10bd")

EDIT4_ADDR = 0x56622
EDIT4_OLD  = bytes.fromhex("3031")   # adds r1,#0x30  (stock version digit '0')
EDIT4_NEW  = bytes.fromhex("3431")   # adds r1,#0x34  => reports 0.6.4.4

# ---------------- Windows cache-bust: bump bcdDevice -------------------------
# Windows caches descriptors per VID/PID/bcdDevice. Our bb91/0x0001 is cached as
# a FAILED "Device Descriptor Request Failed" (same id as stock service mode).
# Bumping bcdDevice makes Windows treat it as a new device and re-read fresh.
# device desc @0x5daac; bcdDevice is 2 bytes LE at +0x0c = 0x5dab8. Value-only,
# zero control-flow / zero behaviour impact on Linux/BT. (Opus 5.5 verdict.)
BCDDEV_ADDR = 0x5dab8
BCDDEV_OLD  = bytes.fromhex("0100")   # bcdDevice 0x0001
BCDDEV_NEW  = bytes.fromhex("0200")   # bcdDevice 0x0002

# ---------------- HID descriptor edits --------------------------------------
# New config descriptor tail: replace the 59-byte CDC block at 0x5db34.
#   HID interface (if 2, 1 EP, class 0x03)      09 04 02 00 01 03 00 00 00
#   HID descriptor (bcdHID 1.11, report len 27) 09 21 11 01 00 01 22 1b 00
#   EP 0x83 interrupt IN, 8B, 10ms              07 05 83 03 08 00 0a
#   filler descriptor header (bLength 34)       22 ff
#   HID report descriptor (27 bytes)            05 0c ... c0
#   5 pad bytes (inside the filler)             ff ff ff ff ff
REPORT_DESC = bytes.fromhex(
    "050c"      # Usage Page (Consumer)
    "0901"      # Usage (Consumer Control)
    "a101"      # Collection (Application)
    "1500"      # Logical Minimum (0)
    "2501"      # Logical Maximum (1)
    "7501"      # Report Size (1)
    "9503"      # Report Count (3)
    "09e9"      # Usage (Volume Increment)
    "09ea"      # Usage (Volume Decrement)
    "09cd"      # Usage (Play/Pause)  -- present, never sourced by stage0
    "8102"      # Input (Data,Var,Abs)
    "9505"      # Report Count (5)
    "8101"      # Input (Const,Array,Abs) -- 5-bit pad
    "c0"        # End Collection
)
assert len(REPORT_DESC) == 27, len(REPORT_DESC)
REPORT_DESC_ADDR = 0x5db4f                  # must match literal written at RPTR

DESC_ADDR = 0x5db34
DESC_OLD  = bytes.fromhex(
    "080b02020202010009040200000202010005240010010524010003042402020524060203"
    "09040300020a0000000705040240000007058302400000")
DESC_NEW  = (bytes.fromhex("090402000103000000")        # HID interface
             + bytes.fromhex("092111010001221b00")       # HID descriptor (len 27)
             + bytes.fromhex("0705830308000a")            # EP 0x83 int IN
             + bytes.fromhex("22ff")                      # filler header (bLength 34)
             + REPORT_DESC                                # report descriptor @ 0x5db4f
             + b"\xff" * 5)                               # pad to fill filler
assert len(DESC_NEW) == len(DESC_OLD) == 59, (len(DESC_NEW), len(DESC_OLD))
assert DESC_ADDR + 9 + 9 + 7 + 2 == REPORT_DESC_ADDR    # report desc lands at literal

DTOT_ADDR = 0x5dac0
DTOT_OLD  = bytes.fromhex("b100")    # wTotalLength 0x00b1
DTOT_NEW  = bytes.fromhex("8f00")    # wTotalLength 0x008f = 118(audio)+25(HID)

DNIF_ADDR = 0x5dac2
DNIF_OLD  = bytes.fromhex("04")      # bNumInterfaces 4
DNIF_NEW  = bytes.fromhex("03")      # bNumInterfaces 3

# std-interface handler 0x5ac08: make GET_DESCRIPTOR(type 0x22) return our desc.
RPTR_ADDR = 0x5ac94                  # literal pool slot used by the kept ldr
RPTR_OLD  = struct.pack("<I", 0x20000558)       # old: &RAM list head
RPTR_NEW  = struct.pack("<I", REPORT_DESC_ADDR) # new: &report descriptor (flash)

RGET_ADDR = 0x5ac58
RGET_OLD  = bytes.fromhex("09e0027f424506d14169")  # old list-walk entry
# str r0,[r5] ; movs r0,#0x1b ; str r0,[r4] ; movs r0,#1 ; b 0x5ac6a
RGET_NEW  = bytes.fromhex("28601b202060012003e0")

# Vol+- router hook: bl 0x4f510 -> bl CAVE1 (0x5e3d8)
RHOOK_ADDR = 0x4f8d6
RHOOK_OLD  = bytes.fromhex("fff71bfe")   # bl 0x4f510
RHOOK_NEW  = bytes.fromhex("0ef07ffd")   # bl 0x5e3d8

# CAVE1 (HID send) in the stage0 tail 0xFF pad, right after plan-a-min's cave.
#   push {r4,r5,lr}; mov r4,r1(sub); bl 0x4f510; adr r5,rep_table;
#   adds r0,r5,r4; subs r0,r0,#2; movs r1,#1; bl 0x5a298;   (key-down)
#   adds r0,r5,#2; movs r1,#1; bl 0x5a298;                   (key-up)
#   pop {r4,r5,pc}; <2B pad>; rep_table = 01 02 00
CAVE1_ADDR = 0x5e3d8
CAVE1_OLD  = b"\xff" * 35
CAVE1_NEW  = bytes.fromhex("30b50c46f1f798f805a52819801e0121fbf756ffa81c0121fbf752ff30bd"
                           "ffff" "010200")
assert len(CAVE1_NEW) == 35

EDITS = [
    ("HOOK",  HOOK_ADDR,  HOOK_OLD,  HOOK_NEW),
    ("CAVE0", CAVE0_ADDR, CAVE0_OLD, CAVE0_NEW),
    ("EDIT1", EDIT1_ADDR, EDIT1_OLD, EDIT1_NEW),
    ("EDIT4", EDIT4_ADDR, EDIT4_OLD, EDIT4_NEW),
    ("BCDDEV", BCDDEV_ADDR, BCDDEV_OLD, BCDDEV_NEW),
    ("DESC",  DESC_ADDR,  DESC_OLD,  DESC_NEW),
    ("DTOT",  DTOT_ADDR,  DTOT_OLD,  DTOT_NEW),
    ("DNIF",  DNIF_ADDR,  DNIF_OLD,  DNIF_NEW),
    ("RPTR",  RPTR_ADDR,  RPTR_OLD,  RPTR_NEW),
    ("RGET",  RGET_ADDR,  RGET_OLD,  RGET_NEW),
    ("RHOOK", RHOOK_ADDR, RHOOK_OLD, RHOOK_NEW),
    ("CAVE1", CAVE1_ADDR, CAVE1_OLD, CAVE1_NEW),
]
INNER_CRC_LEN_OFF = 0x1e39c
INNER_CRC_OFF     = 0x1e3a0


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
    assert (CAVE0_ADDR - BASE) >= code_len and (CAVE1_ADDR - BASE) >= code_len, "caves outside inner CRC"
    new_crc = go4_crc32(img[:code_len])
    struct.pack_into("<I", img, INNER_CRC_OFF, new_crc)
    print(f"inner metadata CRC {old_crc:#010x} -> {new_crc:#010x} (go4crc over [0x40000:0x5e39c))")

    OUT.mkdir(parents=True, exist_ok=True)
    part = OUT / "stage0_patched.bin"
    part.write_bytes(img)
    assert len(img) == STAGE0.stat().st_size

    container = OUT / "Go4_ota_all0640_hid_winfix.bin"
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

    print("\npartition comparison (hid vs stock):")
    for p in new_man["partitions"]:
        nb = (rex / f"{p['name']}.bin").read_bytes()
        sb = (stock_rex / f"{p['name']}.bin").read_bytes()
        diff_off = {i for i, (a, b) in enumerate(zip(nb, sb)) if a != b}
        if p["partition_id"] == 1:
            unexpected = diff_off - expected
            print(f"  {p['name']} (id 1): {len(diff_off)} differ; expected {len(expected)}; "
                  f"unexpected {sorted(hex(x) for x in unexpected)}")
            assert not unexpected and diff_off == expected, \
                (sorted(map(hex, diff_off)), sorted(map(hex, expected)))
        else:
            same = hashlib.sha256(nb).hexdigest() == hashlib.sha256(sb).hexdigest()
            print(f"  {p['name']} (id {p['partition_id']}): {'IDENTICAL' if same else 'CHANGED!'}")
            assert same, p["name"]

    print("\ndisassembly of code edits from re-extracted stage0:")
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    data = (OUT / "stage0.bin").read_bytes()
    for name, addr, old, new in EDITS:
        code = data[addr - BASE: addr - BASE + len(new)]
        assert code == new, (name, code.hex(), new.hex())
        if name in ("CAVE0", "DESC", "DTOT", "DNIF", "RPTR"):
            print(f"  {name} @{addr:#x}: {code.hex()}  (data; not disassembled)")
            continue
        print(f"  {name} @{addr:#x}:")
        for ins in md.disasm(code, addr):
            print(f"    {ins.address:#07x}  {ins.bytes.hex():<10} {ins.mnemonic} {ins.op_str}")

    print("\nCAVE1 (HID send) full disassembly + rep_table:")
    c1 = data[CAVE1_ADDR - BASE: CAVE1_ADDR - BASE + 30]
    for ins in md.disasm(c1, CAVE1_ADDR):
        print(f"    {ins.address:#07x}  {ins.bytes.hex():<10} {ins.mnemonic} {ins.op_str}")
    print(f"    rep_table @0x5e3f8 = {data[0x5e3f8-BASE:0x5e3f8-BASE+3].hex()} (VolInc=01 VolDec=02 release=00)")

    print("\nnew HID descriptor block (0x5db34):")
    print("   ", data[DESC_ADDR-BASE:DESC_ADDR-BASE+25].hex(), "(HID if + HID desc + EP)")
    print("    report desc @0x5db4f:", data[REPORT_DESC_ADDR-BASE:REPORT_DESC_ADDR-BASE+27].hex())
    # walker chain check: every bLength from device desc must reach the 0x00 at 0x5dbaf
    p = 0x5daac - BASE
    while data[p] != 0:
        p += data[p]
    assert p == 0x5dbaf - BASE, hex(p + BASE)
    print(f"    descriptor bLength chain terminates correctly at {hex(p+BASE)} (string table intact)")

    blob = container.read_bytes()
    md5 = hashlib.md5(blob).hexdigest()
    cfg = {"version": "0.6.4.4", "targetPID": "20e4", "md5": md5,
           "binUrl": "local/Go4_ota_all0640_hid_winfix.bin",
           "note": "LOCAL experimental build usb-parity-hid (CDC->HID consumer control). "
                   "NOT an official Harman image."}
    (OUT / "Go4_ota_all0640_hid_winfix.bin.json").write_text(json.dumps(cfg, indent=2))

    print(f"\ncontainer: {container}\n  size: {len(blob)}\n  md5:  {md5}")
    print("  wrote config json (version 0.6.4.4) alongside")


if __name__ == "__main__":
    main()
