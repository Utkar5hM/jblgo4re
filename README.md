# JBL Go 4 reverse engineering notebook

The [firmware and USB findings](RE_NOTES.md) contain the current reverse engineering map and local Ghidra setup.

The first target is a Go 4 that powers off during playback while its USB charging cable is connected. The second target is understanding its hidden USB audio mode and whether ordinary volume and playback controls can be retained. This repo contains host probes, firmware analysis tools, and a reproducible test plan. The optional CDC version probe sends one read-only query to the speaker. Nothing here flashes firmware.

## Current observations

- On this Linux host, the Go 4 is connected through Bluetooth A2DP (SBC). Its PipeWire sink exists but was suspended with no audio stream at the time of the first snapshot. The saved default sink points to AirPods, so a real Linux playback test must confirm the game stream is routed to the Go 4.
- With USB attached in ordinary mode, the Go 4 did not enumerate as a USB device on this Linux host. That is consistent with charging only; it does **not** measure whether USB power is stable.
- The user reports that on Windows the speaker apparently powers off during active playback while USB power is attached. Pressing Power turns it back on and it reconnects immediately. This points toward speaker-side power, charging, or firmware behavior, but the cause is not established yet.
- In USB service mode on this unit, pressing Volume+, Volume−, and Play produced no audible/playback change, no CDC bytes, and no change in the host-visible USB PCM volume control during a synchronized 40-second capture. The firmware reason remains unknown.
- JBL's current Go 4 firmware release note lists **0.7.4.1 (30 October 2026)** as a performance update. It does not name a shutdown or USB-audio fix. Record the speaker's current version before updating so pre/post behavior can be compared. JBL says Go 4 firmware updates have migrated from JBL Portable to **JBL ONE**.

## Reproduce the shutdown

Keep the source audio, volume, and test duration as similar as possible. Record the firmware version, battery indication in the JBL app, exact shutdown time, whether a power-off tone plays, and whether the LED goes out.

| Test | Power | Playback | What it separates |
| --- | --- | --- | --- |
| A | PC USB | The same game that triggers it | Baseline |
| B | 5 V wall charger within JBL's 5 V / 3 A limit | Same game | PC USB port or cable behavior |
| C | Battery only, after a full charge | Same game | Charging path versus speaker operation |
| D | Same power as A | Continuous music at a normal level | Game audio gaps or low-level signal versus general shutdown |

If the speaker powers off during continuous, clearly audible music on battery as well as on two hosts, a host routing problem becomes much less likely. If it happens only while charging, investigate the charging cable, port, battery, and charging circuit before assuming an inactivity timer. Do not charge a wet speaker.

### Windows (main reproduction host)

