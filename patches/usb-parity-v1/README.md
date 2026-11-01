# usb-parity-v1

**Status: built and offline-verified 2026-11-02. NOT flashed.** Stage0-only, in
place, same size. Keeps the current (byte0==2) USB service boot mode but makes it
behave more like BT: resend the stored EQ at USB start, and let Vol± through the
boot-mode key filter.

Firmware-derived outputs are gitignored and land in
`captures/patch-candidates/usb-parity-v1/` (run `build.py` to regenerate).

## What it changes (all `[stage0]`, 0.6.4.0)

- **EDIT 1 — EQ resend.** `0x4f278` (the 18-byte USB-start level thunk + 2-byte
  pad). Original: `0x4f510(0,1,0x20); return 1` (sets DSP level 32). New:
  `0x4f510(0,1,0x20); 0x43184(); return 1` — also calls the stored-EQ sender
  (`0x43184`, ch `0x0a`), which the USB path never invokes. 20 bytes, no cave.
- **EDIT 2 — key whitelist.** `0x4d686..0x4d69b` (the 22-byte whitelist loop
  inside filter `0x4d674`, reached only on byte0==2). Replaces the 2-entry table
  lookup with an inline test that passes `event>>8 == 0xf` (Vol± `0xf05`/`0xf06`),
  `0x600`, and `0xa01`, else drops to `0x4d6cc`. Other boot modes are unaffected
  (the `cmp #2 / bne 0x4d69c` at `0x4d684` skips the block). After the whitelist,
  Vol± continues through the unchanged normal-mode common path (`0x5261c`,
  `0x4f4d2`, `0x55ad4`), which already handles Vol± in BT mode.
- **Inner metadata CRC** at `0x5e3a0` recomputed over `[0x40000:0x5e39b]`
  (`0xf798464c` → `0xc6a53f76`), since both edits precede `code_len`.

Exact byte diff (verified): `0x4d686..0x4d69b`, `0x4f27a..0x4f28b`
(the `10b5` push at `0x4f278` is unchanged), and the 4-byte CRC at `0x5e3a0`.
Nothing else differs.

## Build + verify

    .venv/bin/python patches/usb-parity-v1/build.py

Checks performed offline:

1. `apply()` asserts the pre-edit bytes match stock before overwriting.
2. Keystone/Capstone round-trip: both edits disassemble to the intended Thumb.
3. `repack_fw.py` swaps partition 1 into the full 4-partition container and
   recomputes the outer descriptor CRC.
4. `extract_fw.py` re-validates all four outer CRCs, markers and footer.
5. `main`, `part2` (DSP), `part3` extract byte-identical to stock; only stage0
   (and the manifest it drives) changed.
6. No external branch lands inside either replaced range (self-contained); see
   `xrefscan.py`.

## Known limits / not addressed

- Does not change the boot mode: still requires the Play+BT service-mode chord.
  Normal-boot USB audio is the separate v2 draft (findings/usb-mode.md).
- Play/Pause to the host would need a USB HID interface (v2).
- Unverified on device. **Nothing here is sent to the speaker.** Flashing waits
  on a proven recovery path (Q5) and the user's decision.
