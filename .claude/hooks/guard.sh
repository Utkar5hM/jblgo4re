#!/usr/bin/env bash
# PreToolUse guard: block commands that could change device state. The session often runs
# with permissions bypassed, so this is the last line of defence for the speaker.
cmd="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))')"
deny() { echo "BLOCKED by .claude/hooks/guard.sh: $1. Ask the user to run it themselves (prefix with !) if intended." >&2; exit 2; }
# AT names only matter when the command can actually transmit (python/pyusb/serial/device node),
# so docs edits that merely mention them are allowed.
if grep -qiE 'python|\.py\b|pyusb|usb\.core|/dev/(tty|bus/usb)|serial|socat|screen|minicom' <<<"$cmd"; then
  grep -qiE 'HMPowerOff|HMReset|HMDevUpd|HMDevFAC|HMDevHDO|HMDevLeDUT|HMDevDUT|HMDevSwitchAC|HMDevPwrLD|HMDev(CLW|bpW|SNW)|HMCusWrite|GPFPSW|GFPSWrite|AT\+HM(Set|Wr|Erase)' <<<"$cmd" \
    && deny "state-changing AT command"
fi
grep -qiE '(^|[^a-z])(dfu-util|flashrom|openocd|pyocd|st-flash|esptool)' <<<"$cmd" && deny "flashing tool"
grep -qiE 'tools/[a-z_]*(flash|ota_send|ota_upload|dfu)[a-z_]*\.py' <<<"$cmd" && deny "OTA/flash script"
grep -qiE 'aa ?4[3-9a-e] ' <<<"$cmd" && grep -qiE 'ble|bleak|gatt' <<<"$cmd" && deny "BLE OTA opcode 0x43-0x4e"
grep -qE 'git (add|commit).*captures/' <<<"$cmd" && deny "committing captures/ (firmware is not redistributable)"
exit 0
