# usb-parity-hid

**Hypothesis:** Converting the (confirmed-dead) CDC interface into a USB **HID
Consumer Control** interface, and emitting a HID input report when the stage0
Vol+-/router fires `0xf05`/`0xf06`, makes the physical Volume buttons move the
**HOST PC's** system volume (Volume Increment `0x00E9` / Volume Decrement
`0x00EA`). Built on the flashed `usb-parity-plan-a-min` base (normal-boot USB
enumeration + a running button scanner are both required for HID to ever send).

Play/Pause (`0x00CD`) is in the report descriptor for completeness but is
**never sourced** — `0x22`/`0x23` are main-partition events invisible to stage0.
No main-partition changes.

## Design in one paragraph
The whole descriptor set (device+config+strings) is a single static blob at
`[stage0] 0x5daac`, walked by `bLength` in `0x5a844`/`0x5aac4`. We rewrite the
59-byte CDC block (`0x5db34`) in place as a 25-byte HID block (interface + HID
class descriptor + one interrupt-IN endpoint reusing `EP 0x83`), shrink the
config `wTotalLength`/`bNumInterfaces`, and wrap the 34 freed bytes in **one
`bLength`-valid filler descriptor** that also stores the 27-byte HID report
descriptor (so the chain still walks cleanly to the strings). The std-interface
handler `0x5ac08` already recognises `GET_DESCRIPTOR(type 0x22)`; we patch its
body to return our flash report-descriptor pointer+length directly (no RAM list,
no init code). On a Vol+- event the router `0x4f7c8` jumps to a 35-byte cave that
keeps the original speaker-gain step and then sends a 1-byte key-down + key-up on
`EP 0x83` via the existing CDC submit-and-wait primitive `0x5a298`.

## Edits (stock base; `build.py` asserts every original byte)
| id | addr | change | path | in inner CRC? |
|----|------|--------|------|----------------|
| HOOK  | `0x59428` | `mov.w r0,#0xc00` → `bl 0x5e3b8` | plan-a-min USB-plug hook | yes |
| CAVE0 | `0x5e3b8` | 32B plan-a-min cave (post `0x806` on normal-boot plug) | USB-plug only | **no** |
| EDIT1 | `0x4f278` | USB-start thunk also `bl 0x43184` (EQ resend) | USB start only | yes |
| EDIT4 | `0x56622` | `adds r1,#0x30` → `#0x33` (reports 0.6.4.3) | value-only | yes |
| DESC  | `0x5db34` | CDC block (59B) → HID if(9)+HID desc(9)+int-IN EP(7)+filler(2)+report-desc(27)+pad(5) | USB enumeration | yes |
| DTOT  | `0x5dac0` | config `wTotalLength` `0x00b1`→`0x008f` | USB enumeration | yes |
| DNIF  | `0x5dac2` | config `bNumInterfaces` `4`→`3` | USB enumeration | yes |
| RPTR  | `0x5ac94` | `0x5ac08` literal `0x20000558`→`0x5db4f` (&report desc) | USB `GET_DESCRIPTOR(0x22)` | yes |
| RGET  | `0x5ac58` | `GET_DESCRIPTOR(0x22)` body → return (&report desc, 27) | USB `GET_DESCRIPTOR(0x22)` | yes |
| RHOOK | `0x4f8d6` | Vol+- router `bl 0x4f510` → `bl 0x5e3d8` | Vol+- event | yes |
| CAVE1 | `0x5e3d8` | 35B HID-send cave | Vol+- event | **no** |

Disassembly of the two new code regions (from the round-tripped container):

```
RGET  0x5ac58  str r0,[r5] ; movs r0,#0x1b ; str r0,[r4] ; movs r0,#1 ; b 0x5ac6a
RHOOK 0x4f8d6  bl 0x5e3d8

CAVE1 0x5e3d8  push {r4,r5,lr}
      0x5e3da  mov  r4,r1            ; r4 = sub (2=Vol+, 3=Vol-)
      0x5e3dc  bl   0x4f510          ; original speaker-gain step (keeps BT behaviour)
      0x5e3e0  adr  r5,#0x14         ; r5 = &rep_table (0x5e3f8)
      0x5e3e2  adds r0,r5,r4
      0x5e3e4  subs r0,r0,#2         ; r0 = &rep_table[sub-2] : Vol+->01, Vol-->02
      0x5e3e6  movs r1,#1
      0x5e3e8  bl   0x5a298          ; key-down on EP 0x83 (submit + wait-for-host-poll)
      0x5e3ec  adds r0,r5,#2         ; r0 = &rep_table[2] = 0x00 (release)
      0x5e3ee  movs r1,#1
      0x5e3f0  bl   0x5a298          ; key-up
      0x5e3f4  pop  {r4,r5,pc}
      rep_table @0x5e3f8 = 01 02 00
```

## New descriptors (host-visible)
HID interface `09 04 02 00 01 03 00 00 00` (interface 2, 1 EP, class 0x03/0/0).
HID class descriptor `09 21 11 01 00 01 22 1b 00` (bcdHID 1.11, 1 report desc,
type 0x22, length 27).  Endpoint `07 05 83 03 08 00 0a` (`EP 0x83` IN, interrupt,
8-byte, 10 ms).  Config: `bNumInterfaces` 3, `wTotalLength` 0x8f (118 audio + 25
HID). Interfaces 0/1 (UAC1 audio) are untouched.

