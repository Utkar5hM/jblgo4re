"""Add a load address to `strings -t x` offsets: strings -a -t x BIN | rebase_strings.py 0x40000"""
import sys
base = int(sys.argv[1], 0)
for line in sys.stdin:
    parts = line.strip().split(None, 1)
    if len(parts) == 2:
        print(f"{int(parts[0], 16) + base:x} {parts[1]}")
