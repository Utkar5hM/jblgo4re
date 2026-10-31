# Go 4 reverse engineering notes

These findings are from the public `Go4_ota_all0600.bin` image and a live Go 4 in USB service mode on 31 October 2026. The archived image may differ from the firmware on this unit. Addresses below refer to raw partition load addresses, not offsets in the OTA container.

## Local toolchain

Ghidra 12.2 and Temurin JDK 25 are installed under ignored `.toolchain/`. The source OTA, extracted partitions, Ghidra projects, and raw USB descriptors are under ignored `captures/`.

```bash
python3 tools/extract_fw.py captures/Go4_ota_all0600.bin
JAVA_HOME="$PWD/.toolchain/jdk" .toolchain/ghidra_12.2_PUBLIC/ghidraRun
```

The analyzed projects are `captures/ghidra/go4_stage0_v3` and `captures/ghidra/go4_main_v3`. Load `stage0_40000.bin` as `ARM:LE:32:Cortex` at `0x40000` and `main_00000.bin` as the same processor at `0x0`. The Ghidra scripts in `tools/ghidra/` seed Cortex-M vector handlers, find literal references and immediates, and dump decompiled functions.

## OTA layout

Container SHA-256: `2f440402006a65d29778075021e58cb174cf20626920187acfe0faaee75a5d19`. The file begins with `HMHEADER9`, has four `PARTHMDT` partitions, and ends with `FOOTERHM`.

The byte at header offset `0x10` is the partition count (`4`). Four 13-byte descriptors follow at `0x11`; each parses as a one-byte partition ID and three little-endian 32-bit fields: length, an unknown parameter, and an unknown integrity word. IDs are `1, 2, 3, 6`. The integrity words do not match ordinary zlib CRC-32 or Adler-32 over the extracted payloads, so their meaning remains open. `tools/extract_fw.py` reads these lengths and validates each marker and the final footer.

| Partition | File data offset | Size | Load address | Observation |
| --- | ---: | ---: | ---: | --- |
| 0 | `0x4d` | `0x1e400` | `0x40000` | Cortex-M vectors; SP `0x20010000`, reset `0x40071` |
| 1 | `0x1e455` | `0xdd000` | `0x0` | Cortex-M vectors; SP `0x20050000`, reset `0x71` |
| 2 | `0xfb45d` | `0x4dc00` | unknown | Starts `a55a5aa5`; includes `proj_bsp32.X` |
| 3 | `0x149065` | `0x8000` | unknown | Structure still unknown |

The first two reset handlers disassemble as Thumb code. The `0x400000` references from partition 1 appear to point to a separate ROM or address space; this mapping remains unverified. Do not concatenate the executable partitions into one address space without resolving that overlap.

## Live USB service mode

The Linux host enumerated `0ac8:bb91`, manufacturer `Zgmicro`, product `JBL Go 4`, `bcdDevice 0.01`. Bluetooth disconnected. The device exposes:

- USB Audio Class 1.0, 48 kHz, 16-bit, stereo playback on isochronous OUT endpoint `0x02`.
- Audio Feature Unit 2: master mute and left/right volume controls. ALSA reports the volume control as `0..100` with `0.00..0.39 dB`, effectively no attenuation. PipeWire can still apply host-side software volume.
- CDC ACM control/data interfaces with bulk OUT `0x04` and IN `0x83`. There is no HID interface, so no standard USB button events. The CDC control interface has no notification endpoint and Linux did not create `/dev/ttyACM*`; whether the bulk endpoints carry useful diagnostics is untested.

The device node was `/dev/bus/usb/003/096` for this capture and is root owned. That path will change after re-enumeration. A temporary per-user ACL was granted with a PolicyKit password prompt; it disappears when the device is unplugged.

`tools/cdc_listen.py` is a passive reader for bulk IN `0x83`; it does not transmit. A 30-second capture received no bytes. Whether any speaker buttons were pressed during that window is unconfirmed. A 25-second ALSA poll of the USB PCM volume control showed `0,0` throughout, with button presses likewise unconfirmed.

