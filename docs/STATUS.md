# Status board

_Lead-owned. Updated 2026-11-02._

## Where we are
- Stock service mode lives in **stage0**: `0x901` → `0x806` → USB setup `[stage0] 0x4fdc4` (IPC ch `0x10`, 48 kHz/16-bit, `0xc0`-byte blocks), then `[stage0] 0x4f278` = `0x4f510(0, 1, 0x20)`. The EQ config sender `[stage0] 0x43184` (ch **`0x0a`** via `0x4f588`, handle `0x20000518`) is **not** called on this path. `[static]`
- **Ch `0x11` cmd 2 is a DSP level/volume command, not a route switch.** Its only sender is `[stage0] 0x4f510(_, sub, val)`. sub 1 = set level: USB start sends 32, `0x59dd8` restores a saved level on `0x906`, the CDC `AT+HMDevVOL=` sends 0..16, and the ramp `0x578b0` steps toward `0x20000258[0]`. sub 2/3 = step up/down, from events `0xf05`/`0xf06` in `0x4f7c8`. `[static]` What sub 1 = 32 means on the DSP scale (above the AT range of 16) is unknown. `[hyp]`
- So stage0 already has a volume-control primitive. Restoring Vol± in USB mode may only need key events → `0xf05`/`0xf06` (or `0x4f510(…,2|3,0)`). `[hyp]`
- In service mode: no button action, CDC silent (including with the KIN diag gate on), no BLE advertising, and UAC volume is a dummy RAM table. `[live]`
- Codex's offline candidate (`patches/go4-0640-usb-controls`) is **not adopted**. It patches stage0, drops `0x4d6fc`'s body, and sends keys to the host instead of the speaker. Rationale: findings/usb-mode.md.
- Normal-mode volume path is mapped in main (`0x928c0` → `0x8cd2c` → `0x8e128`/`0x8deb4`), but the final gain consumer is unknown. `[static]`
- Offline OTA rebuild works (custom CRC). The host-side OTA handshake isn't mapped yet, and recovery isn't proven (Q5), so nothing can be live-tested.
- **Flash is A/B banked.** OTA IDs 1 (stage0), 2 (main) and 3 (DSP) live in slots {0,1,2} or {4,5,6}. ID 6 (part3) is a fixed slot. The bank selector at flash `0x3000` holds magic `0x5aa5`, two u16 sequence counters and a flag byte `+3`. OTA writes to the inactive bank, checks the CRC per partition, and only on apply (opcode `0x4d` → `0x597a0` → `0x40fb8`) bumps the counter, sets `+3 = 1` and resets. `[static]`
- **No boot-time image verification exists in stage0 or main.** Bank choice and any rollback must be done by an unseen mask ROM at `0x400000` (main's NMI handler lives there). Nothing in either image clears flag `+3`, so it may be a ROM "trial boot" flag, but that's unproven. `[hyp]`
- **Rule: only ever send a full 4-partition container** with unchanged stage0, DSP and part3. A main-only OTA would flip to a bank holding stale or blank stage0/DSP. `[static]`+`[hyp]`
- CDC has no firmware-write command, so it can't be a recovery channel. The full AT list is in `docs/findings/cdc-at-commands.md`. `[static]`
- **Dual core, concurrent:** stage0 = core 0 (USB, power, button scanner, OTA, DSP level/EQ requests), main = core 1 (BT stack in mask ROM, app, DSP mailbox). The IPC channels (ch `0x0a` EQ, `0x10` USB stream, `0x11` level, `0x12` power/mode) go core0→core1, **so main sits on the far end of the USB audio path too.** Main stays alive in service mode. `[static]` Details: findings/firmware-images.md.
- **USB audio is a separate boot mode.** The Play+BT chord toggles the persisted flag `cfg[4]` and powers off. The next boot sets PowerOffStatus byte0=2, and 25 stage0 checks of `0x59a14()==2` then strip features. In that mode the key filter (`[stage0] 0x4d682`) passes only `0xa01`/`0x600`, so Vol± are dropped. `[static]` Details: findings/usb-mode.md.
- Buttons: stage0 scanner → key table → filter `0x4d674` → events. Masks `0x20`/`0x40` → `0xf05`/`0xf06` → ch-`0x11` level step (probably Vol±). In service mode, either the scanner never starts (`0x200010b8+9`) or the filter drops everything. `[static]`/`[hyp]` Details: findings/buttons.md.

## Strategy
**Goal (user, 2026-11-02): USB mode should behave exactly like Bluetooth mode, just over USB** (same DSP chain/EQ, buttons, volume).
Q1 shows both cores keep running, and Q4b shows USB mode is a stripped boot mode (byte0==2). **Preferred plan (A'):** keep a normal boot (byte0≠2, so BT app, keys and EQ all intact) and start the existing USB audio path (`0x806` → `0x4fdc4`) when a USB host is attached, relaxing the `byte0==2` condition in `[stage0] 0x59e32`. Then make sure main routes that stream through the A2DP-equivalent DSP chain (Q3). Fallback (B): stay in the boot mode and whitelist keys plus resend EQ. Earlier framing: make main treat the USB stream like an A2DP source (same DSP setup and EQ), and make the stage0 key filter pass keys in USB mode. Both are probably small, targeted patches. Original framing:
- **A. USB in normal mode**: keep the main app running (buttons, EQ policy) and start the existing USB audio path (`0x806` setup) from normal operation, so PCM flows into the processed route. Preferred if service mode turns out to stop or bypass main.
- **B. Upgrade service mode**: after `0x806`, also send the EQ profile (`0x43184`, ch `0x0a`) and let keys through the stage0 filter so Vol± reaches `0xf05`/`0xf06` → ch-`0x11` steps on the speaker itself. This is now folded into the plan above.

Either way, a patch should touch as little as possible and should leave the recovery path (Q5) intact.

## Open questions
| # | Question | Start from | Owner |
|---|---|---|---|
| ~~Q1~~ | Answered: dual core, concurrent, IPC via shared RAM `0x20010000` + doorbell. Main stays alive in service mode `[hyp, strong]` | — | — |
| ~~Q2~~ | Answered: ch `0x11` cmd 2 = level set/step (see above). Follow-ups: who posts `0xf05`/`0xf06`; ramp target writer `0x20000258[0]`; `0x59550` and gate `*DAT_43248+10` inside `0x43184` | `[stage0] 0x4f7c8`, `0x578b0`, `0x43184` | — |
| Q3 | **Main side of the USB stream:** which main handler serves IPC ch `0x10` (cmds 7/2/3/8) and how does it feed the DSP? How does that differ from A2DP stream start (DSP route, EQ/effects setup, ch `0x0a` handling)? | `[main]` IPC table `0xb1f05`, DSP mailbox `0x157b0`/`0xb0970`/`0x7d4fc`, App Task DSP `0x76028` | tracer (round 2) |
| ~~Q4~~ | Answered (gate = `0x4d682` whitelist in byte0==2 mode). Old row: Pipeline mapped. Still open: which filter condition or scanner gate kills keys in service mode? Who writes runs +0/+9/+0xd (`[main] 0x2c644`) and the filter bytes, and what are their values after the Play+BT chord? | `[stage0] 0x4d674`, `0x4cd8c`; `[main] 0x2c644` | tracer (round 2) |
| Q8 | Classify all 25 `0x59a14()==2` checks: what each disables/enables, and what normal boot needs to start USB audio (conditions in `0x59e32`, `0x51620`/`0x4f4d2`, `0x57128`) | the list in findings/usb-mode.md | tracer (round 2) |
| Q5 | Partly answered (A/B, see above). Still open: does ROM roll back when the new bank fails to boot? Is there a watchdog (reset reg `*0x45e0c` in `0x4a154`)? Does OTA work from normal mode (`0x519f8` needs `0x4f4d2` ∈ {2,3})? If stage0 survives a main crash (Q1), BLE re-flash = recovery | `[stage0] 0x40fb8`, `0x4a154`, `0x4f4d2`; ROM `0x400000` | — |
| Q6 | Host-side OTA handshake over BLE (`0x43` setup, 12-byte payload, `0x44` data…), static only | `[stage0] 0x57dcc`, `0x519f8`, `0x59494` | — |
| Q7 | CoolFlux P-section ISA; where EQ (`setAdjustGain`, `VDSP_SetAlgParam*`) is applied in `player` | `captures/coolflux0640/` | — |
| P1 | (secondary) Which reason-6 power-off fires on the plugged-in shutdown? | `[stage0] 0x59328`, `0x50d30` | — |

## Next round
Round 2 (running): Q3 (main-side USB vs A2DP DSP route) and Q4 (service-mode key gate). Then patch-engineer drafts a candidate (full container; prefer main-side changes; stage0 changes only if the key filter requires them). Q7 (DSP ISA) is deferred unless the ARM side can't explain the EQ gap. P1 stays separate. Don't touch charging or battery cutoff logic.