HID report descriptor (27 B) at `0x5db4f`:
```
05 0C  Usage Page (Consumer)
09 01  Usage (Consumer Control)
A1 01  Collection (Application)
15 00  Logical Minimum (0)
25 01  Logical Maximum (1)
75 01  Report Size (1)
95 03  Report Count (3)
09 E9  Usage (Volume Increment)
09 EA  Usage (Volume Decrement)
09 CD  Usage (Play/Pause)     ; present, never sourced by stage0
81 02  Input (Data,Var,Abs)
95 05  Report Count (5)
81 01  Input (Const)          ; 5-bit pad -> 1-byte report
C0     End Collection
```
Report byte: bit0 = Vol+, bit1 = Vol-, bit2 = Play/Pause.

## Descriptor-chain proof (string table must stay reachable)
`build.py` walks the blob from the device descriptor stepping by each `bLength`
and asserts it lands exactly on the `0x00` terminator at `0x5dbaf` (i.e. the
langid/Manufacturer/Product/serial strings are still found). The 34 freed CDC
bytes are one descriptor (`bLength=0x22`, type `0xff`) so the walker steps over
them in a single hop; the report descriptor lives inside that filler and is
never walked. `GET_DESCRIPTOR(config)` returns only `wTotalLength=0x8f`, so the
host never sees the filler.

## CDC reclamation / caller neutralization
**No CDC code is overwritten, so nothing needs neutralizing.** The HID logic fit
without reclaiming code (report-desc served by the in-place `0x5ac08` patch;
report bytes stored in the freed config-blob space; send+routing in the stage0
tail pad after plan-a-min). The CDC *code* (AT parser `0x4d6d8`/`0x4d71c`, App
USB Transmit task `0x44044`, transmit frame builder `0x4a758`, CDC IN wrapper
`0x5a298`) is left byte-identical. After the descriptor change the host sees no
CDC data interface and **no `EP 0x04` OUT exists**, so the parser task has no
input and blocks on its empty queue exactly as it already does on this unit
(CDC confirmed dead, three live retests → zero bytes). We deliberately **keep**
`0x5a298` + the CDC transport init `0x50bc0` (its completion semaphore at
`0x20000598+0x30`) because CAVE1 reuses `0x5a298` as the EP-0x83 submit+wait
primitive.

## Why the send works, and why it is safe in BT/no-USB mode
`0x5a298(buf,len)` submits on `EP 0x83` (`0x5a5a4`), then waits on the transport
semaphore until the host fetches the packet (so key-down is delivered before
key-up overwrites the per-endpoint buffer — avoids the down/up race). It gates on
the CDC-active flag `*0x20000598 == 0` (returns `-5`, an instant no-op, if unset)
and on `EP 0x83` being enabled (endpoint table at static RAM `0x20003240`,
`+0x2c`, returns `-2` if not). On a **no-USB / BT boot**, `SET_CONFIGURATION`
never runs → the config callback `0x5a004` never sets `0x20000598[0]` → `0x5a298`
no-ops instantly; CAVE1 still performs the original `0x4f510` speaker step, so
**BT-mode Vol+- is byte-for-byte identical in effect to stock** (no block, no
crash, no HID traffic). On a USB host, `SET_CONFIGURATION` sets the flag and
enables `EP 0x83` (HID interrupt IN), so the report is delivered.

## Recovery window (Q5 — our only safety net)
Every changed byte is on a USB-enumeration path (descriptor blob, `0x5ac08`
`GET_DESCRIPTOR` handler), a USB-event path (the Vol+- router, which no-ops the
HID send when USB is down), or value-only (version digit, inner CRC). **Nothing
on reset / scatter-load / BLE-init changed.** A boot with **no USB cable** is
stock behaviour → BLE/OTA alive → always re-flashable. Worst-case failure of the
HID change is that the host fails to bind the HID interface (audio still
enumerates) or reports don't deliver — not a brick. Test protocol: flash → power
on with **no USB** (confirm boot + BLE/OTA) → then plug a host and test Vol+-.

## Residual risks (live-test only)
- **SET_IDLE / GET_REPORT are not answered** (no HID class handler registered) →
  they STALL. Linux `usbhid` tolerates this for an input-only consumer device;
  Windows may be less tolerant. If the host refuses to bind, iterate.
- **`EP 0x83` is reconfigured bulk→interrupt** via the same endpoint parser;
  if the controller needs interrupt-specific setup it may behave as bulk (still
  delivers IN data). Unverified offline.
- **In USB-host mode Vol+- moves BOTH host volume and the speaker's own gain**
  (we keep `0x4f510` because dropping it would break BT-mode Vol+-). Accepted per
  tasking; the net effect is a double step in the same direction.
- If the host polls `EP 0x83` slowly or not at all (e.g. a dumb charger that
  enumerated), each press blocks the event task up to ~1 s ×2 in `0x5a298`.
- HID binding / report delivery / host-volume movement are all **live-test only**
  (offline proves well-formed bytes + an intact descriptor chain, not behaviour).

## Build / verify
`.venv/bin/python patches/usb-parity-hid/build.py` → container + `.json`
(version 0.6.4.3 + md5) under `captures/patch-candidates/usb-parity-hid/`
(gitignored). Offline verification (all passed): extract validates all 4 outer
CRCs; `main`/`part2`/`part3` byte-identical to stock; stage0 diff = **165 bytes**
= exactly the edits + inner CRC (0 unexpected); every code edit disassembles with
branch targets on instruction boundaries; descriptor `bLength` chain terminates
at `0x5dbaf`. Never transmits. md5 `0f9dc9434e341c8b9ee715c9f78bfa8c`.
