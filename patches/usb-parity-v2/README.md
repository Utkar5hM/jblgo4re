# usb-parity-v2

**Status: built and offline-verified 2026-11-02. NOT flashed.** Stage0-only, in
place, same size. Layered on usb-parity-v1 (keeps both v1 edits) and adds one
2-byte edit that starts the button scanner in the Play+BT USB service boot mode.

Firmware-derived outputs are gitignored and land in
`captures/patch-candidates/usb-parity-v2/` (run `build.py` to regenerate).

## Why v1 was not enough (root cause)

v1 resent the EQ and whitelisted Vol± (`0xf05`/`0xf06`) in the byte0==2 key
filter, but on device **no button produced any effect and the CDC IN endpoint
stayed silent**. The whitelist is downstream of an event source that never fires
in service mode.

Trace of the stage0 key pipeline (all `[stage0]`), confirmed break = scanner
never starts:

- Button init `0x4cd38` runs unconditionally at boot (`0x53ac4` →
  `0x57128`, `0x4cd38`; no byte0 gate). It registers the key table, the diag
  callback `0x4d6fc`, and the filter `0x4d674`, then **posts scan-start msg
  `0x700` only if `[0x200010b8+9] != 0`** (tail at `0x4cd7a..0x4cd90`,
  `ldrb r0,[r0,#9]; cmp r0,#0; beq 0x4cd94`). `0x4cd8c`/`0x51ff8(0x700,0)` is the
  only `0x700` producer.
- `[0x200010b8+9]` is written once, before the read, by `0x4d3e4`
  (`strb r0,[r1,#9]`, literal `0x4d3f0 -> 0x200010b8`), called from boot init
  `0x566a4`. Its value is `FUN_0004d398()` = a debounced read of GPIO port 1
  pin 0 (`FUN_00052888(1,0,3,10)`) = **the power key held at boot**.
- Normal power-on holds the power key, so the byte is non-zero and the scanner
  starts. Service mode is entered by the Play+BT chord, which toggles `cfg[4]`
  and powers off; the next boot into byte0==2 is **self-initiated with no key
  held**, so the byte is 0 and `0x700` is never posted. The scanner, scan
  handler (`0x459cc`, msgs `0x700`/`0x701`), gesture machine (`0x457a8` →
  `0x45798` → `0x50a24`) and the whole event path then produce no key events at
  all. That is why v1's whitelist was moot and the CDC diag route was silent.

Everything downstream of scan-start is already mode-clean, so forcing the scanner
is sufficient:

- Scan handler `0x459cc` and gesture `0x457a8` have **no byte0 check** (pure
  GPIO sampling). `[static]`
- `0x50a24` applies the key-table filter `0x4d674` (v1-whitelisted for `0xf0x`
  in byte0==2) to the event id, then (diag gate `0x200004e8` is 0 in this mode)
  posts the event via `0x51ff8(evid,0,0)`. `[static]`
- The byte0==2 event pre-filter `0x529fc` (dispatch table `0x5d238[2]`) passes
  `0xf05`/`0xf06` (they fall through to `return 1`). `[static]`
- Router `0x4f7c8` (entry `0x5e138`, enabled in all modes) maps
  `0xf05 → 0x4f510(0,2,0)` and `0xf06 → 0x4f510(0,3,0)` = ch-`0x11` level
  step up/down. Ch `0x11` (handle `0x20000514`, created by `0x56c50`) is live in
  service mode: the stock USB-start thunk already sends `0x4f510(0,1,0x20)` on
  it, so the step command is effective. `[static]`

Ruled out: (b) gesture/scan path is not byte0-gated; (c) `0x50a24`/`0x4f7c8` are
not skipped in service mode; (d) the level step is effective (same channel the
USB-start level-32 command uses). The sole break is (a): msg `0x700` is never
posted.

## What it changes (all `[stage0]`, 0.6.4.0)

- **EDIT 1 — EQ resend (v1, unchanged).** `0x4f278` USB-start thunk:
  `0x4f510(0,1,0x20); return 1` → `0x4f510(0,1,0x20); 0x43184(); return 1`
  (also calls stored-EQ sender `0x43184`, ch `0x0a`). 20 bytes.
- **EDIT 2 — key whitelist (v1, unchanged).** `0x4d686..0x4d69b`, the 22-byte
  whitelist loop inside filter `0x4d674` (reached only on byte0==2). Passes
  `event>>8 == 0xf` (Vol± `0xf05`/`0xf06`), `0x600`, `0xa01`, else drops to
  `0x4d6cc`. Other boot modes skip the block (`cmp #2 / bne 0x4d69c` at
  `0x4d684`).
- **EDIT 3 — force scanner start (NEW).** `0x4cd80`: `08 d0`
  (`beq 0x4cd94`) → `00 bf` (`nop`). NOPs the gate branch so `0x4cd38` always
  falls through to post scan-start msg `0x700`, regardless of the boot-time
  power-key GPIO read. The now-dead `cmp r0,#0` at `0x4cd7e` is harmless; the
  skip label `0x4cd94` stays reachable from `0x4cd44` (button-device
  registration failure), so a missing `button_dev` still skips the post. 2
  bytes, in place, no cave.
