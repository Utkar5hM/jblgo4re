# JBL Go 4 firmware RE

**Goal:** a USB-C audio mode on the user's Go 4 (fw 0.6.4.0, PID `0x20e4`) where the normal DSP chain (EQ) and the physical buttons work. Stock "service mode" (Play+BT chord, USB `0ac8:bb91`) plays raw UAC1 PCM with dead buttons. Secondary: the plugged-in shutdown during playback.

Read `docs/STATUS.md` first. It holds the strategy, open questions, and who is doing what. Topic findings live in `docs/findings/*.md`, so load only the topic you need.

## Hard safety rules (enforced partly by `.claude/hooks/guard.sh`)
- **Never flash, OTA-send, reset, or power-cycle the speaker.** BLE opcodes `0x43`–`0x4e` (OTA) and `AT+HMPowerOff` are off limits. A modified image is only ever *built and verified offline*; sending it is the user's decision, made after a recovery path is proven.
- Live-device actions are limited to the existing read-only probes (`tools/ble_probe.py`, `cdc_listen.py`, `cdc_version.py`, `cdc_key_probe.py`, `linux_probe.py`). Anything new that transmits to the device needs the user's explicit OK, and the user has to be physically present (button presses, observations).
- A built OTA must always be a **full 4-partition container**. The flash is A/B banked, and a partial container would leave the new bank incomplete.
- Firmware images and anything derived from them (`captures/`, including the index) must never be committed.

## Firmware layout (0.6.4.0 unless stated)
| file (`captures/firmware0640/`) | OTA ID | load | notes |
|---|---|---|---|
| `stage0_40000.bin` | 1 | `0x40000` | Cortex-M, SP `0x20010000`, RAM `0x2000xxxx`. USB stack + service-mode audio, power, BLE GATT, OTA receive, CDC AT parser |
| `main_00000.bin` | 2 | `0x0` | Cortex-M, SP `0x20050000`, RAM `0x2002xxxx`. App: event names, buttons/volume, EQ policy |
| `part2_unknown.bin` | 3 | — | CoolFlux BSP32 DSP image (X/Y/P), ISA undecoded |
| `part3_unknown.bin` | 6 | — | 32 KiB, unknown |

The two ARM images overlap in address range (`0x40000..0x5e400`), so always say which image an address belongs to: `[stage0] 0x4fdc4`, `[main] 0x8e128`.

## Looking things up (in this order)
1. **`tools/q.sh`**: instant greps over the pre-exported Ghidra index in `captures/index/{main,stage0}/`:
   `q.sh fn ADDR` (decompiled C, works mid-function) · `q.sh asm ADDR` · `q.sh callers ADDR` · `q.sh callees ADDR` · `q.sh val 0x20000538` (every immediate/literal-pool use, which is how to find RAM xrefs) · `q.sh str REGEX` · `q.sh grep REGEX` (all decompiled C).
   You can also grep the raw files directly: `functions.tsv`, `calls.tsv`, `consts.tsv`, `strings.tsv`, `raw_strings.txt`, `decomp/0x%08x.c`, `asm/0x%08x.s`.
2. **`tools/gh.sh main|stage0 Script.java args…`**: headless Ghidra (read-only, ~15 s cold start) for things the index can't answer: data at an address, functions Ghidra never created, and so on. Scripts live in `tools/ghidra/`. Never write a one-off log per query. Put scratch output in `captures/scratch/<topic>/` and delete it once its finding is recorded.
3. If you rename or retype things in the Ghidra GUI, rerun `tools/build_index.sh` (40 s).

Other tools: `extract_fw.py` (OTA → partitions, CRC check), `repack_fw.py` (same-size partition swap + custom CRC-32 poly `0x681bb522`, offline), `extract_coolflux.py`, `decompress_stage0_data.py` (stage0 `.data` init image). Python: `.venv/bin/python`; Ghidra 12.2 + JDK under `.toolchain/`.

## Writing findings
- One bullet per fact, in the topic file: **claim — evidence (addresses) — tag**. Tags: `[live]` observed on device, `[static]` read from code, `[hyp]` hypothesis. Skip hedging prose. The tag carries the confidence.
- When a fact supersedes an old one, edit or delete the old bullet rather than appending a contradiction.
- Update `docs/STATUS.md` (questions answered or opened, next actions) in the same change.
- Commit after each coherent finding: `<Verb> <what>` subject, short body.

## Multi-agent workflow
The main session is the **lead**. It owns `docs/STATUS.md`, picks the questions, and merges findings. It delegates independent, well-scoped questions in parallel to subagents in `.claude/agents/`:
- `fw-tracer` (Sonnet): answers one concrete static question ("who writes `0x20000538+0xc`?", "what does `[main] 0x43184` send?") from the index. Returns tagged bullets and does not edit docs.
- `patch-engineer`: designs and builds offline patches (Thumb asm, same-size, `repack_fw.py`), verifies them by disassembly and diffing, and writes `patches/<name>/`. Never flashes.
- `dsp-reverser`: long-running CoolFlux BSP32 ISA and `player` path work on `part2`.
- `device-prober` (Sonnet): runs the approved read-only live probes with the user and reports raw observations.

Brief each subagent with the exact question, the addresses already known, and what is ruled out. Ask for findings only, not narrative. Two tracers must never edit the same doc. The lead does all doc edits.
