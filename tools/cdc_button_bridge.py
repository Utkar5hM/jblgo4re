#!/usr/bin/env python3
"""Map patched Go 4 CDC key reports to Linux USB-audio controls.

Requires the offline stage0 patch candidate from build_usb_controls_patch.py.
This program only reads the speaker's CDC IN endpoint; it does not send USB
commands. Supply observed key-code mappings with repeated --map options.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time

import usb.core
import usb.util

from cdc_version import FRAME_SIZE, IN_ENDPOINT, INTERFACE, PID, VID, crc16_ccitt


KEY_RE = re.compile(rb"AT\+HMDevKEY=(\d{2})")
SINK_RE = re.compile(r"^\s*[│├└─ ]*\*?\s*(\d+)\.\s+.*JBL Go 4.*\[vol:", re.I)


def decode_frames(buffer: bytearray):
    """Yield complete valid 60-byte firmware frames and retain a partial tail."""
    while True:
        marker = buffer.find(b"\x0f\xf0")
        if marker < 0:
            keep = 1 if buffer.endswith(b"\x0f") else 0
            if keep:
                if len(buffer) > 1:
                    del buffer[:-1]
            else:
                buffer.clear()
            return
        if marker:
            del buffer[:marker]
        if len(buffer) < FRAME_SIZE:
            return
        frame = bytes(buffer[:FRAME_SIZE])
        length = int.from_bytes(frame[2:4], "little")
        if length > FRAME_SIZE - 6:
            del buffer[0]
            continue
        expected_crc = int.from_bytes(frame[58:60], "little")
        if crc16_ccitt(frame[:58]) != expected_crc:
            del buffer[0]
            continue
        yield frame[4:4 + length]
        del buffer[:FRAME_SIZE]


def run(*args: str) -> str:
    result = subprocess.run(args, check=True, text=True, capture_output=True)
    return result.stdout


def find_go4_sink() -> str:
    status = run("wpctl", "status")
    in_sinks = False
    for line in status.splitlines():
        if re.match(r"\s*[├└]─ Sinks:", line):
            in_sinks = True
            continue
        if in_sinks and re.match(r"\s*[├└]─ ", line):
            break
        match = SINK_RE.match(line)
        if in_sinks and match:
            return match.group(1)
    raise RuntimeError("no JBL Go 4 sink found; pass --sink-id explicitly")


def adjust_volume(sink_id: str, delta: str) -> None:
    run("wpctl", "set-volume", sink_id, delta)


def play_pause() -> None:
    listing = run("busctl", "--user", "--no-pager", "--list")
    names = sorted({
        line.split()[0]
        for line in listing.splitlines()
        if line.startswith("org.mpris.MediaPlayer2.")
    })
    if not names:
        raise RuntimeError("no MPRIS media player is available on this desktop")
    players = []
    for name in names:
        try:
            status = run(
                "busctl", "--user", "get-property", name, "/org/mpris/MediaPlayer2",
                "org.mpris.MediaPlayer2.Player", "PlaybackStatus",
            )
        except subprocess.CalledProcessError:
            continue
        players.append(("Playing" in status, name))
    if not players:
        raise RuntimeError("no MPRIS player exposes PlaybackStatus")
    _, name = next((p for p in players if p[0]), players[0])
    run("busctl", "--user", "call", name, "/org/mpris/MediaPlayer2",
        "org.mpris.MediaPlayer2.Player", "PlayPause")


def parse_map(values: list[str]) -> dict[bytes, str]:
    mapping: dict[bytes, str] = {}
    allowed = {"volume_up", "volume_down", "play_pause"}
    for value in values:
        try:
            key, action = value.split("=", 1)
        except ValueError as error:
            raise ValueError(f"invalid mapping {value!r}; expected CODE=ACTION") from error
        if not re.fullmatch(r"\d{2}", key):
            raise ValueError(f"invalid key code {key!r}; use the two digits from HMDevKEY")
        if action not in allowed:
            raise ValueError(f"unsupported action {action!r}; choose from {', '.join(sorted(allowed))}")
        mapping[key.encode("ascii")] = action
    return mapping


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", action="append", default=[], metavar="CODE=ACTION",
                        help="observed HMDevKEY code mapping; repeat as needed")
    parser.add_argument("--sink-id", help="PipeWire sink ID (default: discover JBL Go 4)")
    args = parser.parse_args()
    try:
        mapping = parse_map(args.map)
    except ValueError as error:
        parser.error(str(error))
    if not mapping:
        print("Listening only. Add --map CODE=volume_up|volume_down|play_pause to enable actions.",
              flush=True)

    device = usb.core.find(idVendor=VID, idProduct=PID)
    if device is None:
        parser.error("Go 4 service-mode device 0ac8:bb91 is not connected")
    device.get_active_configuration()
    if device.is_kernel_driver_active(INTERFACE):
        parser.error("interface 3 has a kernel driver; refusing to detach it")
    try:
        usb.util.claim_interface(device, INTERFACE)
    except usb.core.USBError as error:
        parser.error(f"cannot claim CDC interface 3: {error}")

    try:
        sink_id = args.sink_id or find_go4_sink()
        print(f"Reading Go 4 CDC reports; PipeWire sink ID {sink_id}. Ctrl-C to exit.", flush=True)
        buffer = bytearray()
        while True:
            try:
                chunk = bytes(device.read(IN_ENDPOINT, 64, timeout=500))
            except usb.core.USBTimeoutError:
                continue
            buffer.extend(chunk)
            for payload in decode_frames(buffer):
                match = KEY_RE.search(payload)
                if not match:
                    print(f"CDC {payload!r}", flush=True)
                    continue
                code = match.group(1)
                action = mapping.get(code)
                print(f"key {code.decode()}" + (f" -> {action}" if action else ""), flush=True)
                try:
                    if action == "volume_up":
                        adjust_volume(sink_id, "5%+")
                    elif action == "volume_down":
                        adjust_volume(sink_id, "5%-")
                    elif action == "play_pause":
                        play_pause()
                except (RuntimeError, subprocess.CalledProcessError) as error:
                    print(f"action failed: {error}", file=sys.stderr, flush=True)
            time.sleep(0.001)
    except KeyboardInterrupt:
        return 0
    finally:
        usb.util.release_interface(device, INTERFACE)
        usb.util.dispose_resources(device)


if __name__ == "__main__":
    raise SystemExit(main())
