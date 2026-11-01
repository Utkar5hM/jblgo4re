# CDC AT command set (stage0 0.6.4.0)

Parser `[stage0] 0x4d71c` prefix-compares commands with `0x59954`. Frames are 60 bytes: `0f f0`, a u16 length, the payload, then CRC-16/CCITT. The commands have no live replies in service mode so far. `[static]`

- **Query/diag:** HMDevHDI, HMDevVER, HMDevMAC, HMDevBAT, HMDevBATAd, HMDevT, HMDevNtcAd, HMDevChgIcNtc2State, HMDevRSSI, HMDevNAME, HMDevODM, HMDevCLRE, HMDevSNRE, HMDevbpR, HMDevbpmR, HMCusRead, GPFPSRead, HMRetAnalytics, HMReadPoweron, HMReadPlayback
- **Write/set (config, not image slots):** HMDevCLW=, HMDevbpW=, HMDevSNW=, HMCusWrite, GPFPSW, GFPSWriteModelId
- **State/control:** HMDevHDO (power-off, reason 7), HMDevFAC (`0x51448`, factory reset + power-off reason 5), HMDevPair, HMDevWON, HMDevRON, HMDevROFF, HMDevPwrLDON, HMDevPwrLDOFF, HMDevKIN/KOF (diag key gate `0x200004e8`), **HMDevVOL=** (0..16 → `0x4f510(0,1,val)`, ch `0x11` level), HMMuteNone/High/Low/All, HMPowerOff, HMDevSwitchAC
- **Test modes:** HMDevDUT (`0x4f614(0x1f)`), HMDevLeDUT (`0x4f614(0xe9)`, hangs forever after 500 ms)
- **Output-only strings (not parsed):** HMDevKEY, HMDevColor, HMDevNtc2State, GDPSModelID, HMDevBT
- No firmware write/erase/update command exists, so CDC is not a recovery channel. `[static]`

**Live-safety:** HDO, FAC, PowerOff, DUT/LeDUT, SwitchAC, Pwr*, and every write/set command change device state. They are forbidden without explicit user approval (see CLAUDE.md). `.claude/hooks/guard.sh` blocks them in any command that could transmit.
