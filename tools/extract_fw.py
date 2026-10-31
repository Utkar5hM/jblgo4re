#!/usr/bin/env python3
"""Extract an HMHEADER9 Go 4 OTA container for static analysis."""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys


EXPECTED_SHA256 = "2f440402006a65d29778075021e58cb174cf20626920187acfe0faaee75a5d19"
PARTITION_NAMES = {1: "stage0_40000", 2: "main_00000", 3: "part2_unknown", 6: "part3_unknown"}


def extract(source: Path, output: Path):
    blob = source.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    if digest != EXPECTED_SHA256:
        print(f"warning: unstudied image SHA-256 {digest}; inspect all metadata before using it", file=sys.stderr)
    if not blob.startswith(b"HMHEADER9"):
        raise ValueError("missing HMHEADER9")

    count = blob[0x10]
    if count == 0 or count > 16:
        raise ValueError(f"implausible partition count {count}")
    descriptors = []
    for number in range(count):
        part_id, length, parameter, integrity_word = struct.unpack_from("<BIII", blob, 0x11 + 13 * number)
        descriptors.append((part_id, length, parameter, integrity_word))

    cursor = 0x11 + 13 * count
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"source": str(source), "sha256": digest, "partitions": []}
    for number, (part_id, length, parameter, integrity_word) in enumerate(descriptors):
        name = PARTITION_NAMES.get(part_id, f"part{number}_type{part_id}")
        if blob[cursor:cursor + 8] != b"PARTHMDT":
            raise ValueError(f"partition {number} marker missing at 0x{cursor:x}")
        start = cursor + 8
        data = blob[start:start + length]
        if len(data) != length:
            raise ValueError(f"partition {number} truncated")
        path = output / f"{name}.bin"
        path.write_bytes(data)
        item = {
            "name": name,
            "file": str(path),
            "file_offset": f"0x{start:x}",
            "size": f"0x{length:x}",
            "partition_id": part_id,
            "parameter_unknown": f"0x{parameter:08x}",
            "integrity_word_unknown": f"0x{integrity_word:08x}",
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        if part_id in (1, 2):
            stack, reset = struct.unpack_from("<II", data)
            item.update({
                "initial_stack": f"0x{stack:08x}",
                "reset_vector": f"0x{reset:08x}",
                "load_address": "0x40000" if part_id == 1 else "0x0",
            })
        manifest["partitions"].append(item)
        cursor = start + length
    if blob[cursor:] != b"FOOTERHM":
        raise ValueError(f"unexpected tail at 0x{cursor:x}")
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=Path("captures/firmware"))
    args = parser.parse_args()
    extract(args.source, args.output)


if __name__ == "__main__":
    main()
