#!/usr/bin/env python3
"""Read-only Go 4 host probe. Emits JSON snapshots or JSONL samples."""

import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys
import time


def run(*argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=8, check=False)
        return result.stdout if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def bluetooth():
    devices = run("bluetoothctl", "devices") or ""
    matches = []
    for line in devices.splitlines():
        match = re.match(r"Device ([0-9A-F:]{17}) (.*)", line)
        if match and "go 4" in match.group(2).lower():
            info = run("bluetoothctl", "info", match.group(1)) or ""
            fields = {}
            for key in ("Connected", "Paired", "Trusted"):
                found = re.search(rf"^\s*{key}: (yes|no)$", info, re.MULTILINE)
                fields[key.lower()] = found.group(1) == "yes" if found else None
            matches.append({"name": match.group(2), **fields})
    return matches


def pipewire():
    raw = run("pw-dump")
    if raw is None:
        return {"error": "pw-dump unavailable"}
    try:
        objects = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "pw-dump returned invalid JSON"}
    nodes = []
    links = []
    for obj in objects:
        info = obj.get("info") or {}
        props = info.get("props") or {}
        if obj.get("type") == "PipeWire:Interface:Node":
            media_class = props.get("media.class", "")
            if media_class in ("Audio/Sink", "Stream/Output/Audio"):
                nodes.append({
                    "id": obj.get("id"),
                    "name": props.get("node.name"),
                    "description": props.get("node.description") or props.get("media.name"),
                    "class": media_class,
                    "state": info.get("state"),
                    "profile": props.get("api.bluez5.profile"),
                    "codec": props.get("api.bluez5.codec"),
                    "target": props.get("target.object"),
                })
        elif obj.get("type") == "PipeWire:Interface:Link":
            links.append({
                "output_node": info.get("output-node-id"),
                "input_node": info.get("input-node-id"),
                "state": info.get("state"),
            })
    return {"nodes": nodes, "links": links, "wpctl_status": run("wpctl", "status")}


def usb():
    result = []
    root = pathlib.Path("/sys/bus/usb/devices")
    for path in sorted(root.iterdir()) if root.exists() else []:
        vendor = path / "idVendor"
        product = path / "idProduct"
        if not vendor.exists() or not product.exists():
            continue
        try:
            result.append({
                "path": path.name,
                "vid": vendor.read_text().strip(),
                "pid": product.read_text().strip(),
                "manufacturer": (path / "manufacturer").read_text().strip() if (path / "manufacturer").exists() else None,
                "product": (path / "product").read_text().strip() if (path / "product").exists() else None,
            })
        except OSError:
            continue
    return result


def snapshot():
    return {
        "time_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "bluetooth": bluetooth(),
        "audio": pipewire(),
        "usb": usb(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=5, help="seconds between samples; 0 means one snapshot")
    parser.add_argument("--duration", type=float, default=0, help="stop after N seconds; 0 means run until Ctrl-C")
    parser.add_argument("--output", type=pathlib.Path, help="JSONL file (default: stdout)")
    args = parser.parse_args()
    if args.interval < 0 or args.duration < 0:
        parser.error("interval and duration must be nonnegative")
    stream = None
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        stream = args.output.open("a", encoding="utf-8")
    else:
        stream = sys.stdout
    start = time.monotonic()
    try:
        while True:
            print(json.dumps(snapshot(), separators=(",", ":")), file=stream, flush=True)
            if args.interval == 0 or (args.duration and time.monotonic() - start >= args.duration):
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        if args.output:
            stream.close()


if __name__ == "__main__":
    main()
