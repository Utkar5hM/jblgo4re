#!/usr/bin/env python3
"""Conservative xref scan for stage0: decode every Thumb branch encoding at
every halfword offset (data included, so false positives only over-report)
and every 32-bit word, report anything that lands in the given ranges."""
import struct, sys
B = 0x40000
def scan(d, ranges):
    hits = []
    inr = lambda t: any(lo <= t < hi for lo, hi in ranges)
    for o in range(0, len(d) - 1, 2):
        a = B + o; h1 = struct.unpack_from('<H', d, o)[0]
        if (h1 >> 12) == 0xd and ((h1 >> 8) & 0xf) < 0xe:            # B<c> T1
            t = a + 4 + (((h1 & 0xff) ^ 0x80) - 0x80) * 2
            if inr(t): hits.append((a, 'b<c>.n', t))
        if (h1 >> 11) == 0b11100:                                    # B T2
            t = a + 4 + (((h1 & 0x7ff) ^ 0x400) - 0x400) * 2
            if inr(t): hits.append((a, 'b.n', t))
        if (h1 & 0xf500) == 0xb100:                                  # CBZ/CBNZ
            t = a + 4 + ((((h1 >> 9) & 1) << 6) | (((h1 >> 3) & 0x1f) << 1))
            if inr(t): hits.append((a, 'cbz', t))
        if o + 3 < len(d) and (h1 >> 11) == 0b11110:
            h2 = struct.unpack_from('<H', d, o + 2)[0]
            S = (h1 >> 10) & 1; J1 = (h2 >> 13) & 1; J2 = (h2 >> 11) & 1
            if (h2 >> 14) == 0b11 or (h2 >> 12) & 0b1101 == 0b1001:  # BL/BLX/B.W T4
                I1 = 1 - (J1 ^ S); I2 = 1 - (J2 ^ S)
                imm = (S << 24) | (I1 << 23) | (I2 << 22) | ((h1 & 0x3ff) << 12) | ((h2 & 0x7ff) << 1)
                imm -= (1 << 25) if S else 0
                t = a + 4 + imm
                if (h2 >> 12) & 1 == 0: t &= ~3
                if inr(t): hits.append((a, 'bl/b.w', t))
            elif (h2 >> 14) == 0b10 and (h2 >> 12) & 1 == 0 and ((h1 >> 6) & 0xf) < 0xe:  # B<c>.W T3
                imm = (S << 20) | (J2 << 19) | (J1 << 18) | (((h1 >> 0) & 0x3f) << 12) | ((h2 & 0x7ff) << 1)
                imm -= (1 << 21) if S else 0
                t = a + 4 + imm
                if inr(t): hits.append((a, 'b<c>.w', t))
        if o + 3 < len(d):
            v = struct.unpack_from('<I', d, o)[0]
            if inr(v) or inr(v & ~1): hits.append((a, 'word', v))
    return hits
if __name__ == '__main__':
    d = open(sys.argv[1], 'rb').read()
    rs = [tuple(int(x, 0) for x in r.split('-')) for r in sys.argv[2:]]
    for a, k, t in scan(d, rs): print(f"  0x{a:05x} {k:8s} -> 0x{t:05x}")
