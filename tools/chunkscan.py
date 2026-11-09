"""Worst-case scan of DQ2 (SFC) script chunks against the 256-byte render window.

Model of the text expander ($09:9F84) and renderer ($00:B222), from the handlers
in bank $09 (jump table $09:A02C) and the renderer's 8-bit INC $C9:
  - the renderer reads the expanded buffer at $06A0 with an index that wraps at 256,
  - a chunk ends at FF or at a D8 03 (goto), which re-expands from offset 0,
  - every byte the renderer must read in a chunk must sit at offset <= $FF.

Output sizes per code (worst case where a value is involved):
  text byte (<$D8) 1 | FE 1 | E5 1 | DC 1 | DD 1 | F0 2 | FD 0
  D8 cmd n p1..pn: 3+2n (copied) | names (F1 to WRAM, F4, F5): NAME bytes
  F1 to ROM: actual string in bank $01 | numbers: DIGITS bytes
  F7 a a w / FA a a w: w | F3: 2*count | conditionals: both paths explored
usage: python tools/chunkscan.py ROM [--name N] [--digits N] [--limit 256] [--banks 01,14,2B,32,33,34]
"""
import argparse
import sys

NAME = 8
DIGITS = 8


def off(bank, addr):
    return bank * 0x8000 + (addr - 0x8000)


class Scanner:
    def __init__(self, rom, name, digits):
        self.d = rom
        self.name = name
        self.digits = digits

    def rom_string_len(self, addr):
        # F1 to a ROM address reads bank $01 (DB is forced to $01)
        o = off(0x01, addr)
        n = 0
        while self.d[o + n] != 0xFF and n < 64:
            n += 1
        return n

    def walk(self, bank, addr, pos, depth, seen, out):
        """Follow one path from (bank, addr) with `pos` bytes already in the chunk.
        Appends (end_pos, end_kind, end_addr, path) for every terminating path."""
        d = self.d
        steps = 0
        while True:
            steps += 1
            if steps > 4000 or depth > 40:
                out.append((pos, 'cap', addr))
                return
            if addr < 0x8000 or addr > 0xFFFF:
                out.append((pos, 'badaddr', addr))
                return
            o = off(bank, addr)
            c = d[o]
            if c == 0xFF:
                out.append((pos, 'FF', addr))
                return
            if c < 0xD8:
                pos += 1
                addr += 1
                continue
            p = d[o + 1:o + 8]
            if c == 0xD8:
                n = p[1]
                size = 3 + 2 * n
                if p[0] == 0x03:
                    # goto: the renderer reads the whole command, then restarts at 0
                    out.append((pos + size, 'D8-03', addr))
                    return
                pos += size
                addr += size
                continue
            if c in (0xFE, 0xE5, 0xDC, 0xDD):
                pos += 1; addr += 1; continue
            if c == 0xF0:
                pos += 2; addr += 1; continue
            if c in (0xFD, 0xD9, 0xDA, 0xE2, 0xF8):
                pos += 1 if c == 0xE2 else 0
                addr += 1
                continue
            if c == 0xF1:
                tgt = p[0] | (p[1] << 8)
                pos += self.rom_string_len(tgt) if tgt >= 0x8000 else self.name
                addr += 3
                continue
            if c == 0xF4:
                pos += self.name; addr += 1; continue
            if c == 0xF5:
                pos += self.name; addr += 2; continue
            if c in (0xDB, 0xE6, 0xE7, 0xEC, 0xED, 0xF2, 0xF6):
                pos += self.digits; addr += 3; continue
            if c == 0xF9:
                pos += self.digits; addr += 2; continue
            if c == 0xE3:
                addr += 2; continue
            if c == 0xE4:
                pos += self.name; addr += 2; continue
            if c in (0xDF, 0xE0):
                addr += 5; continue
            if c == 0xE1:
                addr += 4; continue
            if c in (0xEE, 0xEF):
                addr += 3; continue
            if c == 0xDE:
                pos += self.name; addr += 3; continue
            if c == 0xF3:
                if p[0] == 0x80:
                    pos += 2 * p[1]
                else:
                    pos += 2 * p[1]
                addr += 3
                continue
            if c == 0xF7:
                pos += p[2]; addr += 4; continue
            if c == 0xFA:
                pos += p[2]; addr += 4; continue
            if c == 0xFC:
                addr = p[0] | (p[1] << 8)
                key = (bank, addr, pos)
                if key in seen:
                    out.append((pos, 'loop', addr)); return
                seen.add(key)
                continue
            if c in (0xE8, 0xE9):
                tgt = p[3] | (p[4] << 8)
                self.branch(bank, tgt, pos, depth, seen, out)
                addr += 6
                continue
            if c in (0xEA, 0xFB):
                tgt = p[2] | (p[3] << 8)
                self.branch(bank, tgt, pos, depth, seen, out)
                addr += 5
                continue
            if c == 0xEB:
                tgt = p[1] | (p[2] << 8)
                self.branch(bank, tgt, pos, depth, seen, out)
                addr += 4
                continue
            out.append((pos, 'unknown %02X' % c, addr))
            return

    def branch(self, bank, tgt, pos, depth, seen, out):
        key = (bank, tgt, pos)
        if key in seen:
            return
        seen.add(key)
        self.walk(bank, tgt, pos, depth + 1, seen, out)


def entries(d, bank):
    """Message starts: the byte after every FF, plus every goto/branch target in the bank."""
    base = off(bank, 0x8000)
    blob = d[base:base + 0x8000]
    starts = set()
    for i, b in enumerate(blob[:-1]):
        if b == 0xFF:
            starts.add(0x8000 + i + 1)
    return sorted(starts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('rom')
    ap.add_argument('--name', type=int, default=NAME)
    ap.add_argument('--digits', type=int, default=DIGITS)
    ap.add_argument('--limit', type=int, default=256)
    ap.add_argument('--banks', default='01,14,2B,32,33,34')
    ap.add_argument('--at', default=None, help='scan one entry, e.g. 2B:99F3')
    a = ap.parse_args()
    d = open(a.rom, 'rb').read()
    sc = Scanner(d, a.name, a.digits)
    if a.at:
        b, ad = a.at.split(':')
        out = []
        sc.walk(int(b, 16), int(ad, 16), 0, 0, set(), out)
        for pos, kind, addr in sorted(set(out)):
            print('end %3d (0x%03X) %-8s at %s:%04X' % (pos, pos, kind, b, addr))
        return
    bad = []
    for bs in a.banks.split(','):
        bank = int(bs, 16)
        for st in entries(d, bank):
            out = []
            sc.walk(bank, st, 0, 0, set(), out)
            worst = max(out, key=lambda t: t[0]) if out else None
            if worst and worst[0] > a.limit:
                bad.append((bank, st, worst))
    for bank, st, (pos, kind, addr) in bad:
        print('%02X:%04X worst %d (0x%X) ends %s at %02X:%04X' % (bank, st, pos, pos, kind, bank, addr))
    print('%d chunk starts over %d with names=%d digits=%d' % (len(bad), a.limit, a.name, a.digits))


if __name__ == '__main__':
    main()
