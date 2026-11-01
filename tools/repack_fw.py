#!/usr/bin/env python3
"""Offline Go 4 OTA repacker for a same-size replacement partition.

This tool never talks to a speaker. It validates every source partition,
replaces exactly one partition, updates its custom CRC, and validates the
output before writing it. A rebuilt image is not proof that the bootloader
will accept or safely install it.
"""

import argparse
from pathlib import Path
import struct

from extract_fw import go4_crc32


def partitions(blob: bytes):
    if not blob.startswith(b"HMHEADER9") or len(blob) < 0x11:
        raise ValueError("missing HMHEADER9")
    count = blob[0x10]
    if not 1 <= count <= 16:
        raise ValueError(f"invalid partition count {count}")
    cursor = 0x11 + count * 13
    if cursor > len(blob):
        raise ValueError("truncated descriptor table")
    result = []
    for number in range(count):
        descriptor = 0x11 + number * 13
        part_id, length, parameter, expected_crc = struct.unpack_from("<BIII", blob, descriptor)
        if blob[cursor:cursor + 8] != b"PARTHMDT":
            raise ValueError(f"missing marker before partition {number}")
        start = cursor + 8
        end = start + length
        if end > len(blob):
            raise ValueError(f"partition {number} truncated")
        actual_crc = go4_crc32(blob[start:end])
        if actual_crc != expected_crc:
            raise ValueError(f"partition {number} CRC mismatch")
        result.append((part_id, start, end, descriptor + 9, parameter))
        cursor = end
    if blob[cursor:] != b"FOOTERHM":
        raise ValueError("missing FOOTERHM or unexpected tail")
    return result


def repack(source: Path, part_id: int, replacement: Path, output: Path):
    if source.resolve() == output.resolve():
        raise ValueError("output must differ from source")
    blob = bytearray(source.read_bytes())
    entries = partitions(blob)
    matches = [entry for entry in entries if entry[0] == part_id]
    if len(matches) != 1:
        raise ValueError(f"partition ID {part_id} occurs {len(matches)} times")
    _, start, end, crc_offset, _ = matches[0]
    data = replacement.read_bytes()
    if len(data) != end - start:
        raise ValueError(f"replacement must be exactly {end - start} bytes")
    blob[start:end] = data
    crc = go4_crc32(data)
    struct.pack_into("<I", blob, crc_offset, crc)
    partitions(blob)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(blob)
    print(f"partition {part_id}: replaced {len(data)} bytes; CRC 0x{crc:08x}; wrote {output}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("partition_id", type=lambda value: int(value, 0))
    parser.add_argument("replacement", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    repack(args.source, args.partition_id, args.replacement, args.output)


if __name__ == "__main__":
    main()
