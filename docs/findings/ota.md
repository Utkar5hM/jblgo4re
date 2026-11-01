# OTA container, CRC, receive path

_Migrated verbatim from RE_NOTES.md on 2026-11-02; tighten bullets when touched. Addresses are 0.6.4.0 unless marked 0600._

Container SHA-256: `2f440402006a65d29778075021e58cb174cf20626920187acfe0faaee75a5d19`. The file begins with `HMHEADER9`, has four `PARTHMDT` partitions, and ends with `FOOTERHM`.

The byte at header offset `0x10` is the partition count (`4`). Four 13-byte descriptors follow at `0x11`; each parses as a one-byte partition ID and three little-endian 32-bit fields: length, a still-unknown parameter, and a **custom CRC-32** of the partition payload. IDs are `1, 2, 3, 6`. Stage-0 function `0x43d4e` initializes the CRC to `0xffffffff`, feeds data through table function `0x44568`, and complements the result. The table at `0x5dc14` is a reflected CRC with polynomial `0x681bb522`. All four descriptor values match the computed CRC in both 0600 and 0.6.4.0, including the identical CRCs of three substantially different partitions. Standard zlib CRC-32 uses another polynomial and therefore does not match. `tools/extract_fw.py` now validates all four CRCs as well as markers and footer.

`tools/repack_fw.py` replaces one partition with data of the same length, updates its CRC in the header, and verifies the resulting container. Replacing stage 0 with identical bytes reproduced the official 0.6.4.0 OTA byte for byte (SHA-256 `56867f41...`); a one-byte test edit generated a new CRC and passed offline extraction. These checks establish the outer container format only. The device's board checks, flash mapping, boot behavior, and recovery path remain to be verified before a modified image is sent.

The same BLE command dispatcher that answered the live version query handles OTA-related opcodes. In stage 0, `0x57dcc` routes `0x43` to transfer setup `0x519f8` and `0x44` to a queued data path; `0x47`, `0x48`, `0x4a`, `0x4d`, and `0x4e` handle additional control/status operations. The setup path requires a 12-byte payload and checks the device mode through `0x4f4d2` before starting. Queued chunks reach `0x59494`, which checks sequence numbers and passes bytes to container parser `0x52dc4`. That parser recognizes `HMHEADER`, `PARTHMDT`, and `FOOTERHM`, and calls flash callback `0x5bc24`. The callback writes through `0x52460`/`0x53b50`; completion uses `0x41470` to compare a custom CRC of the written flash contents with the descriptor value. This is a static map, not a validated host-side update sequence. No update command was sent to the live speaker.

## Flash banking and commit (round 1, 2026-11-02)
- OTA IDs 1/2/3 map to A/B slots {0,1,2} or {4,5,6}. ID 6 is fixed slot 3. IDs 10/0x11/0x12 map to slots 9/7/8. — `[stage0] 0x4132c`, `0x41388` (slot table `0x200007a4+0x40+slot*0x20`) — [static]
- Bank selector is at flash `0x3000`: magic `0x5aa5`, flag byte `+3`, u16 counters `+4`/`+6`, CRC16 `+8`. The writer targets the bank with the lower counter. — `[stage0] 0x43c3c` — [static]
- Apply (opcode `0x4d`) → `0x597a0`: slots get status 3, user data is copied (`0x53ed4`), then `0x40fb8` bumps the lower counter to higher+1, sets `+3=1`, rewrites `0x3000` (single copy), and resets via `0x4a154(1)`. — [static]
- In-progress status 7 is written by `0x41138` to a record at flash `0x3ff100`. Nothing in stage0 or main reads status or clears `+3`, so the consumer is probably the mask ROM (`0x400000`). — [static] writer / [hyp] consumer
- The descriptor's "unknown parameter" is a per-partition version stored at slot `+0x48` by `0x414b0` (e.g. `0x00040600` = 0.6.4.0). No downgrade check was found. — [static]
- Per-partition CRC32 is checked only at OTA completion (`0x41470`). The slot table is then rewritten to sectors `0x0000` and `0x1000` (redundant). No boot-time image CRC exists in either image. — [static]
- **A main-only container would flip to a bank holding stale or blank stage0/DSP, so always send all 4 partitions.** — [static]+[hyp]
- The OTA control path (0xAA-framed `0x57774` → `0x57dcc`) lives only in stage0. Setup `0x519f8` needs `0x4f4d2()` ∈ {2,3}. — [static]
- No watchdog kick pattern was found. Software reset is `0x4a154` (register at `*0x45e0c`). Deliberate infinite hangs: `0x4f614`, `0x4f64c`, `0x49490`. — [static]

## In-partition integrity fields (2026-11-02)
- Each ARM partition ends with a 28-byte metadata block right before its `0xff` padding. stage0 `[stage0] 0x5e39c`: `u32 code_len=0x1e39c`, **`u32 go4crc(0x40000..0x5e39b)=0xf798464c`** (verified), then `00 06 03 03`…, build date `19 07 11 0a 04 2d` (2025-07-17 10:04:45), and `2e 00`. Main has the same layout at `[main] 0xd50cc` (date 2025-07-16 20:32:41). **Any code patch must recompute this CRC.** No reader exists in stage0 or main; the mask ROM is the suspected checker. — [static]
- Every partition (including part2 and part3) also ends with a 4-byte trailer (stage0 `c7 84 9e d1`, main `4b 05 00 32`). It doesn't match go4, IEEE or CRC32C (any reflect/init/xorout), adler32, a byte sum, md5/sha1/sha256 prefixes, or a forcing word to a constant residue over any sensible range. **Unidentified; keep it byte-identical.** — [static, negative]
- go4crc over the whole partition including the trailer = the OTA descriptor CRC (the known outer check). — [static]
- part3 (ID 6, 32 KiB) is high-entropy up to the last byte. It might be keys/signature or encrypted data. Unknown. — [hyp]
