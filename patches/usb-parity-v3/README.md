# usb-parity-v3

**v3 = v2 + a visible firmware version bump 0.6.4.0 -> 0.6.4.1.**
Goal: give an unambiguous proof-of-apply — after flashing, the device's BLE
version reply (`aa 41 00` -> `aa 42 04 <bytes>`) and `jblgo4.py info` report
0.6.4.1 instead of 0.6.4.0.

Offline build + verify only. Never flashed/sent by this patch.

## Hypothesis
The 4-byte version in the `0x42` reply can be bumped to `00 06 04 01` by changing
exactly one stage0 instruction — the formatter that builds the version ASCII
string — because that formatter is the only point on the `0x42` path that lives
inside the OTA container.

## Version-display chain (traced, [static] unless noted)
Dispatcher `[stage0] 0x57dcc` routes opcode `0x41` -> `FUN_00050286`, which emits
`aa 42 04` + 4 bytes `s[1]-'0', s[3]-'0', s[5]-'0', s[6]-'0'` where
`s = FUN_000527b4()` = `*(int*)(DAT_000527e4+4) + 0x40` (a RAM device-info struct,
version ASCII at +0x40).

- `FUN_000527b4` returns the cached string at struct+0x40; if the "version ready"
  flag (bit 3 / 0x08 of struct+0xc4) is clear it first calls `FUN_000565d0`.
- `FUN_000565d0` reads the **raw 16-bit version** via `FUN_00054144(0x1a, &v, 2)`
  (= config property item **0x1a**, value **0x2806** on 0.6.4.0) and formats it
  into struct+0x40 as ASCII `"v0.6.40"`:
  - +0x41 = `(v.lo/10)+'0'` = 0   -> `s[1]` -> major 0
  - +0x43 = `(v.lo%10)+'0'` = 6   -> `s[3]` -> minor 6
  - +0x45 = `(v.hi/10)+'0'` = 4   -> `s[5]` -> patch 4  (v.hi = 0x28 = 40)
  - +0x46 = `(v.hi%10)+'0'` = 0   -> `s[6]` -> **build 0**  <= the byte we bump
  - `[stage0] 0x56622 adds r1,#0x30 ; 0x56624 strb r1,[r0,#0x6]`
- Boot populator `FUN_00056488` (from `0x4358c`) calls `FUN_000565d0` to fill the
  cache at boot; a hardcoded fallback string only runs after 20 failed property
  reads and is `"v0.0.00"` (`DAT_00056574`), i.e. a 0.0.0.0 placeholder, never
  0.6.4.0. So on a healthy device the version always comes from item 0x1a.

Live confirmation: post-v1-flash probe returned `aa 42 04 00 06 04 00` = 0.6.4.0,
exactly matching this arithmetic (`s[6]=0`). `[live]`

### Why the container DESCRIPTOR version is NOT the source (negative result)
- The `0x42` value comes from config property item **0x1a**, read by the type-1
  property store (`FUN_00048ae4` -> `FUN_0004b79c`/`FUN_0004b4a0`) from a **fixed
  config/NVM flash region** addressed via the global flash-manager struct
  (`0x20000760`/`0x200007a4`, primary/backup offsets +0x18/+0x1c). That region is
  **not one of the 4 OTA partitions** (stage0/main/DSP/part3).
- **No code in stage0 (or main) writes item 0x1a.** The only property writers
  (`FUN_00048b70`/`FUN_00054156`) are called with ids 0x240/0x245/0x180 — never
  0x1a. Item 0x1a is also **not** in the apply-time user-data migration set
  (`FUN_00053ed4` preserves ids `0x2,0x4,0x1d,0x146,0x149,0x180` only).
- The OTA descriptor "parameter"/version field is per-partition and is 0 for
  stage0/main (`0x00000000`), `0x00010002` for part2, and only `0x00040600` for
  part3. It is written to the on-device slot table (+0x48) by `FUN_000414b0` and
  is read by the DFU-version path (`0x4a`->`0x4b`, 3 bytes), **not** by `0x42`.

**Conclusion:** bumping the container descriptor version would NOT change the
`0x42` reply (item 0x1a is factory-provisioned, non-OTA, preserved across applies).
The only container-resident lever on the `0x42` string is the stage0 formatter —
so v3 bumps there. This is confirmed to reach the `0x42` reply.

## Edits
All applied in place to stock `stage0_40000.bin` (load `0x40000`); same-size.
EDIT1-3 are v1/v2, unchanged. EDIT4 is new in v3.

| id | [img] addr | file off | old -> new | disasm |
|----|-----------|----------|------------|--------|
| EDIT1 | [stage0] 0x4f278 | 0x0f278 | (v1) `0124 2022 2146 0020 00f045f9 2046 ...` -> `2022 0121 0020 00f046f9 f3f77eff 0120` | USB-start thunk also `bl 0x43184` (resend stored EQ) |
| EDIT2 | [stage0] 0x4d686 | 0x0d686 | (v1) filter table-scan -> inline whitelist | pass `0xfxx`, `0x600`, `0xa01` in boot-mode key filter |
| EDIT3 | [stage0] 0x4cd80 | 0x0cd80 | (v2) `08d0` (beq 0x4cd94) -> `00bf` (nop) | force button scanner start (post msg 0x700) |
| **EDIT4** | **[stage0] 0x56622** | **0x16622** | **`3031` -> `3131`** | **`adds r1,#0x30` -> `adds r1,#0x31`** |

