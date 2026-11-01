#!/usr/bin/env python3
"""Inspect and extract X/Y/P memory sections from the Go 4 CoolFlux image."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys


MAGIC = bytes.fromhex("a5 5a 5a a5")
SECTIONS = (
    ("X", 0x14, 0x18),
    ("Y", 0x28, 0x2C),
    ("P", 0x3C, 0x40),
)
SECTION_NAMES = {
    "X": b"proj_bsp32.X",
    "Y": b"proj_bsp32.Y",
    "P": b"proj_bsp32.P",
}


def inspect_image(path: Path) -> tuple[bytes, list[dict[str, int | str]]]:
    image = path.read_bytes()
    if len(image) < 0x44 or image[:4] != MAGIC:
        raise ValueError("not a Go 4 CoolFlux image (bad magic or truncated header)")

    sections: list[dict[str, int | str]] = []
    for name, offset_field, size_field in SECTIONS:
        offset, size = struct.unpack_from("<II", image, offset_field)
        end = offset + size
        if size == 0 or offset < 0x44 or end > len(image):
            raise ValueError(
                f"invalid {name} section bounds: offset=0x{offset:x}, "
                f"size=0x{size:x}, image=0x{len(image):x}"
            )
        sections.append({"name": name, "offset": offset, "size": size, "end": end})

    by_offset = sorted(sections, key=lambda section: int(section["offset"]))
    for left, right in zip(by_offset, by_offset[1:]):
        if int(left["end"]) > int(right["offset"]):
            raise ValueError(f"overlapping {left['name']} and {right['name']} sections")

    for name, _, _ in SECTIONS:
        if SECTION_NAMES[name] not in image[:0x200]:
            raise ValueError(f"section-name marker for {name} is missing")

    return image, sections


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="extracted part2_unknown.bin")
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="write coolflux_X.bin, coolflux_Y.bin, and coolflux_P.bin here",
    )
    args = parser.parse_args()

    try:
        image, sections = inspect_image(args.image)
        if args.out_dir:
            args.out_dir.mkdir(parents=True, exist_ok=True)

        report: dict[str, object] = {
            "image": str(args.image),
            "image_size": len(image),
            "image_sha256": hashlib.sha256(image).hexdigest(),
            "sections": [],
        }
        for section in sections:
            name = str(section["name"])
            offset = int(section["offset"])
            size = int(section["size"])
            payload = image[offset : offset + size]
            entry: dict[str, object] = {
                **section,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            if args.out_dir:
                output = args.out_dir / f"coolflux_{name}.bin"
                output.write_bytes(payload)
                entry["file"] = str(output)
            report["sections"].append(entry)  # type: ignore[union-attr]

        print(json.dumps(report, indent=2))
        return 0
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
