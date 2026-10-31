# Go 4 reverse engineering notes

These findings are from `Go4_ota_all0600.bin`, the official `Go4_ota_all0640.bin` image, and a live Go 4 in USB service mode on 31 October 2026. Neither image is verified as the firmware on this unit. Addresses below refer to raw partition load addresses, not offsets in the OTA container. Unless marked 0.6.4.0, addresses refer to the older 0600 image.

## Local toolchain

Ghidra 12.2 and Temurin JDK 25 are installed under ignored `.toolchain/`. The source OTA, extracted partitions, Ghidra projects, and raw USB descriptors are under ignored `captures/`.

```bash
python3 tools/extract_fw.py captures/Go4_ota_all0600.bin
JAVA_HOME="$PWD/.toolchain/jdk" .toolchain/ghidra_12.2_PUBLIC/ghidraRun
```

The analyzed projects are `captures/ghidra/go4_stage0_v3` and `captures/ghidra/go4_main_v3`. Load `stage0_40000.bin` as `ARM:LE:32:Cortex` at `0x40000` and `main_00000.bin` as the same processor at `0x0`. The Ghidra scripts in `tools/ghidra/` seed Cortex-M vector handlers, find literal references and immediates, and dump decompiled functions.

The newer 0.6.4.0 image is saved as `captures/Go4_ota_all0640.bin` (SHA-256 `56867f41fb985776ae530b5a7d50ae01bd188561480caf0aae66661c3dc8d3aa`). It matches the byte stream at the [official Harman OTA URL](https://storage.harman.com/release/portable/go4/Go4_ota_all0640.bin), and its [OTA manifest](https://github.com/vddCore/jbl-firmware-archive/blob/master/Firmware/speaker/JBL%20GO%204/20e4/release/go4_ota.json) identifies version 0.6.4.0 and target PID `20e4`. Its extracted files and analyzed Ghidra projects are under `captures/firmware0640/`, `captures/ghidra/go4_stage0_0640`, and `captures/ghidra/go4_main_0640`. All four partitions have the same sizes as 0600 but different content. The official 0.7.4.1 image has not been acquired.

## OTA layout

Container SHA-256: `2f440402006a65d29778075021e58cb174cf20626920187acfe0faaee75a5d19`. The file begins with `HMHEADER9`, has four `PARTHMDT` partitions, and ends with `FOOTERHM`.

The byte at header offset `0x10` is the partition count (`4`). Four 13-byte descriptors follow at `0x11`; each parses as a one-byte partition ID and three little-endian 32-bit fields: length, an unknown parameter, and an unknown metadata word. IDs are `1, 2, 3, 6`. The metadata words for IDs 1, 2, and 3 are identical in the 0600 and 0.6.4.0 packages even though their payloads differ substantially, so they are not ordinary per-partition payload checksums. The ID 6 word changes, but does not match ordinary zlib CRC-32 or Adler-32 over that partition. `tools/extract_fw.py` reads the lengths and validates each marker and the final footer.

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
- CDC ACM control/data interfaces with bulk OUT `0x04` and IN `0x83`. There is no HID interface, so no standard USB button events. The CDC control interface has no notification endpoint and Linux did not create `/dev/ttyACM*`; passive captures yielded no data, and read-only version queries got no reply.

The device node was `/dev/bus/usb/003/096` for this capture and is root owned. That path will change after re-enumeration. A temporary per-user ACL was granted with a PolicyKit password prompt; it disappears when the device is unplugged.

`tools/cdc_listen.py` is a passive reader for bulk IN `0x83`; it does not transmit. A 30-second capture received no bytes. Whether any speaker buttons were pressed during that window is unconfirmed. A 25-second ALSA poll of the USB PCM volume control showed `0,0` throughout, with button presses likewise unconfirmed.

In a later 40-second synchronized capture, the user pressed Volume+, Volume−, and Play in USB service mode and reported no change in loudness or playback. CDC IN emitted no bytes, the ALSA USB PCM volume control remained `0,0`, and the device stayed enumerated as `0ac8:bb91`. This confirms that these buttons provide no observed control in this mode on the tested unit; it does not yet locate the firmware gate or prove the buttons are electrically disabled.

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

### 0.6.4.0 cross-check

- The exact live USB device descriptor (`0ac8:bb91`, bcdDevice 0.01) is present in stage-0 at `0x5daac`. Initialization at `0x5aa3c` registers its descriptor table. This places the service-mode USB implementation in the small stage-0 image; the main image may still provide application behavior.
- The 60-byte AT parser loop is at `0x44044` and calls `0x4d71c`; its entry pointer at `0x51b80` sits beside the task name `App USB Transmit`. A callback at `0x51b60` creates that task on internal event `0xa03`. This supports the archived firmware's USB command path, but the live CDC endpoint remains silent.
- Mode-state handler `0x51620` emits event `0x901` when a mode value changes to `2` or `3` from a lower value. Power handler `0x59e32` turns `0x901` into `0x806` when its state byte equals `2`; event router `0x4f7c8` handles `0x806` by calling USB audio setup `0x4fdc4`. That setup registers the USB descriptors and an isochronous audio callback for 48 kHz playback. The physical Play+Bluetooth chord's state-write point is not yet located.
- USB audio callback `0x4c6f0` accumulates incoming PCM and forwards blocks to `0x4feac`, which copies up to `0xc0` bytes to a buffer and signals another task. Neither function visibly applies gain or maps a key event. This is a patch investigation lead, not proof that no later stage can change volume.
- `AT+HMDevKIN` and `AT+HMDevKOF` in parser `0x4d71c` write the same state byte at RAM `0x200004b8` read by key-reporting gate `0x52610` via `0x4d6fc`. The two additional functions invoked by those commands (`0x418b6`, `0x419f0`) are stubs in this build. This gate controls diagnostic `AT+HMDevKEY` forwarding; it does **not** establish the cause of the disabled Volume+/Volume−/Play actions.
- `power_smart_control` is created at `0x53034` with two 30,000-unit timers, likely milliseconds. Its status function `0x53f04` samples an ADC through `0x4237c`, smooths the sample through `0x57590`, and maps it through threshold logic at `0x57958` into a level `0..6`. That level is stored in RAM state `0x200000e8 + 3` and passed to `0x59328`. When the level is zero on more than seven consecutive calls and another state check `0x59a9c()==2` holds, `0x59328` posts power-off event `0x902` with reason byte `6`. The functions' use of charger-status bits and level thresholds makes a low-battery or voltage-sag shutdown a strong interpretation. It remains unproven for this unit, and the physical threshold values have not been recovered.
- Another path, `0x50d30`, posts event `0x902` with reason `6` if a flag is set, the `0x59a14()` state equals `1`, and event bit `0x200` is absent. It runs in a loop next to `0x50c0c`, which contains charge-bypass control logic. This is a separate power/charging candidate.
- Both power-off conditions also exist in the older 0600 image at `0x58e2c` and `0x50be0` with the same zero-level counter and event/reason values. Their presence in two releases makes them intentional firmware behavior, although it still does not show which one fires on the user's speaker.

## Next static/dynamic steps

1. Trace which subsystem sets RAM `0x200000e8 + 3` in 0.6.4.0 and what event bit `0x200` means before linking either power-off candidate to the observed shutdown.
2. Locate the condition that disables keys in service mode, or determine whether the main application is bypassed entirely. The live button test confirms the loss of Volume+/Volume−/Play behavior.
3. Locate the state-write point triggered by the Play+Bluetooth chord. In 0.6.4.0, mode-state transition `0x901` leads to USB-audio event `0x806`, but the chord recognizer is still unknown.
4. Trace why USB task event `0xa03` is or is not emitted in service mode, and why the live CDC endpoint produces no version-query reply.
5. Obtain this unit's exact firmware version and, if possible, its matching OTA for a reliable patch target. [JBL says Go 4 updates moved to JBL ONE](https://support.jbl.com/gb/en/howto/portable-app-partybox-app-migration-to-jbl-one-app-mtbw9ikdhub-emea/000054613.html), while the old public `go4_ota.json` still serves 0.6.4.0.
6. Before attempting a firmware modification, establish an image backup and recovery path for this board revision.

Reference: [community firmware archive](https://github.com/pembem22/jbl-firmware), [Go 4 teardown](https://www.52audio.com/archives/221424.html), [JBL's Go 4 firmware notes](https://support.jbl.com/us/en/howto/go-4-software-update-release-notes-us/000043859.html).
