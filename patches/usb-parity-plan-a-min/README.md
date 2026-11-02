# usb-parity-plan-a-min

**Hypothesis:** On a NORMAL boot (byte0≠2), kicking the existing USB-audio setup
on cable-plug makes USB audio run through the normal DSP/EQ chain with the
physical buttons live — because in a normal boot the main-side Vol±/EQ/route
state holds its working BT values (buttons.md round 6: the main Vol± gate is HFP
call state, not service mode; byte0 never reaches main).

This is the **minimal "test the core"** version. Host-vs-charger gating and
unplug teardown are deliberately deferred (see "Known tradeoffs").

## Edits (stage0, stock base; `build.py` asserts every original byte)
| id | addr | change | path | in inner CRC? |
|----|------|--------|------|----------------|
| HOOK | `0x59428` | `mov.w r0,#0xc00` → `bl 0x5e3b8` | USB plug handler `0x593bc` (cable-change only) | yes |
| CAVE | `0x5e3b8` | 32B in the 68B `0xFF` tail pad | reached only via HOOK | **no** (after `0x5e39c`) |
| EDIT1 | `0x4f278` | USB-start thunk also `bl 0x43184` (EQ resend) | USB start only | yes |
| EDIT4 | `0x56622` | `adds r1,#0x30` → `#0x32` (reports 0.6.4.2) | value-only | yes |

CAVE logic: `if (byte0 != 2) post 0x806` (USB audio setup → router `0x4f7c8` →
`0x4fdc4`), then restore r0=0xc00/r1=0/r2=0 and return so the original `0xc00`
plug event is still posted by the untouched tail-call at `0x59470`.

## Recovery window (our only safety net — Q5: no ROM dump, no host bank-rollback)
Every changed byte is on a **USB-only path** (plug handler + cave, USB-start
thunk) or a **value-only** change (version digit, inner-CRC word). None is on
reset / scatter-load / BLE-init. Therefore a boot with **NO USB cable** is
byte-for-byte stock behavior → BLE/OTA stays alive → always re-flashable.
**Test protocol:** flash → power on with NO USB (confirm boot + BLE/OTA) →
only then plug into a host and test.

## Known tradeoffs (deferred by design)
- No host-vs-charger discrimination: plugging a wall **charger** also posts
  `0x806`, bringing USB up and (via `0x4fdc4`→cmd2→`0x92298`) grabbing the DSP
  stream if BT is idle → BT A2DP would be deferred until unplug.
- No unplug teardown.
- Downstream behavior (USB routed through the A2DP/EQ chain, Vol±, EQ audibility)
  is live-test-only; offline checks prove well-formed bytes, not behavior.

## Verify / build
`python3 patches/usb-parity-plan-a-min/build.py` → container + `.json` under
`captures/patch-candidates/usb-parity-plan-a-min/` (gitignored). Confirms all 4
outer CRCs, main/part2/part3 identical to stock, stage0 diff = 58 bytes (exactly
the edits + inner CRC), and disassembles every edit. md5/setup-CRC printed.