`tools/cdc_version.py` sends only `AT+HMDevVER\r\n` in a 60-byte frame to bulk OUT `0x04` and reads bulk IN `0x83`. The frame contains a `0f f0` marker, 16-bit payload length, zero-padded payload, and a little-endian CRC-16/CCITT over the first 58 bytes, matching the archived firmware's transmit routine. The live device accepted the 60-byte USB write but returned no data in 2.5 seconds. Repeating the query with CDC DTR set and with the length field set to `0x36` also returned no data; DTR was then cleared. This does not prove that the parser is active in this mode or that the live firmware matches the archived image. No reset, power, or update command was sent.

## Preliminary code paths

- Partition 0 has an `AT+HMDevVER` command and an `AT+HMPowerOff` command in a command parser around `0x4d6d8`. The latter queues message `0x902` with parameter `7`. The transport for these commands is not yet identified; do not send them blindly.
- `PowerOffStatusTimer` is created around `0x5952c` with period `3000` (likely milliseconds). Its callback at `0x576b4` sets a state byte to `2` and posts internal message `0x905`. This establishes a power-status timer, not the cause of the user's shutdown.
- Partition 1 has an event-name table at `0xc2130`. IDs include `0x17` = `VOL_UP`, `0x18` = `VOL_DOWN`, `0x22` = `PLAY`, `0x23` = `PAUSE`, `0x88` = `ENTER_DEMO_MODE`, and `0x2` = `POWEROFF`.
- Main event routing around `0x929fe` forwards the volume and demo-mode events into `0x8e864`. The event name suggests that service USB playback may be tied to a demo mode, but that relationship is not yet proven.
- The event router `0x8e864` sends `0x17` to volume-up handler `0x8fc24` and `0x18` to volume-down handler `0x8f9b8`. Both handlers return early when state byte `+0xf6` equals `2` and a second state test is true. Setters around `0x91fbc` and `0x92030` handle six-byte peer addresses, so this gate is more likely tied to Bluetooth peer state than USB mode. Event `0x88` reaches this router but has no obvious direct handling there, so another handler or a different event path may implement the mode change.
- Partition 0 function `0x40acc` maps six one-bit key masks (`0x01, 0x02, 0x08, 0x10, 0x20, 0x40`) to `AT+HMDevKEY=05,03,02,04,01,00` text and passes them to `0x40a80`. This gives us a key-code map for tracing the button scanner, but the physical button identities are not yet assigned.
- Partition 0 callback `0x521aa` receives key message `0x1c00`. For single-key masks `0x02, 0x08, 0x10, 0x20, 0x40` with a zero second word it calls `0x40acc`; `0x4d6a4` can enqueue `0x1c00`. This path emits diagnostic `AT+HMDevKEY` text, but it has not been tied to the USB CDC interface.
- Partition 0 loop at `0x44460` reads exactly 60 bytes through `0x4a744` and passes the bytes starting at offset 4 to the AT parser `0x4d6d8`. Transmit routine `0x4a758` builds 60-byte `0f f0` frames and appends CRC-16/CCITT (polynomial `0x1021`, initial value `0`). Its lower-level function `0x59e2c` submits to endpoint number `0x83`; this matches the live CDC IN endpoint. USB initialization at `0x50a70` sets up the same RAM ring buffer (`0x20003340`) that the parser's read path uses. Together these support a USB command path in the archived firmware, but no response to the live version query has confirmed that path on this unit in service mode.

## Next static/dynamic steps

1. Follow callers of partition 0 `0x40acc` to the button scanner and chord recognizer.
2. Locate the condition that disables keys in service mode, or determine whether the main application is bypassed entirely.
3. Trace the USB receive callback that fills ring buffer `0x20003340` and determine why the live service-mode interface produces no version-query reply.
4. Obtain this unit's exact firmware version and, if possible, its matching OTA for a reliable patch target. [JBL says Go 4 updates moved to JBL ONE](https://support.jbl.com/gb/en/howto/portable-app-partybox-app-migration-to-jbl-one-app-mtbw9ikdhub-emea/000054613.html), so new OTA discovery should target that app rather than the older JBL Portable package.
5. Before attempting a firmware modification, establish an image backup and recovery path for this board revision.

Reference: [community firmware archive](https://github.com/pembem22/jbl-firmware), [Go 4 teardown](https://www.52audio.com/archives/221424.html), [JBL's Go 4 firmware notes](https://support.jbl.com/us/en/howto/go-4-software-update-release-notes-us/000043859.html).
