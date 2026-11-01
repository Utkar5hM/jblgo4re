# Go 4 0.6.4.0 USB controls patch candidate

This is an **offline exploratory patch**, not a release image and not validated on hardware. The binary outputs stay under ignored `captures/patch-candidates/`.

## Changes

- Stage‑0 `0x4f278` keeps the stock `0x4f510(0, 1, 0x20)` call, then calls `0x43184` to resend the active profile. `0x4f510` uses DSP channel `0x11` (created by `0x56c50`) for level changes; the profile sender `0x43184` uses channel `0x0a` (created by `0x56c80`, handle at `0x20000518`). Whether the profile changes the service-mode PCM path still needs device verification.
- The button driver already registers `0x4d6fc` as a key callback. Stock code reports a key only when the diagnostic gate at `0x200004e8` is set. The candidate preserves that gate and also reports keys when `0x4f4d2()` returns USB-mode state 2. It reuses the stock `0x1c00` event and `AT+HMDevKEY=xx` framed CDC report path; it adds no USB interface.
- `tools/cdc_button_bridge.py` passively reads those reports and can map observed codes to PipeWire volume and MPRIS Play/Pause actions. Codes are not assigned to physical buttons by default; use `--map CODE=ACTION` after identifying them.

## Build

```bash
python3 tools/build_usb_controls_patch.py \
  captures/firmware0640/stage0_40000.bin \
  captures/patch-candidates/stage0-usb-controls.bin \
  --manifest captures/patch-candidates/stage0-usb-controls.json

python3 tools/repack_fw.py \
  captures/Go4_ota_all0640.bin 1 \
  captures/patch-candidates/stage0-usb-controls.bin \
  captures/patch-candidates/Go4_ota_all0640-usb-controls.bin
```

The builder pins the 0.6.4.0 stage‑0 SHA‑256, original hook bytes, and a 60-byte erased padding range at `0x5e3c0`. It verifies its Thumb branch destinations. The repacker validates every outer OTA partition CRC. Neither check proves the image is accepted by the device, produces processed USB audio, or is recoverable after a failed update.

## Open work

- Establish a recovery/boot path before any live installation.
- Confirm the profile command affects USB PCM, and that CDC key reports actually arrive in mode 2.
- Identify the physical-button mapping for the reported key codes, then map Vol+, Vol−, and Play/Pause in the host bridge.
- Trace and fix the powered‑USB shutdown source without suppressing battery-voltage or charge protections. This candidate does not alter power logic.