In PowerShell from the repo root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\windows_probe.ps1 -IntervalSeconds 5 -DurationSeconds 3600
```

It appends timestamped JSON lines to `captures/windows.jsonl` for present Bluetooth, USB, and audio devices. Write down the exact local time when the speaker turns off and when Power is pressed again. Windows may keep a PnP device listed after a Bluetooth disconnect, and this script does not measure game audio samples; combine its log with the speaker's LED/tone and Windows Sound settings. To take one snapshot, use `-IntervalSeconds 0`.

### Linux (second-host comparison)

```bash
python3 tools/linux_probe.py --interval 5 --duration 3600 --output captures/linux.jsonl
```

The script records Bluetooth connection state, PipeWire sinks/streams/links, and enumerated USB devices. To take one snapshot:

```bash
python3 tools/linux_probe.py --interval 0 --output captures/linux.jsonl
```

Summarize either host's log with `python3 tools/summarize.py captures/linux.jsonl` (or `captures/windows.jsonl`). It prints changes in connection, sink state, stream links, and USB devices, with timestamps.

Before testing, run `wpctl status` and set the Go 4 sink as the default if needed: `wpctl set-default <Go-4-sink-ID>`. Confirm the game appears under **Streams** and is linked to that sink. PipeWire numeric IDs can change on reconnect.

## USB audio mode experiment

JBL's documented normal USB audio procedure lists the **Go 5**, not the Go 4. The Go 4 USB audio behavior here is an observed service mode. [Go 4 user reports](https://4pda.to/forum/index.php?showtopic=1082596&st=180) describe holding **Play + Bluetooth** to enter USB audio service mode; this is not a JBL-documented Go 4 feature. Button combinations for leaving the mode vary in reports and need to be verified on this unit.

1. Save a normal-mode snapshot and note the USB cable/port used.
2. Enter the service mode using the button sequence that works on this speaker. Keep host volume very low before playing audio, because service mode may have a fixed output level.
3. Save a second snapshot. On Linux, compare the `usb` arrays and `Audio/Sink` nodes in the two JSON lines. On Windows, compare the `pnp_devices` and `sound_devices` fields. Record USB VID/PID, product name, audio sample formats, whether Bluetooth stays active, and which physical buttons still work.
4. Try the known exit sequence on this specific unit and record it precisely. Do not confuse it with a factory reset. If the speaker appears stuck, do not keep guessing button chords; disconnecting/reconnecting USB and then using the verified sequence is safer than blindly resetting it.

A host-side volume control may be possible even when the speaker's own buttons are disabled: on Linux try `wpctl set-volume <USB-sink-ID> 0.15`; on Windows start with the app's own volume control. This attenuates the audio sent to the USB device and does not restore physical button handling. Whether Windows' master slider works depends on the USB audio interface exposed in service mode; test its descriptors before designing a workaround.

The service-mode USB descriptor also exposes a CDC data interface (`0x04` OUT, `0x83` IN). `tools/cdc_listen.py` passively watches IN traffic, and `tools/cdc_version.py` sends the archived firmware's framed `AT+HMDevVER` query. Install the local Python dependencies with `python3 -m venv .venv` and `.venv/bin/pip install -r requirements.txt`. Both tools need read/write access to the current `/dev/bus/usb/BUS/DEVICE` node. The current unit accepted the version-query write but did not reply, even with DTR enabled; see [RE_NOTES.md](RE_NOTES.md) before interpreting that path.

## Firmware research

- A community archive has `Go4_ota_all0600.bin` (SHA-256 `2f440402006a65d29778075021e58cb174cf20626920187acfe0faaee75a5d19`). A local copy was inspected under ignored `captures/`; it is **not** committed or flashed.
- Its header begins `HMHEADER9`, and strings include `JBL Go 4`, `PowerOffStatusTimer`, `charge_bypass_task`, `VOLUME_CHANGED`, `POWEROFF`, and `VOL_UP`. These strings show useful code areas to investigate; they do not establish the cause of this unit's shutdown. The archived image is not the newly announced 0.7.4.1 release.
- An [original Go 4 teardown](https://www.52audio.com/archives/221424.html) identifies a ZGMICRO WS9652A audio SoC, a Southchip SC89619D charger, a USB input protection chip, and a protected 850 mAh cell in the unit it opened. That is a reference board, not confirmation of this speaker's hardware revision. A shutdown while USB is connected can still involve the power path or battery.
- Before any patching: identify this unit's hardware revision and firmware version, obtain a verified backup/recovery path, map update format and integrity checks, and reproduce the shutdown under controlled conditions. A generic firmware image or a patched OTA could brick a different board revision.

## Sources

- [JBL Portable app](https://play.google.com/web/store/apps/details?id=com.harman.ble.jbllink) — the previously supported Go 4 app linked by the user.
- [JBL app migration notice](https://support.jbl.com/gb/en/howto/portable-app-partybox-app-migration-to-jbl-one-app-mtbw9ikdhub-emea/000054613.html) — Go 4 firmware updates now use JBL ONE.
- [Go 4 firmware release notes](https://support.jbl.com/us/en/howto/go-4-software-update-release-notes-us/000043859.html) — latest listed version and change summary.
- [Go 4 spec sheet](https://support.jbl.com/on/demandware.static/-/Sites-masterCatalog_Harman/default/dw9308649c/pdfs/JBL%20Go%204_%20Specsheet_EN.pdf) — battery and charging specifications.
- [Go 4 quick start guide](https://support.jbl.com/on/demandware.static/-/Sites-masterCatalog_Harman/default/dw2d8f9429/pdfs/PA_JBL_GO%204_QSG_Global_SOP.pdf) — charging indicator and adapter limit.
- [JBL factory reset procedure](https://support.harmanaudio.com/howto/factory-reset-procedure-go-series-mhdtyj1wllf-us/000053858.html) — Go 4 reset is Volume+ and Play for more than 3 seconds; this erases settings and pairings.
- [JBL USB audio support article](https://support.jbl.com/gb/en/howto/can-i-listen-to-lossless-audio-on-my-speaker-and-does-it-support-usb-music-playback-from-laptops-and-tablets-emea/000048463.html) — lists Go 5 and other supported models, not Go 4.
- [Community Go 4 firmware archive](https://github.com/pembem22/jbl-firmware) — static analysis sample, not a flashing recommendation.

`captures/` is gitignored because logs can contain local device identifiers. Review a log before sharing it.
