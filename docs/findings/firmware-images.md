# Firmware images, toolchain, references

_Migrated verbatim from RE_NOTES.md on 2026-11-02; tighten bullets when touched. Addresses are 0.6.4.0 unless marked 0600._

These findings are from `Go4_ota_all0600.bin`, the official `Go4_ota_all0640.bin` image, and a live Go 4 on 31 October 2026. A read-only BLE query confirmed the unit runs 0.6.4.0; this matches the analyzed release, though a cryptographic equality check against the installed bytes is unavailable. Addresses below refer to raw partition load addresses, not offsets in the OTA container. Unless marked 0.6.4.0, addresses refer to the older 0600 image.

Ghidra 12.2 and Temurin JDK 25 are installed under ignored `.toolchain/`. The source OTA, extracted partitions, Ghidra projects, and raw USB descriptors are under ignored `captures/`.

```bash
python3 tools/extract_fw.py captures/Go4_ota_all0600.bin
JAVA_HOME="$PWD/.toolchain/jdk" .toolchain/ghidra_12.2_PUBLIC/ghidraRun
```

The analyzed projects are `captures/ghidra/go4_stage0_v3` and `captures/ghidra/go4_main_v3`. Load `stage0_40000.bin` as `ARM:LE:32:Cortex` at `0x40000` and `main_00000.bin` as the same processor at `0x0`. The Ghidra scripts in `tools/ghidra/` seed Cortex-M vector handlers, find literal references and immediates, and dump decompiled functions.

The newer 0.6.4.0 image is saved as `captures/Go4_ota_all0640.bin` (SHA-256 `56867f41fb985776ae530b5a7d50ae01bd188561480caf0aae66661c3dc8d3aa`). It matches the byte stream at the [official Harman OTA URL](https://storage.harman.com/release/portable/go4/Go4_ota_all0640.bin), and its [OTA manifest](https://github.com/vddCore/jbl-firmware-archive/blob/master/Firmware/speaker/JBL%20GO%204/20e4/release/go4_ota.json) identifies version 0.6.4.0 and target PID `20e4`. Its extracted files and analyzed Ghidra projects are under `captures/firmware0640/`, `captures/ghidra/go4_stage0_0640`, and `captures/ghidra/go4_main_0640`. All four partitions have the same sizes as 0600 but different content. The official 0.7.4.1 image has not been acquired.

The first two reset handlers disassemble as Thumb code. The `0x400000` references from partition 1 appear to point to a separate ROM or address space; this mapping remains unverified. Do not concatenate the executable partitions into one address space without resolving that overlap.

- The Ghidra 12.2 installation in this workspace no longer runs the old Jython `.py` scripts through `analyzeHeadless` by default. `tools/ghidra/DumpFunctions.java` provides the same address-based decompilation workflow as a native Ghidra script and is being used for new traces; existing logs/findings remain valid.

As of 1 November 2026, [JBL lists 0.7.4.1](https://support.jbl.com/us/en/howto/go-4-software-update-release-notes-us/000043859.html) (30 October 2026) with only a generic performance note. A live check of the archive's `20e4` release manifest still returns 0.6.4.0 and its Harman image URL; the archive's debug manifest is 8.8.8.0 and is not a production image. A guessed `Go4_ota_all0741.bin` URL returned HTTP 403. There is no 0.7.4.1 binary here to compare or use as a patch base.

The [APK-derived OpenJBL product catalog](https://github.com/NiceDayZc/openjbl) lists two Go 4 PIDs, `20e4` and `210a`, with different OTA manifest paths. This unit reported `20e4`; a binary or procedure for the other PID must not be assumed compatible. OpenJBL documents control protocol details but deliberately omits OTA implementation.

Reference: [community firmware archive](https://github.com/pembem22/jbl-firmware), [Go 4 teardown](https://www.52audio.com/archives/221424.html), [JBL's Go 4 firmware notes](https://support.jbl.com/us/en/howto/go-4-software-update-release-notes-us/000043859.html).

## Architecture: dual Cortex-M, concurrent (round 1, 2026-11-02)
- **stage0 = core 0, main = core 1, both running at once.** stage0 is not main's bootloader. Its reset goes `0x40070` → `0x40136` → `main()` `0x566a4` (VSDK_AppTaskInit) → RTOS `0x463a0` and never jumps to main. It sets its own VTOR=`0x40000` (`[stage0] 0x445f8`). Main boots `0x71` → `0x138` → `0xb2120` (uC/OS-III via ROM, AppBTTaskInit, IPC Service). — [static]
- The same core-ID routine exists in both images (`[stage0] 0x445c0` = `[main] 0x7eb94`, byte-identical). It decides the core from where its statics live. — [static, verified]
- Shared RAM is the 64 KiB at `0x20010000` ("shar" magic, named blocks with a per-core spinlock): glob `0xa0`, ipcq `0x60`, pool `0x2800`, runs `0x74`, dbif `0x4c`. — `[stage0] 0x4a2c8`, `0x559ee`; `[main] 0x86d60`, `0xb1ff8`… — [static]
- Doorbell `0x4004c000` (ch 0 → core 1) and `0x4004c004` (ch 2 → core 0). Each core clears its own bit in IRQ11 (`[stage0] 0x456b8`, `[main] 0x8062c`). The stage0 "channels" made by `0x5ba9c(0,id)` sit on top of `0x55310` (0x98-byte IPC channel objects), so **ch `0x0a`/`0x10`/`0x11`/`0x12` are core0↔core1 IPC with main on the far end**. — [static]
- glob+`0x2a` (written by stage0 `0x4a140`, set at boot from GPIO `0x49520(0,4)`; AT DUT handlers set 4/0) makes main skip its app init `0xb2852` when the value is 1 or 4. — `[main] 0x80560` — [static]
- Service-mode entry does not touch glob+`0x2a`, the core-control register `0x4004c008`, or core 1. `0x4f4d2` reads shared "runs" +0/+9/+0xd, which main writes (`[main] 0x2c644`), so main must be alive in service mode. — [static] / [hyp]
- `0x400000`–`0x40cdxx` is mask ROM called only by core 1 (uC/OS wrappers, libc, BT). Main's NMI is `0x400007`. — [static]
- `0x4004c030`+ is the DSP mailbox used by main (`Sram2DspDm`/`DspDm2Sram`, `[main] 0x157b0`, `0xb0970`, `0x7d4fc`). — [static]
- What releases core 1 from reset is unknown (hardware or ROM). Candidates: `0x40000080` bits 2–3, the `0x4004c008`/`+0xc` handshake at `[stage0] 0x45750`. — open
