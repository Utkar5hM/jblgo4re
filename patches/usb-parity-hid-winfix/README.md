# usb-parity-hid-winfix

`usb-parity-hid` (CDC→HID consumer-control, so the physical Vol+/Vol− move the
**host** system volume over native USB HID) **plus a 2-byte `bcdDevice` bump** to
get past a Windows-only enumeration failure.

## Why
`usb-parity-hid` enumerates and works on Linux (HID input node appears; Vol+/Vol−
deliver consumer-control reports that move the system volume — confirmed live).
On **Windows** the same image failed to enumerate: *"Unknown USB Device (A request
for the USB device descriptor failed)"*.

Two Opus-assisted static passes verified the descriptors and the EP0 control-
transfer engine are correct (ZLP termination, length clamping, DEVICE_QUALIFIER
STALL, blob bLength-walk, IAD/interface-count all pass), and that endpoints are
programmed **directly from the descriptor bytes** (no descriptor-vs-hardware
mismatch is possible). A valid config that enumerates on Linux but fails at the
device/config stage on Windows is the classic Windows **descriptor cache** keyed
on VID/PID/`bcdDevice`: our `bb91 / bcdDevice 0x0001` is identical to the stock
service-mode device Windows already cached as "failed". Bumping `bcdDevice` makes
Windows treat it as a new device and re-read fresh.

## Edits (stage0; = usb-parity-hid, with two value-only deltas)
| id | addr | change |
|----|------|--------|
| … | … | all `usb-parity-hid` edits verbatim (HID descriptor block, wTotalLength, bNumInterfaces, report-descriptor handler, Vol± HID-send cave) |
| BCDDEV | `0x5dab8` | `bcdDevice` `0x0001` → `0x0002` (device descriptor value; defeats the Windows cache) |
| EDIT4 | `0x56622` | version digit → reports **0.6.4.4** (proof-of-apply) |

`bcdDevice` is a device-descriptor value with no control-flow effect and zero
impact on Linux/BT behaviour. The recovery window is unchanged from
`usb-parity-hid`: every functional change is on a USB-enumeration / USB-event
path, so a boot with **no USB cable** is byte-for-byte stock → BLE/OTA stays
alive and the image is always re-flashable.

## Build / verify
`python3 patches/usb-parity-hid-winfix/build.py` → container + `.json` under the
gitignored `captures/patch-candidates/usb-parity-hid-winfix/`. Re-derives from the
stock stage0, asserts every original byte, recomputes the inner metadata CRC and
all four outer partition CRCs, confirms main/part2/part3 are byte-identical to
stock, and disassembles every code edit. Prints md5 + setup CRC. Never transmits.

See [../../docs/findings/usb-mode.md](../../docs/findings/usb-mode.md) for the
live results and the Windows-enumeration analysis.
