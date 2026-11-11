"""Independent check of the eight release patches against the original Japanese ROM.

The patches are applied with the small IPS and BPS readers in this file (not tools/patchlib.py, which wrote
them), and each result is compared with the ROM that tools/build.py builds in memory from the same inputs.
Checked per flavor: IPS structure (no truncation field, no record at the 'EOF' offset, nothing after EOF),
BPS source size/CRC = the original ROM, target size/CRC, patch CRC, the output hashes, and the headered
patches on an all-zero header and (with --jp pointing at a copier-headered dump) on that real header.

usage: python -I tools/check_patches.py --jp ROM [--dir FOLDER] [--baseline v0.2|v0.3]
  --dir       folder holding the patches as released (default: the repository root)
  --baseline  v0.2: expect the v0.2 build (every v0.3 and v0.4 fix skipped), e.g. for the v0.2 files;
              v0.3: expect the v0.3.0 build (every v0.4 fix skipped), e.g. for the released v0.3.0 files
Inputs as for build.py (--rpgone, --mziab). Exit code 1 on any failure.
"""
import argparse
import hashlib
import os
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build  # noqa: E402

fails = []


def ok(cond, msg):
    print(('  ok   ' if cond else '  FAIL ') + msg)
    if not cond:
        fails.append(msg)


def ips_apply(src, p):
    assert p[:5] == b'PATCH', 'no PATCH header'
    out, i, recs, maxend = bytearray(src), 5, 0, 0
    while p[i:i + 3] != b'EOF':
        o = int.from_bytes(p[i:i + 3], 'big')
        size = int.from_bytes(p[i + 3:i + 5], 'big')
        i += 5
        if size == 0:
            data = p[i + 2:i + 3] * int.from_bytes(p[i:i + 2], 'big')
            i += 3
        else:
            data = p[i:i + size]
            i += size
        if o + len(data) > len(out):
            out.extend(bytes(o + len(data) - len(out)))
        out[o:o + len(data)] = data
        recs, maxend = recs + 1, max(maxend, o + len(data))
    tail = p[i + 3:]
    return bytes(out), recs, maxend, tail


def bps_apply(src, p):
    assert p[:4] == b'BPS1', 'no BPS1 header'
    i = 4

    def num():
        nonlocal i
        v, s = 0, 1
        while True:
            x = p[i]
            i += 1
            v += (x & 0x7F) * s
            if x & 0x80:
                return v
            s <<= 7
            v += s
    ssize, tsize, msize = num(), num(), num()
    i += msize
    out, so, to, end = bytearray(), 0, 0, len(p) - 12
    while i < end:
        d = num()
        cmd, ln = d & 3, (d >> 2) + 1
        if cmd == 0:
            out += src[len(out):len(out) + ln]
        elif cmd == 1:
            out += p[i:i + ln]
            i += ln
        elif cmd == 2:
            d = num()
            so += (-1 if d & 1 else 1) * (d >> 1)
            out += src[so:so + ln]
            so += ln
        else:
            d = num()
            to += (-1 if d & 1 else 1) * (d >> 1)
            for _ in range(ln):
                out.append(out[to])
                to += 1
    scrc, tcrc, pcrc = (int.from_bytes(p[end + k:end + k + 4], 'little') for k in (0, 4, 8))
    return bytes(out), ssize, tsize, scrc, tcrc, pcrc, zlib.crc32(p[:-4])


def h(b):
    return '%08X sha1 %s' % (zlib.crc32(b), hashlib.sha1(b).hexdigest())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jp', default=build.JP)
    ap.add_argument('--dir', default=build.ROOT)
    ap.add_argument('--baseline', choices=['v0.2', 'v0.3'], default=None)
    ap.add_argument('--rpgone', default=os.path.join(build.ROOT, 'work', 'DQV20%s.IPS'))
    ap.add_argument('--mziab', default=os.path.join(build.ROOT, 'work', 'dq12fix_%s.bps'))
    a = ap.parse_args()
    raw = open(a.jp, 'rb').read()
    jp = build.load_jp(a.jp)                         # headerless, CRC-checked
    print('original ROM %s: %d bytes, headerless %s' % (a.jp, len(raw), h(jp)))
    jph0 = bytes(512) + jp
    skip = {'v0.2': set(build.V03) | set(build.V04), 'v0.3': set(build.V04)}.get(a.baseline, set())
    for fl in ('dq', 'dw'):
        rom = bytearray(build.third_party_base(jp, fl, a.rpgone % fl.upper(), a.mziab % fl))
        for fid, fn in build.FIXES:
            if fid not in skip:
                fn(rom, fl)
        rom = bytes(rom)
        print('== %s: expected ROM %s (%d bytes)' % (fl, h(rom), len(rom)))
        name = build.RELEASE + '-' + fl
        for rel, src, hdr in (('%s.ips' % name, jp, 0), ('%s.bps' % name, jp, 0),
                              ('headered/%s-headered.ips' % name, jph0, 512), ('headered/%s-headered.bps' % name, jph0, 512)):
            p = open(os.path.join(a.dir, rel), 'rb').read()
            print(' %s  (%d bytes, sha1 %s, sha256 %s)' % (rel, len(p), hashlib.sha1(p).hexdigest(), hashlib.sha256(p).hexdigest()))
            if rel.endswith('.ips'):
                out, recs, maxend, tail = ips_apply(src, p)
                ok(maxend == len(out) and not tail, 'IPS: %d records, ends at the file end (%d bytes), nothing after EOF'
                   % (recs, maxend))
            else:
                out, ss, ts, sc, tc, pc, pcalc = bps_apply(src, p)
                ok(ss == len(src) and sc == zlib.crc32(src), 'BPS: source = the original ROM (%d bytes, %08X)' % (ss, sc))
                ok(ts == len(out) and tc == zlib.crc32(out), 'BPS: target size and CRC match the output (%d, %08X)' % (ts, tc))
                ok(pc == pcalc, 'BPS: patch CRC %08X valid' % pc)
            ok(out[hdr:] == rom and out[:hdr] == src[:hdr], 'output = the build (%s)' % h(out))
        if len(raw) == len(jp) + 512 and any(raw[:512]):
            p = open(os.path.join(a.dir, 'headered/%s-headered.ips' % name), 'rb').read()
            out = ips_apply(raw, p)[0]
            ok(out[:512] == raw[:512] and out[512:] == rom,
               'headered IPS on the given copier-headered dump keeps its header ($%02X...) and gives the build' % raw[0])
    print('FAILURES: %d' % len(fails))
    for f in fails:
        print('  ' + f)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
