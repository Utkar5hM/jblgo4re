#!/usr/bin/env python3
"""Print state changes from a Linux or Windows probe JSONL file."""

import argparse
import json
import pathlib


def state(sample):
    if "bluetooth" in sample:  # Linux
        speakers = sample["bluetooth"]
        connected = any(device.get("connected") for device in speakers)
        audio = sample.get("audio") or {}
        nodes = audio.get("nodes") or []
        sink = next((node for node in nodes if node.get("class") == "Audio/Sink" and "go 4" in (node.get("description") or "").lower()), None)
        sink_id = sink.get("id") if sink else None
        streams = sum(1 for link in audio.get("links") or [] if link.get("input_node") == sink_id) if sink_id is not None else 0
        usb = {f"{d.get('vid')}:{d.get('pid')} {d.get('product') or ''}" for d in sample.get("usb") or []}
        return {"connected": connected, "sink": sink.get("state") if sink else None, "streams_to_go4": streams, "usb": usb}

    devices = sample.get("pnp_devices") or []  # Windows
    go4 = [device for device in devices if "go 4" in (device.get("FriendlyName") or "").lower()]
    usb = {f"{d.get('FriendlyName')} [{d.get('InstanceId')}]" for d in devices if d.get("Class") == "USB"}
    return {"go4_pnp": [(d.get("Class"), d.get("Status")) for d in go4], "usb": usb}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=pathlib.Path)
    args = parser.parse_args()
    previous = None
    with args.log.open(encoding="utf-8-sig") as stream:
        for number, line in enumerate(stream, 1):
            try:
                sample = json.loads(line)
            except json.JSONDecodeError as error:
                print(f"line {number}: invalid JSON ({error})")
                continue
            current = state(sample)
            if current != previous:
                print(sample.get("time_utc", f"line {number}"))
                for key, value in current.items():
                    if key == "usb":
                        if previous is None:
                            print(f"  usb present: {sorted(value)}")
                        else:
                            for device in sorted(value - previous["usb"]):
                                print(f"  usb added: {device}")
                            for device in sorted(previous["usb"] - value):
                                print(f"  usb removed: {device}")
                    elif previous is None or value != previous.get(key):
                        print(f"  {key}: {value}")
            previous = current


if __name__ == "__main__":
    main()