EDIT4 detail:
```
0x5661e  mls  r1,r2,r3,r1   ; r1 = v.hi % 10   (unchanged)
0x56622  adds r1,#0x31      ; r1 = (v.hi%10)+'0'+1  (was +'0')   <-- EDIT4
0x56624  strb r1,[r0,#0x6]  ; struct+0x46 = s[6] = build digit   (unchanged)
```
On 0.6.4.0, `v.hi%10 = 0`, so the build digit becomes `'0'+1 = '1'` and
`FUN_00050286` emits `aa 42 04 00 06 04 01` = **0.6.4.1**. The ASCII string at
struct+0x40 becomes `"v0.6.41"`.

### Why this space / instruction is safe (no cave needed)
EDIT4 is an **in-place, same-length** 16-bit Thumb instruction replacing another
16-bit Thumb instruction of the same class (`ADDS Rdn,#imm8`, T2 encoding
`0x3130 -> 0x3131`). Nothing moves: no branch target, no literal pool, no
alignment, no PC-relative load is touched (verified by disassembling the
re-extracted stage0 — the following `strb r1,[r0,#0x6]` and all neighbours are
intact). It only changes the immediate added before the store, so only the one
output byte (the build digit) changes.

## CRC layers kept valid
1. **Per-partition go4 CRC-32** (poly `0x681bb522`): stage0 payload changed, so
   `repack_fw.py` recomputes it: descriptor field `0xb6dc4025 -> 0xb29002ff`.
2. **Inner stage0 metadata go4 CRC** at stage0 `0x5e3a0` over `[0x40000:0x5e39c)`:
   EDIT4 @0x56622 is inside that range, so recomputed:
   `0xf798464c (stock) -> 0xc4194070 (v3)` (v2 value was `0x809fb6c0`).
3. **Descriptor-table CRC16** (device fn `0x44528`, records +0x1d4): **untouched.**
   v3 changes no descriptor parameter/version field (stage0 parameter stays
   `0x00000000`). The per-partition CRC32 field is a normal payload-CRC update.
   The device rebuilds + re-CRCs its slot records from the received descriptors at
   install, so nothing to precompute here.
4. Whole-file DFU setup CRC: computed by the flasher; not embedded. New file md5
   below; recompute setup CRC/len with `tools/setup_crc.py` before any transmit.

## Container diff v2 -> v3 (9 bytes)
| container off | v2 -> v3 | meaning |
|---------------|----------|---------|
| 0x00001a..1d | `87 72 2f f2` -> `ff 02 90 b2` | stage0 descriptor per-partition CRC32 (LE 0xf22f7287 -> 0xb29002ff) |
| 0x01666f | `30` -> `31` | EDIT4 version build-digit instruction byte |
| 0x01e3ed..3f0 | `80 9f b6 c0` -> `70 40 19 c4` | inner stage0 metadata CRC (LE 0x809fb6c0 -> 0xc4194070) |

## Verification (all passing; see build.py output)
- keystone re-assembles `adds r1, #0x31` -> `3131` == EDIT4_NEW.
- `extract_fw.py` on v3: all 4 outer partition CRCs validate.
- stage0 vs stock: 45 bytes differ, all expected (EDIT1-4 changed bytes + 4-byte
  inner CRC), zero unexpected.
- main / part2 / part3: byte-identical to stock (sha256 match).
- v3 vs v2 container: exactly the 9 bytes above.
- capstone disasm of EDIT1-4 from the re-extracted stage0 matches intent; EDIT4 =
  `adds r1, #0x31` at 0x56622.

## Outputs
- Container: `captures/patch-candidates/usb-parity-v3/Go4_ota_all0640_usbparity_v3.bin`
  (gitignored), 1380461 bytes, md5 `b91571366445eff1f126deef2b7ce664`.
- Build: `patches/usb-parity-v3/build.py` (idempotent; asserts stock bytes before writing).

## Expected observable
After the user flashes v3 (their call, present hardware, normal BT mode): the BLE
version query `aa 41 00` returns `aa 42 04 00 06 04 01` and `jblgo4.py info`
reports **0.6.4.1**. Plus v2's behaviour (EQ resend + Vol± + scanner on USB).

## Residual risk
- **Second version copies NOT changed (intentional):** the 3-byte DFU version
  (`0x4a`->`0x4b` = `00 06 04`) and the raw config item 0x1a itself still read
  0.6.4(.0). Only the formatted `0x42` string is bumped. So the APK's
  `getConfigVersion`/update-flag logic and the `0x4b` reply are unchanged. This is
  sufficient for the stated proof-of-apply (0x42 / jblgo4.py info) but is a
  display-only bump, not a true version rewrite.
- **Formatter arithmetic is value-relative:** EDIT4 adds 1 to the build digit. On
  this firmware `v.hi%10 = 0` so it is exactly '1' (confirmed live `...00`). If the
  build digit were 9 it would overflow to ':' — not the case here.
- **Descriptor CRC16 assumption:** `FUN_00044528` decompiles to a Ghidra-stubbed
  no-op (table CRC it failed to analyse). v3 avoids depending on recovering it by
  not touching any descriptor parameter/version field; only the payload CRC32
  (which `repack_fw.py` computes with the verified go4 algorithm) changed.
- Inherits all v1/v2 behavioural and brick risks (stage0 edit; recovery is
  ROM-only and unproven — do not flash until recovery is proven).
