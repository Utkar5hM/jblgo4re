#!/usr/bin/env python3
"""Reconstruct the Go 4 stage-0 initialized RAM block from its boot stream.

The decoder follows the Thumb routine at 0x400ac in the 0.6.4.0 stage-0
image. Defaults are for that release and may differ in another image.
"""

import argparse
from pathlib import Path


def decode(blob: bytes, source_offset: int, output_size: int):
    position = source_offset
    output = bytearray()
    while len(output) < output_size:
        first = blob[position]
        position += 1
        literal_count = first & 7
        if literal_count == 0:
            literal_count = blob[position]
            position += 1
        run = first >> 4
        if run == 0:
            run = blob[position]
            position += 1
        count = literal_count - 1
        if count < 0 or position + count > len(blob):
            raise ValueError("invalid literal run")
        output.extend(blob[position:position + count])
        position += count
        if first & 8:
            distance = blob[position]
            position += 1
            if distance == 0 or distance > len(output):
                raise ValueError("invalid back reference")
            for _ in range(run + 2):
                output.append(output[-distance])
        else:
            output.extend(bytes(run))
        if len(output) > output_size:
            raise ValueError("decoded stream exceeds expected RAM size")
    return bytes(output), position


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage0", type=Path)
    parser.add_argument("--source-address", type=lambda x: int(x, 0), default=0x5E1A0)
    parser.add_argument("--load-address", type=lambda x: int(x, 0), default=0x40000)
    parser.add_argument("--size", type=lambda x: int(x, 0), default=0x760)
    parser.add_argument("--output", type=Path, default=Path("captures/stage0_0640_ram_init.bin"))
    args = parser.parse_args()
    data, end = decode(args.stage0.read_bytes(), args.source_address - args.load_address, args.size)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    print(f"decoded {len(data)} bytes; source ends at 0x{end + args.load_address:x}; output {args.output}")


if __name__ == "__main__":
    main()
