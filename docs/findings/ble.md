# BLE control protocol

_Migrated verbatim from RE_NOTES.md on 2026-11-02; tighten bullets when touched. Addresses are 0.6.4.0 unless marked 0600._

The Go 4 advertises JBL service data `FDDF` and Harman manufacturer ID `0x0057` with product ID `0x20e4`. Its BLE control service is `65786365-6c70-6f69-6e74-2e636f6d0000`, with notify characteristic ending `0001` and write characteristic ending `0002`. A read-only request `aa 41 00` returned command `0x42`, payload `00 06 04 00`, and a trailing zero byte: firmware **0.6.4.0**. Request `aa 11 00` returned device-info tokens including `0x42=20e4`, `0x44=e4` (100%, charging), and `0x4d=30363430` (ASCII `0640`). The read-only `tools/ble_probe.py` reproduces this and suppresses identity fields.

The observed frame shape and opcodes agree with [JBLControl's source](https://github.com/ffrafat/JBLControl/blob/main/Sources/JBLControlKit/JBLProtocol.swift) and [OpenJBL's APK-derived protocol notes](https://github.com/NiceDayZc/openjbl/blob/main/docs/PROTOCOL.md). Both source trees are cloned only under ignored `captures/vendor/`. [ConnectPlus](https://github.com/pembem22/connect-plus) implements older JBL BLE control and a DFU flow, but its own README limits flashing validation to CSR speakers. It is not a verified updater for this Go 4's Vimicro/Zgmicro image. No BLE firmware write, reset, or mode command was sent.