- **Inner metadata CRC** at `0x5e3a0` recomputed over `[0x40000:0x5e39c)`
  (`0xf798464c` → `0xc0b69f80`); all edits precede `code_len`.

Edit table:

| # | [img] addr | old | new | intent |
|---|---|---|---|---|
| 1 | [stage0] 0x4f278 | `10b5 0124 2022 2146 0020 00f045f9 2046 10bd 0000` | `10b5 2022 0121 0020 00f046f9 f3f77eff 0120 10bd` | add `bl 0x43184` (EQ) at USB start |
| 2 | [stage0] 0x4d686 | `1748 0021 30f81120 a242 02d0 491c 0229 f8d3 0229 17d0` | `200a 0f28 07d0 b4f5c06f 04d0 a4f60020 0128 18d1 00bf` | whitelist Vol±/0x600/0xa01 in byte0==2 |
| 3 | [stage0] 0x4cd80 | `08 d0` | `00 bf` | force scan-start `0x700` post |
| CRC | [stage0] 0x5e3a0 | `4c4698f7` | `809fb6c0` | recomputed go4 metadata CRC |

Exact byte diff from stock stage0 (verified by re-extraction): 44 bytes, all
within `0x4d686..0x4d69b`, `0x4f27a..0x4f28b`, `0x4cd80..0x4cd81`, and the 4-byte
CRC at `0x5e3a0`. `main`, `part2` (DSP), `part3` are byte-identical to stock.

## Code-cave / space proof

No code cave is used. EDIT 3 replaces a live conditional branch with a NOP in
place; EDIT 1/2 are v1's (EDIT 1 reuses an unreferenced 20-byte function slot;
EDIT 2 is a same-size inline rewrite of the whitelist loop). The tail padding
cave at `0x5e3b8..0x5e3fb` was deliberately avoided: it sits outside the inner
metadata CRC region (`[:0x5e39c)`) and before the unidentified 4-byte trailer at
`0x5e3fc` (Q9), whose meaning is unproven, so writing code there is riskier than
an in-place edit.

## Build + verify

    .venv/bin/python patches/usb-parity-v2/build.py

Checks performed offline (all pass):

1. `apply()` asserts the stock pre-edit bytes for all three edits.
2. `repack_fw.py` swaps partition 1 into the full 4-partition container and
   recomputes the outer descriptor CRC; inner metadata CRC recomputed first.
3. `extract_fw.py` re-validates all four outer CRCs, markers and footer.
4. Partition diff: stage0 differs in exactly the 44 intended offsets; `main`,
   `part2`, `part3` are byte-identical to stock.
5. Capstone disassembly of each edited region from the **re-extracted** stage0
   matches the intended Thumb; EDIT 2 branch targets (`0x4d69c`, `0x4d6cc`) land
   on existing instruction boundaries.
6. `xrefscan.py` (shared with v1): no external branch lands inside any replaced
   range. The only in-range hit (`0x4d660 → 0x4d68e`) is a false positive — a
   data/string halfword after the `pop {r3,pc}` return at `0x4d65e` ("App ..."),
   not reachable code.

## Expected observable result

In Play+BT USB service mode (byte0==2, enumerated `0ac8:bb91`): the button
scanner starts at boot, so pressing **Vol+ / Vol-** produces `0xf05`/`0xf06`,
which pass v1's filter and the state-2 pre-filter and reach
`0x4f510(0, 2|3, 0)` = a ch-`0x11` DSP level step — the speaker's own output
volume changes, as in BT mode. EQ (EDIT 1) is applied at USB start. Play/Pause to
the host still needs a USB HID interface and is out of scope.

## Residual risk / uncertainty

- **EDIT 3 is not mode-gated.** It forces the scanner on in *every* boot. Normal
  power-on already started it (power key held → gate byte non-zero), so that is
  unchanged. The one changed case is a boot where the power key is **not** held
  and it is not service mode — i.e. plugging a charger into an off device. The
  scanner would then run during "off/charging". A mode-gated version needs a
  `0x59a14()==2` call, which does not fit the 2-byte in-place slot and would
  require a code cave (rejected, see above). Impact is expected to be low:
  pressing power is routed to the normal power-on path anyway, and in that state
  `0x4f4d2()` is typically `<2`/`==1` so the filter drops Vol± on the
  non-whitelisted path; but this is static reasoning, **not observed**.
- `[0x200010b8+9] == 0` in service mode is a strong `[hyp]` from the GPIO/boot
  analysis, not a live read. If it were in fact non-zero (scanner already
  running), EDIT 3 is a harmless no-op and the true break would be elsewhere —
  but the live silence plus the single-producer analysis make that unlikely.
- Unverified on device. **Nothing here is sent to the speaker.** Flashing waits
  on a proven recovery path (Q5) and the user's decision.
