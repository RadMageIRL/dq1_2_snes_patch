"""Static regression checks for the fixes in tools/build.py (v0.3 and the v0.2 baseline).

Needs the same inputs as build.py (original JP ROM, RPGOne v2.0 IPS, mziab BPS) and nothing else:
no emulator. Exit code 1 on any failure.

  1. Baseline: skipping the v0.3 fixes rebuilds v0.2 byte for byte (DQ 69567056, DW D1BA0360).
  2. Footprint: every byte that differs between v0.2 and v0.3 is written by exactly one v0.3
     fix, and bank $01 changes stay inside the listed scripts, text edits and stubs.
  3. Behaviour: each fixed script is walked the way the text expander runs it (branches,
     calls, gotos, window restarts; text bytes ignored) and compared with the Japanese original;
     text fixes are read back through their detours, with no reference into replaced bytes.
  4. Negative control: the same checks run on v0.2 and must fail where v0.3 fixes something.

usage: python -I tools/check_fixes.py [--jp ROM] [--rpgone IPS%s] [--mziab BPS%s]
"""
import argparse
import os
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build  # noqa: E402

V02_CRC = {'dq': 0x69567056, 'dw': 0xD1BA0360}
fails = []


def ok(cond, msg):
    print(('  ok   ' if cond else '  FAIL ') + msg)
    if not cond:
        fails.append(msg)


def off(b, a):
    return b * 0x8000 + a - 0x8000


def apply(base, fl, ids):
    rom = bytearray(base)
    for fid, fn in build.FIXES:
        if fid in ids:
            fn(rom, fl)
    return rom


# ----------------------------------------------------------------- script walker
LEN = {0xE0: 5, 0xE1: 4, 0xE8: 6, 0xE9: 6, 0xEA: 5, 0xFB: 5, 0xEE: 3, 0xEF: 3, 0xF1: 3, 0xF5: 2, 0xFC: 3,
       0xF6: 3, 0xDB: 3, 0xF7: 4, 0xFA: 4, 0xDE: 3}     # from the handlers at $09:A02C
LAYOUT = {0xFE, 0xFD, 0xDC, 0xDD, 0xE5, 0xE2}       # line/indent codes: JP and English lay out differently


def walk(d, bank, start, region, exits, intent=None, layout=False):
    """Tree of control tokens for the script at bank:start, as the expander and renderer run it.

    region: list of (lo, hi) ranges of this script; a goto or branch outside them becomes
    ('exit', exits[target]). A jump back to an address already on the path becomes ('loop',).
    intent: {address: address} redirects (used for one JP target that points mid-instruction).
    Text bytes are dropped; F1 to ROM is followed as a call (bank $01, as the engine does)."""
    intent = intent or {}

    def go(a, stack, seen):
        out = []
        while True:
            a = intent.get(a, a)
            if not any(lo <= a <= hi for lo, hi in region) and not stack:
                out.append(('exit', exits.get(a, '%04X?' % a)))
                return out
            if (a, stack) in seen:                    # back to a spot already on this path
                out.append(('loop',))
                return out
            seen = dict(seen)
            seen[(a, stack)] = True
            o = off(bank if not stack else 0x01, a)
            x = d[o]
            if x < 0xD8:                             # text
                a += 1
                continue
            if x in LAYOUT:
                if layout:
                    out.append(('%02X' % x,))
                a += 1
                continue
            if x == 0xFF:
                if stack:
                    a = stack[-1]
                    stack = stack[:-1]
                    continue
                out.append(('end',))
                return out
            if x == 0xF0:
                out.append(('F0',))
                a += 1
                continue
            if x == 0xF4:
                out.append(('name', 'F4 (actor)'))
                a += 1
                continue
            if x == 0xD8:
                cmd, n = d[o + 1], d[o + 2]
                ps = [d[o + 3 + 2 * i] | d[o + 4 + 2 * i] << 8 for i in range(n)]
                if cmd == 0x03:                      # window restart / goto (render time)
                    out.append(('restart',))
                    a = ps[0]
                    continue
                if cmd in (0x38, 0x0D, 0x12):        # render-time switch / yes-no: every target
                    out.append(('switch %02X' % cmd, tuple(go(t, stack, seen) for t in ps)))
                    return out
                out.append(('D8 %02X' % cmd,) + tuple(ps))
                a += 3 + 2 * n
                continue
            ln = LEN.get(x, 1)
            raw = d[o:o + ln]
            if x in (0xE8, 0xE9):
                t = raw[4] | raw[5] << 8
                cond = ('%02X' % x, raw[1] | raw[2] << 8, raw[3])
                out.append(('if',) + cond + (tuple(go(t, stack, seen)), tuple(go(a + ln, stack, seen))))
                return out
            if x in (0xEA, 0xFB):
                t = raw[3] | raw[4] << 8
                out.append(('ifflag %02X' % x, raw[1], tuple(go(t, stack, seen)), tuple(go(a + ln, stack, seen))))
                return out
            if x == 0xFC:
                a = raw[1] | raw[2] << 8
                continue
            if x == 0xF1:
                t = raw[1] | raw[2] << 8
                if t < 0x8000:
                    out.append(('name', '%04X' % t))
                    a += 3
                else:
                    stack = stack + (a + 3,)
                    a = t
                continue
            out.append(tuple(['%02X' % x] + list(raw[1:])))
            a += ln
    return tuple(go(start, (), {}))


def leaves(t):
    """Last token of every path through a walk() tree."""
    last = t[-1]
    if last[0] in ('if',):
        return leaves(last[4]) + leaves(last[5])
    if last[0].startswith('ifflag'):
        return leaves(last[2]) + leaves(last[3])
    if last[0].startswith('switch'):
        return [x for sub in last[1] for x in leaves(sub)]
    return [last]


def has_loop(t):
    return "('loop',)" in repr(t)


def first_diff(t1, t2, path='root'):
    if t1 == t2:
        return None
    if isinstance(t1, tuple) and isinstance(t2, tuple):
        for i, (a, b) in enumerate(zip(t1, t2)):
            r = first_diff(a, b, '%s/%d' % (path, i))
            if r:
                return r
        if len(t1) != len(t2):
            return '%s: length %d vs %d' % (path, len(t1), len(t2))
    return '%s: %r vs %r' % (path, t1, t2)


# ----------------------------------------------------------------- checks
def check_footprint(v02, v03, base, fl):
    diff = {i for i in range(len(v03)) if v02[i] != v03[i]}
    owner = {}
    for fid in build.V03:
        r = apply(v02, fl, {fid})
        for i in range(len(r)):
            if r[i] != v02[i]:
                owner.setdefault(i, []).append(fid)
    ok(set(owner) == diff, '%s: all %d changed bytes come from the v0.3 fixes' % (fl, len(diff)))
    ok(all(len(v) == 1 for v in owner.values()), '%s: no byte is written by two fixes' % fl)
    b1 = sorted(i for i in diff if i // 0x8000 == 1)
    ca = 0xA2B8 if fl == 'dq' else 0xA2BA
    s3 = [(a, a + 12) for a in BANK01_STAGE3[fl]] + [(0xFED0, 0xFEFF)]      # stage 3 text edits and their stubs
    s3 += [(a, a + 15) for a in BANK01_STAGE4[fl]]                            # stage 4: same-length text edits
    inside = all(off(1, 0x8F02) <= i <= off(1, 0x91C0) or off(1, ca) <= i <= off(1, ca + 0x12)
                 or off(1, 0xFF40) <= i <= off(1, 0xFFFF) or off(1, 0x89D5) <= i <= off(1, 0x89DD)
                 or any(off(1, lo) <= i <= off(1, hi) for lo, hi in s3) for i in b1)
    ok(inside, '%s: bank $01 changes only in the Chance script ($8F02-$91C0), the confused-attack script '
       '($%04X), new code ($FF40+), the poison-cure script ($89D5-$89DD), the stage-3 text edits (%s, stubs '
       '$FED0-$FEFF) and the stage-4 text edits (%s)' % (fl, ca, ' '.join('$%04X' % a for a in BANK01_STAGE3[fl]),
                                                          ' '.join('$%04X' % a for a in BANK01_STAGE4[fl])))
    per = {}
    for i, v in owner.items():
        per[v[0]] = per.get(v[0], 0) + 1
    print('       bytes per fix: ' + ', '.join('%s %d' % (k, per.get(k, 0)) for k in build.V03))


def check_orb(jp, rom, fl):
    yes, no = (0x9D77, 0x9DCD) if fl == 'dq' else (0x9D88, 0x9DDE)
    def runs_on(d, a, stop):
        while d[off(0x2B, a)] != 0xFF:
            if a == stop or d[off(0x2B, a)] == 0xD8 and d[off(0x2B, a) + 1] == 0x03:
                return True
            a += 1
        return a >= stop
    ok(not runs_on(jp, 0x9B1E, 0x9B6D), 'JP: Orb Yes text ($2B:9B1E) ends with FF before the No text')
    ok(not runs_on(rom, yes, no), '%s: Orb Yes text ($2B:%04X) ends with FF before the No text ($%04X)' % (fl, yes, no))


def check_nun(jp, rom, fl):
    start, end = (0xC98C, 0xCA5D) if fl == 'dq' else (0xC9C6, 0xCAA9)
    t = walk(rom, 0x33, start, [(start, end)], {})
    ok(not has_loop(t) and set(leaves(t)) == {('end',)}, '%s: nun message ($33:%04X) has no loop and ends' % (fl, start))
    tj = walk(jp, 0x0F, 0xF170, [(0xF170, 0xF1F6)], {})
    ok(not has_loop(tj) and set(leaves(tj)) == {('end',)}, 'JP: nun message ($0F:F170) has no loop and ends')


def check_flute(jp, rom, fl):
    def mapping(d, base):
        m = {}
        for k in range(5):
            o = off(0x2B, base + 6 * k)
            assert d[o] == 0xE9 and d[o + 1:o + 3] == b'\x21\x00'
            t = off(0x2B, d[o + 4] | d[o + 5] << 8)
            assert d[t] == 0xFB
            m[d[o + 3]] = d[t + 1]
        return m
    mj = mapping(jp, 0x9815)
    me = mapping(rom, 0x9976 if fl == 'dq' else 0x997B)
    ok(mj == me, '%s: flute map -> crest flag %s equals JP' % (fl, ' '.join('%02X:%02X' % kv for kv in sorted(me.items()))))


def check_king(jp, rom, fl):
    a3, a4 = (0x81A2, 0x81A8) if fl == 'dq' else (0x81A1, 0x81A7)
    def tgt(d, a, kind):
        o = off(0x14, a)
        if kind == 'D8':
            assert d[o:o + 3] == b'\xd8\x03\x01'
            return d[o + 3] | d[o + 4] << 8
        assert d[o] == 0xE9
        return d[o + 4] | d[o + 5] << 8
    j = [tgt(jp, 0x8000, 'E9'), tgt(jp, 0x8020, 'E9'), tgt(jp, 0x8135, 'D8'), tgt(jp, 0x813B, 'E9')]
    e = [tgt(rom, 0x8000, 'E9'), tgt(rom, 0x8020, 'E9'), tgt(rom, a3, 'D8'), tgt(rom, a4, 'E9')]
    ok(j == [0x802B] * 4 and e == [0x802B] * 4,
       '%s: King branches ill/party-2/party-3 $9C/party-3 princess HP 0 -> %s (JP %s)'
       % (fl, ' '.join('%04X' % x for x in e), ' '.join('%04X' % x for x in j)))


# JP <-> English correspondences for the Chance script exits (spell scripts from the D8 10 switch
# at JP $01:DF92 / English $01:8937, the common tail from roll 0, the roll-7 'all fled' script)
def chance_exits(fl):
    tail = 0x9DCA if fl == 'dq' else 0x9DCC
    return ({0xF029: 'tail', 0xE25B: 'sleep/defence script', 0xE098: 'damage script', 0xE3BD: 'party defence script',
             0xE795: 'all fled'},
            {tail: 'tail', 0x8C7D: 'sleep/defence script', 0x8A82: 'damage script', 0x8E4B: 'party defence script',
             0x92CE: 'all fled'})


def check_chance(jp, rom, fl, before=False):
    xj, xe = chance_exits(fl)
    # JP $01:E54E 'E9 [0C9E]==FF -> E552' lands inside its own instruction (a JP slip); every other
    # absent-slot test goes to the next slot, so the comparison uses that intent (E592).
    tj = walk(jp, 0x01, 0xE444, [(0xE444, 0xE6C0)], xj, intent={0xE552: 0xE592})
    te = walk(rom, 0x01, 0x8F02, [(0x8F02, 0x91C0), (build.CH_FREE, build.CH_FREE + 0x68),
                                  (build.CH_FREE + 0x70, build.CH_FREE + 0x78)], xe)
    def rolls(t):
        out = []
        node = t[0]
        while node[0] == 'if' and node[1] == 'E9' and node[2] == 0x1031:
            out.append((node[3], node[4]))
            node = node[5][0]
        return dict(out)
    rj, re_ = rolls(tj), rolls(te)
    for r in range(8):
        d = first_diff(rj[r], re_[r])
        label = '%s: Chance roll %d control flow and party names = JP' % (fl, r)
        ok(d is None, label + ('' if d is None else '  first difference: ' + d[:160]))


def check_confused_attack(jp, rom, fl):
    a = 0xA2B8 if fl == 'dq' else 0xA2BA
    tail, after = (0x9DCA, 0x9EB7) if fl == 'dq' else (0x9DCC, 0x9EB9)
    tj = walk(jp, 0x01, 0xF461, [(0xF461, 0xF4E3)], {0xF029: 'tail', 0xF0EF: 'after defeat'})
    te = walk(rom, 0x01, a, [(a, a + 0x85), (build.CH_FREE + 0x69, build.CH_FREE + 0x6F)],
              {tail: 'tail', after: 'after defeat'})
    d = first_diff(tj, te)
    ok(d is None, '%s: confused monster attack ($01:%04X) control flow = JP $01:F461%s'
       % (fl, a, '' if d is None else '  first difference: ' + d[:160]))


def check_transform(jp, rom, fl, dw_rom):
    o = off(0x00, 0x9186)
    assert rom[o] == 0xA0 and rom[o + 5] == 0xA9
    ptr, bank = rom[o + 1] | rom[o + 2] << 8, rom[o + 6]
    tj = walk(jp, 0x01, 0xCC83, [(0xCC83, 0xCCCB)], {}, layout=False)
    te = walk(rom, bank, ptr, [(ptr, ptr + 0x80)], {}, layout=False)
    ok(te == tj, '%s: $00:9186 -> $%02X:%04X, flags/sounds/waits = JP $01:CC83 %s' % (fl, bank, ptr, '' if te == tj else first_diff(tj, te)))
    if dw_rom is not None:
        do = off(0x00, 0x9186)
        dp, dbk = dw_rom[do + 1] | dw_rom[do + 2] << 8, dw_rom[do + 6]
        tw = walk(dw_rom, dbk, dp, [(dp, dp + 0x80)], {}, layout=True)
        tl = walk(rom, bank, ptr, [(ptr, ptr + 0x80)], {}, layout=True)
        ok(tl == tw, '%s: line layout codes = DW $%02X:%04X' % (fl, dbk, dp))


# ----------------------------------------------------------------- v0.3 stage 2
def check_item_menu_name(jp, rom, fl):
    stores = [i for i in range(len(rom) - 3) if rom[i + 1:i + 4] == b'\x6e\x01\x7e' and rom[i] in (0x8F, 0x9F)]
    stores += [i for i in range(len(rom) - 2) if rom[i + 1:i + 3] == b'\x6e\x01' and rom[i] in (0x8D, 0x8E, 0x8C, 0x9C)]
    ok(not stores, '%s: no code stores into $016E (slot-2 name, 7th byte)%s'
       % (fl, '' if not stores else ': ' + ' '.join('%02X:%04X' % (i // 0x8000, i % 0x8000 + 0x8000) for i in stores)))
    o = off(0x30, 0x8600)
    ok(rom[o:o + 5] == bytes.fromhex('c92af0016b') and rom[o + 9:o + 12] == bytes.fromhex('c220a5'),
       '%s: item-name line break ($2A) handler at $30:8600 otherwise unchanged' % fl)


def check_inn(jp, rom, fl):
    a = 0xB870 if fl == 'dq' else 0xB86E
    j = jp[off(0x14, 0xE0DF):off(0x14, 0xE0DF) + 3]
    e = rom[off(0x34, a):off(0x34, a) + 3]
    ok(e[:2] == j[:2] == b'\xf6\x89', '%s: Beran inn price prints %s (JP $14:E0DF %s)' % (fl, e.hex(), j.hex()))


def check_vault(jp, rom, fl):
    j = [jp[off(0x2B, a):off(0x2B, a) + 3] for a in (0x89FF, 0x8C6F)]
    e = [rom[off(0x2B, a):off(0x2B, a) + 3] for a in (0x83A1, 0x873F)]
    ok(e == j, '%s: vault deposit / balance print %s / %s = JP $2B:89FF / $2B:8C6F (24-bit DB)' % (fl, e[0].hex(), e[1].hex()))


def check_after_hargon(jp, rom, fl):
    bad = []
    for k in range(28):
        o = off(0x14, build.AH_TABLE + 8 * k)
        t = rom[o + 3] | rom[o + 4] << 8
        if rom[o:o + 3] != b'\xd8\x3c\x02' or rom[o + 5] != 0x33 or rom[off(0x33, t):off(0x33, t) + 3] != b'\xfd\x5f\x8b':
            bad.append('%d->$33:%04X' % (k, t))
    ok(not bad, '%s: all 28 after-Hargon stubs ($14:F96E table, JP order) start a message%s'
       % (fl, '' if not bad else ' (not: %s)' % ', '.join(bad)))
    o = off(0x14, build.AH_TABLE)
    jt = jp[o + 3] | jp[o + 4] << 8
    copies = [(0x14, 0xEC23 if fl == 'dq' else 0xEC77), (0x34, 0xE249 if fl == 'dq' else 0xE257)]
    tg = [rom[off(b, a) + 3] | rom[off(b, a) + 4] << 8 for b, a in copies]
    ok(tg == [0x8C20, 0x8C20], '%s: RPGOne\'s two copies of stub 0 also go to $33:8C20 (JP stub 0 -> $2B:%04X)' % (fl, jt))


HEXCH = set(range(0x01, 0x0B)) | set(range(0x30, 0x36))


def literal_escapes(d):
    """Comma + two hex-digit characters not followed by a lower-case letter (RPGOne escapes)."""
    hits = []
    for b in (0x01, 0x14, 0x2B, 0x2C, 0x31, 0x32, 0x33, 0x34):
        for a in range(0x8000, 0xFFFC):
            i = off(b, a)
            if d[i] == 0x51 and d[i + 1] in HEXCH and d[i + 2] in HEXCH and not 0x30 <= d[i + 3] <= 0x49:
                hits.append('%02X:%04X' % (b, a))
    return hits


# 24-bit matches checked by hand: JP-identical bytes inside JP text, not pointers
NOT_POINTERS = {0x15CCAA: 'JP kana text "13 9B 14" after an F0 in bank $2B ($2B:CCAA)',
                # $2B:AD44-$AD69 is JP's own yes/no script left in place (bytes = JP in v0.2, DQ and DW), reached only
                # by its own D8 03 at $AD64; its target $AA99 is a JP message address, not the English coffin text
                0x15AD47: 'JP leftover D8 0D at $2B:AD44 (identical to JP, self-referenced only)'}
EXCLUDED = []


def refs_into(d, bank, lo, hi, inside, jp):
    """Places that could point at bank:lo..hi from outside `inside` (file offsets lo..hi of the span).

    Excluded (and counted in EXCLUDED): 24-bit matches in bytes identical to JP, when the target
    bank is $30+ (JP has no such bank, so its data cannot point there) or the target starts no
    message in JP or English (the byte before it is not FF) and the match is not a far goto;
    NOT_POINTERS; and far gotos (D8 3C 02 lo hi bank) whose bank is another one."""
    found = []
    seg0 = off(bank, 0x8000)
    for t in range(lo, hi + 1):
        p3 = bytes([t & 0xFF, t >> 8, bank])
        i = d.find(p3)
        while i >= 0:
            same = i + 6 <= len(jp) and d[i - 6:i + 6] == jp[i - 6:i + 6]
            tj = off(bank, t)
            no_start = (d[tj - 1] != 0xFF and (tj > len(jp) or jp[tj - 1] != 0xFF)
                        and d[i - 3:i] != b'\xd8\x3c\x02')
            if inside[0] <= i <= inside[1]:
                pass
            elif same and (bank >= 0x30 or no_start) or i in NOT_POINTERS:
                EXCLUDED.append((i, bank, t))
            else:
                found.append(('ptr24', i, t))
            i = d.find(p3, i + 1)
        p2 = bytes([t & 0xFF, t >> 8])
        i = d.find(p2, seg0, seg0 + 0x8000)
        while i >= 0:
            far_other = d[i - 3:i] == b'\xd8\x3c\x02' and d[i + 2] != bank
            ctx = (d[i - 4] in (0xE8, 0xE9) or d[i - 3] in (0xEA, 0xFB) or d[i - 1] in (0xFC, 0xA0)
                   or any(d[i - 3 - 2 * k] == 0xD8 and d[i - 1 - 2 * k] > k for k in range(8))) and not far_other
            if ctx and not inside[0] <= i <= inside[1] and i not in NOT_POINTERS:
                found.append(('op16', i, t))
            i = d.find(p2, i + 1, seg0 + 0x8000)
        i = d.find(b'\xa0' + p2)
        while i >= 0:
            if bytes([0xA9, bank]) in d[i + 3:i + 12] and not inside[0] <= i <= inside[1]:
                found.append(('LDY#', i, t))
            i = d.find(b'\xa0' + p2, i + 1)
    return found


def check_garbage(jp, v02, rom, fl):
    before, after = literal_escapes(v02), literal_escapes(rom)
    ok(not after, '%s: no literal hex escapes left in the text banks (v0.2 had %d: %s)'
       % (fl, len(before), ' '.join(before)))
    del EXCLUDED[:]
    for (bank, start, stop), edits in build.GARBAGE[fl]:
        # 1) nothing outside the span points into the moved bytes (checked on v0.2, before the move)
        fr = refs_into(v02, bank, start + 1, stop, (off(bank, start), off(bank, stop)), jp)
        # a branch to the span's closing FF still ends the message: that byte stays FF (padding)
        to_end = [r for r in fr if r[2] == stop and rom[off(bank, stop)] == 0xFF]
        fr = [r for r in fr if r not in to_end]
        if to_end:
            print('       (%d branch(es) to the span end $%04X, which stays FF: %s)' % (len(to_end), stop,
                  ' '.join('%02X:%04X' % (i // 0x8000, i % 0x8000 + 0x8000 - 4) for k, i, t in to_end)))
        ok(not fr, '%s: no reference into $%02X:%04X-$%04X from outside%s' % (fl, bank, start + 1, stop,
           '' if not fr else ': ' + ', '.join('%s at %02X:%04X->%04X' % (k, i // 0x8000, i % 0x8000 + 0x8000, t) for k, i, t in fr[:6])))
        # 2) the message's control codes are unchanged (text is dropped by walk); start from the
        #    span's message start (the first FF before it)
        ms = start
        while v02[off(bank, ms - 1)] != 0xFF:
            ms -= 1
        t2 = walk(v02, bank, ms, [(ms, stop)], {})
        t3 = walk(rom, bank, ms, [(ms, stop)], {})
        d = first_diff(t2, t3)
        ok(d is None and not has_loop(t3), '%s: $%02X:%04X message: control codes unchanged by the cleanup%s'
           % (fl, bank, ms, '' if d is None else ' ' + d[:120]))
    print('       24-bit byte matches set aside as JP data, not pointers: %d (%s)'
          % (len(EXCLUDED), ' '.join('%02X:%04X->%02X:%04X' % (i // 0x8000, i % 0x8000 + 0x8000, b, t)
                                     for i, b, t in EXCLUDED)))


def pause_newline_on_last_row(d):
    """'D8 52 00' (pause) + FE on the 4th line of a window: the next line overwrites row 1."""
    hits = []
    for b in (0x01, 0x14, 0x2B, 0x32, 0x33, 0x34):
        for a in range(0x8000, 0xFFF0):
            i = off(b, a)
            if d[i:i + 4] == b'\xd8\x52\x00\xfe':
                j, lines = i - 1, 1
                while j > i - 400:
                    if d[j] == 0xFE:
                        lines += 1
                    if d[j] in (0xF0, 0xFF) or d[j:j + 3] == b'\xd8\x03\x01':
                        break
                    j -= 1
                if lines >= 4:
                    hits.append('%02X:%04X' % (b, a))
    return hits


def lines_until_wait(d, bank, start):
    """Text lines of the message at bank:start up to its FF. FE and F0 both end a line (text after
    a wait continues on the next row); a line with no text (a trailing FE) does not count."""
    i, n, has = off(bank, start), 0, False
    while d[i] != 0xFF:
        if d[i] == 0xD8:
            i += 3 + 2 * d[i + 2]
            continue
        if d[i] in (0xFE, 0xF0):
            n, has = n + has, False
        elif d[i] < 0xD8 and d[i] != 0x00:
            has = True
        i += 1
    return n + has


def check_curse_laugh(jp, rom, fl):
    s = 0x8E63 if fl == 'dq' else 0x8E6B
    n, nj = lines_until_wait(rom, 0x34, s), lines_until_wait(jp, 0x14, 0xC8A3)
    ji = jp.find(b'\xd8\x52\x00', off(0x14, 0xC8A3), off(0x14, 0xC8A3) + 0x40)
    a = 0x8EB2 if fl == 'dq' else 0x8EBA
    ok(n == nj == 4 and rom[off(0x34, a):off(0x34, a) + 3] == jp[ji:ji + 3] == b'\xd8\x52\x00',
       '%s: curse laugh message ($34:%04X) is %d lines, the pause kept (JP $14:C8A3: %d lines, pause at $%04X)'
       % (fl, s, n, nj, ji % 0x8000 + 0x8000))
    h = pause_newline_on_last_row(rom)
    ok(not h, '%s: no pause + new line on a window\'s 4th row%s' % (fl, '' if not h else ': ' + ' '.join(h)))


def check_vault_layout(jp, rom, fl):
    o = off(0x2B, 0x8737)
    ok(rom[o + 7:o + 11] == b'\xfe\xdb\x89\x0c', '%s: vault balance on its own line ("holding" FE DB 89 0C)' % fl)


def check_poison_cure(jp, rom, fl):
    tail = 0x9DCA if fl == 'dq' else 0x9DCC
    tj = walk(jp, 0x01, 0xE00C, [(0xE00C, 0xE02E)], {0xF029: 'tail'})
    te = walk(rom, 0x01, 0x89D5, [(0x89D5, 0x8A0D)], {tail: 'tail'})
    d = first_diff(tj, te)
    ok(d is None, '%s: poison-cure battle script ($01:89D5) = JP $01:E00C (call cast message, restart, poison text, tail)%s'
       % (fl, '' if d is None else '  first difference: ' + d[:160]))


# ----------------------------------------------------------------- v0.3 stage 3
BANK01_STAGE3 = {'dq': [0xAE74, 0xB1AB, 0xC2E0, 0xFE56, 0xBBBE] + build.TRAILING_2A, 'dw': [0x9B67, 0xCAE6]}
BANK01_STAGE4 = {'dq': [0xAE0B, 0xB143], 'dw': [0xAE0B, 0xB149, 0xD78E]}      # retrieve x2; DW item $43 name
TEXT_BANKS = (0x01, 0x14, 0x2B, 0x32, 0x33, 0x34)
JP_EXP = ['14:8366', '14:83CC', '14:843B', '14:A8AF', '14:A90D', '14:A974', '14:C2E8', '14:C346', '14:C3AB',
          '2B:9BF8', '2B:9C6D', '2B:9CE5']
OTHER_FLAVOR_NAMES = {'dq': ['Gwaelin', 'Dragonlord', 'Erdrick', 'Midenhall', 'Cannock'],      # plus the item tables
                      'dw': ['Laura', 'Laurasia', 'Sumaltria', 'Roto']}


def ba(where):
    b, a = where.split(':')
    return int(b, 16), int(a, 16)


def follow(d, bank, at, n):
    """The first n bytes the text expander reads from bank:at, following FC gotos (codes kept whole)."""
    out, a = bytearray(), at
    while len(out) < n:
        o = off(bank, a)
        x = d[o]
        if x == 0xFC:
            a = d[o + 1] | d[o + 2] << 8
            continue
        ln = 3 + 2 * d[o + 2] if x == 0xD8 else LEN.get(x, 1)
        out += d[o:o + ln]
        a += ln
    return bytes(out[:n])


def item_names(d):
    """Names in the item pointer table $09:E927 (strings in bank $01; the $2A line break read as a space)."""
    out = set()
    for k in range(106):
        o = off(0x09, 0xE927) + 2 * k
        p = d[o] | d[o + 1] << 8
        if p >= 0x8000:
            s = d[off(1, p):d.index(b'\xff', off(1, p))]
            out.add(bytes(0 if c == 0x2A else c for c in s).strip(b'\x00'))
    return out


def find_text(d, s):
    """Offsets of text bytes s (words may be split by a space, new line or line start) in the text banks,
    outside the name tables at $01:D563-$01:E0FF."""
    import re
    words = [re.escape(w) for w in s.split(b'\x00')]
    pat = re.compile(b'[\x00\xfe\xfd]+'.join(words) + b'(?![\x30-\x49])')
    hits = []
    for b in TEXT_BANKS:
        seg = d[off(b, 0x8000):off(b, 0x10000)]
        for m in pat.finditer(seg):
            o = off(b, 0x8000) + m.start()
            if not (b == 1 and off(1, 0xD563) <= o < off(1, 0xE100)):
                hits.append(o)
    return hits


def leaks(d, other, fl):
    """Item names of the other flavor (absent from this flavor's table) and the other flavor's character
    names, found in this flavor's text."""
    names = sorted(item_names(other) - item_names(d)) + [build.enct(n) for n in OTHER_FLAVOR_NAMES[fl]]
    out = []
    for n in names:
        for o in find_text(d, n):
            out.append('%s at %02X:%04X' % (''.join(chr(c + 49) if 0x10 <= c <= 0x29 or 0x30 <= c <= 0x49
                                                     else ' ' if c == 0 else "'" for c in n), o // 0x8000, o % 0x8000 + 0x8000))
    return out


def check_names(jp, v02, rom, other, fl):
    lk = leaks(rom, other, fl)
    ok(not lk, '%s: no item or character name of the other flavor in the text (v0.2 had: %s)' % (fl, '; '.join(leaks(v02, other, fl))))
    if lk:
        print('       left: ' + '; '.join(lk))
    for fid, nfl, sites, old, new in build.NAMES:
        if nfl != fl:
            continue
        o, n = build.enct(old), build.enct(new)
        for where, stub in sites:
            b, a = ba(where)
            after = v02[off(b, a) + len(o):off(b, a) + len(o) + 6]
            got = follow(rom, b, a, len(n) + 6)
            fine = got == n + after
            if stub:
                fine = fine and v02[off(b, stub):off(b, stub) + len(n) - len(o) + 6] == bytes(len(n) - len(o) + 6)
                rf = refs_into(v02, b, a + 1, a + len(o) - 1, (off(b, a), off(b, a + len(o) - 1)), jp)
                fine = fine and not rf
            ok(fine, '%s: %s %s reads "%s"%s' % (fl, fid, where, new, ' (stub $%04X, no reference into the old bytes)' % stub if stub else ''))


def check_lead(jp, v02, rom, fl):
    for entry in build.LEAD:
        where = entry[1] if fl == 'dq' else entry[2]
        jb, ja = ba(entry[0])
        b, a, o, n = build.lead_edit(v02, fl, entry)
        after = v02[off(b, a) + len(o):off(b, a) + len(o) + 3]
        got = follow(rom, b, a, len(n) + 3)
        rf = refs_into(v02, b, a + 1, a + len(o) - 1, (off(b, a), off(b, a + len(o) - 1)), jp)
        ok(jp[off(jb, ja):off(jb, ja) + 2] == b'\xf5\x95' and got == n + after and v02[off(*ba(where))] == 0xF4 and not rf,
           '%s: %s names the lead member (F5 95) like JP %s (was F4, the hero)' % (fl, where, entry[0]))


def check_exp(jp, rom, fl):
    j = all(jp[off(*ba(w)):off(*ba(w)) + 3] == b'\xdb\x91\x0c' for w in JP_EXP)
    e = all(rom[off(*ba(w)):off(*ba(w)) + 3] == b'\xdb\x91\x0c' for w in build.EXP_SITES[fl])
    left = [i for b in (0x14, 0x2B, 0x34) for i in range(off(b, 0x8000), off(b, 0x10000) - 16)
            if rom[i:i + 3] == b'\xf6\x91\x00' and build.enc('experience') in rom[i + 3:i + 14]]
    ok(j and e and not left, '%s: the 12 DQ2 "you need N experience" lines print 24-bit (DB 91 0C) like JP\'s 12; no 16-bit one left'
       % fl)


def codes(d, bank, a):
    """Control codes of the message at bank:a up to its FF, operand addresses dropped (text ignored)."""
    out = []
    while True:
        o = off(bank, a)
        x = d[o]
        if x == 0xFF:
            return out
        if x == 0xD8:
            out.append('D8 %02X/%d' % (d[o + 1], d[o + 2]))
            a += 3 + 2 * d[o + 2]
        elif x >= 0xD8:
            out.append('%02X' % x if x in (0xE9, 0xE8, 0xEA, 0xFB, 0xFC) else d[o:o + LEN.get(x, 1)].hex())
            a += LEN.get(x, 1)
        else:
            a += 1


def result_waits(d, cast):
    """Field spell: [wait before the result?] for the D8 23 'nothing happened' target and each spell of the
    dispatch chain (D8 23's second target), following one FC."""
    a = cast
    while d[off(0x2B, a)] != 0xD8 or d[off(0x2B, a) + 1] != 0x23:
        a += 3 + 2 * d[off(0x2B, a) + 2] if d[off(0x2B, a)] == 0xD8 else LEN.get(d[off(0x2B, a)], 1)
    o = off(0x2B, a)
    t0, chain = d[o + 3] | d[o + 4] << 8, d[o + 5] | d[o + 6] << 8

    def waits(t):
        o = off(0x2B, t)
        if d[o] == 0xF0:
            return True
        return d[o] == 0xFC and d[off(0x2B, d[o + 1] | d[o + 2] << 8)] == 0xF0
    out = [('#0', waits(t0))]
    while d[off(0x2B, chain)] == 0xE9:
        o = off(0x2B, chain)
        out.append(('%02X' % d[o + 3], waits(d[o + 4] | d[o + 5] << 8)))
        chain += 6
    return out


def check_field_spell(jp, rom, fl):
    cj, ce = codes(jp, 0x2B, 0xA5A5), codes(rom, 0x2B, 0xABE0)
    ok(cj == ce, '%s: field spell cast message ($2B:ABE0) codes = JP $2B:A5A5 (no wait after the cast line): %s'
       % (fl, ' '.join(ce)))
    wj, we = result_waits(jp, 0xA5A5), result_waits(rom, 0xABE0)
    ok(wj == we, '%s: field spell results wait (F0) exactly where JP does: %s' % (fl, ' '.join('%s:%s' % (k, 'F0' if v else '-') for k, v in we)))


def check_small(jp, v02, rom, fl):
    a = 0x831F if fl == 'dq' else 0x832A
    ok(rom[off(0x14, a):off(0x14, a) + 3] == jp[off(0x14, 0x81F1):off(0x14, 0x81F1) + 3] == b'\xf1\x92\x01',
       '%s: King of Laurasia, princess reply ($14:%04X) speaker = F1 92 01, the princess, as JP $14:81F1' % (fl, a))
    f5fe = [i for b in TEXT_BANKS for i in range(off(b, 0x8000), off(b, 0x10000)) if rom[i:i + 2] == b'\xf5\xfe']
    a = 0xB13F if fl == 'dq' else 0xB158
    ok(not f5fe and follow(rom, 0x14, a, 4) == bytes([0xF5, 0x95, 0xFE, 0x00])
       and jp[off(0x14, 0x9CEA):off(0x14, 0x9CEA) + 2] == bytes([0xF5, 0x95]),
       '%s: King of Cannock "Well <lead> / seek out my son" ($14:%04X) = F5 95 as JP $14:9CEA, then a line break; '
       'no F5 FE left' % (fl, a))
    a = 0x8193 if fl == 'dq' else 0x8192
    ok(rom[off(0x14, a)] == jp[off(0x14, 0x8126)] == 0xF0, '%s: "I can never count on you." waits (F0 at $14:%04X) like JP $14:8126' % (fl, a))
    a = 0xA92E if fl == 'dq' else 0xA944
    ok(rom[off(0x14, a)] == 0xF0, '%s: thief "...forgive me for stealing..." waits before the beer line (F0 at $14:%04X; DW and JP wait)' % (fl, a))
    a = 0xBBBE if fl == 'dq' else 0xBBCE
    ok(rom[off(1, a):off(1, a) + 4] == build.enc('died'), '%s: DQ1 King "you\'ve died in battle" ($01:%04X)' % (fl, a))
    bad = find_text(rom, build.enct('mircale')) + find_text(rom, build.enct('far to important'))
    ok(not bad, '%s: no "mircale" / "far to important" left' % fl)
    ends = []
    for k in range(106):
        for t in (0xE927, 0xE9FB):
            o = off(0x09, t) + 2 * k
            p = rom[o] | rom[o + 1] << 8
            if p >= 0x8000 and rom[off(1, p):].split(bytes([0xFF]), 1)[0].endswith(bytes([0x2A])):
                ends.append('%02X->%04X' % (k, p))
    ok(not ends, '%s: no item name in the tables $09:E927/$09:E9FB ends with the $2A line break%s'
       % (fl, '' if not ends else ': ' + ' '.join(sorted(set(ends)))))


# ----------------------------------------------------------------- v0.3 stage 4
def width(d, bs):
    """Pixel width of text bytes in RPGOne's proportional font ($30:8100 + char)."""
    return sum(d[off(0x30, 0x8100) + c] for c in bs if c < 0xD8)


def check_heal_break(jp, rom, fl):
    widest = 8 * max(rom[off(0x30, 0x8100) + c] for c in list(range(0x10, 0x2A)) + list(range(0x30, 0x4A)))
    row1, row2 = build.enct("'s wounds"), build.enct('were healed!')
    fine = all(follow(rom, 0x2B, a - 9, len(row1) + len(row2) + 1) == row1 + b'\xfe' + row2 for a in (0xACD2, 0xACFB))
    ok(fine and widest + width(rom, row1) <= 206 and width(rom, row2) <= 206,
       '%s: field heal lines ($2B:ACC9/$ACF2) break after "wounds" like RPGOne\'s battle copies; widest row %d px '
       '(8-letter name of the widest letter), limit 206' % (fl, widest + width(rom, row1)))


def check_field_lead(jp, v02, rom, fl):
    for entry in build.FIELD_LEAD:
        jb, ja = ba(entry[0])
        b, a, o, n = build.lead_edit(v02, fl, entry)
        after = v02[off(b, a) + len(o):off(b, a) + len(o) + 3]
        rf = refs_into(v02, b, a + 1, a + len(o) - 1, (off(b, a), off(b, a + len(o) - 1)), jp)
        ok(jp[off(jb, ja):off(jb, ja) + 2] == b'\xf5\x95' and v02[off(b, a)] == 0xF4
           and follow(rom, b, a, len(n) + 3) == n + after and not rf,
           '%s: field message $%02X:%04X names the lead member (F5 95) like JP %s (was F4: $AE = 0, the hero)'
           % (fl, b, a, entry[0]))
    o = off(0x2B, 0xA98E)
    ok(rom[o:o + 2] == jp[off(0x2B, 0xA408):off(0x2B, 0xA408) + 2] == b'\xf5\x95',
       '%s: trap chest "<name> was poisoned!" ($2B:A98E) names the lead like JP $2B:A408 (was F5 8F)' % fl)


TYPO_WORDS = ['retreive', 'possesion', 'you arrival', 'foward']
# $8B (JP opening quote) between English text bytes that is NOT removed, with the reason (checked: no visible
# effect; the renderer plays the talk sound and sets an indent that no following FD uses).
KEEP_8B = {
    'dq': {'01:8610': 'JP leftover text', '14:C405': 'right after the label\'s own $8B (same column)',
           '32:CFF4': 'label "Rock: "', '33:9911': 'after "Bow, wow, wow!" (message end)', '33:9912': 'same',
           '34:A581': 'after "Woof, wooof!" (message end)'},
    'dw': {'01:8610': 'JP leftover text', '14:8457': 'JP leftover text', '14:C431': 'right after the label\'s own $8B',
           '32:D084': 'label "Rock: "', '33:9911': 'after "Bow, wow, wow!" (message end)', '33:9912': 'same',
           '34:A59A': 'after "Woof, wooof!" (message end)', '32:8AD5': 'before a new line start (FD)',
           '32:B36D': 'after "Puff..." before a wait', '33:9BC7': 'marks the speech after the coughs (DQ starts a new '
           'labelled line there)'},
}
TXT = set(range(0x10, 0x2A)) | set(range(0x30, 0x4A)) | {0x00} | set(range(0x50, 0x5A)) | {0x60}


def stray_8b(d):
    """$8B after a text byte that is not a label colon, before text/FE/FF/F0/name codes, in English text."""
    out = []
    for b in TEXT_BANKS:
        for a in range(0x8000, 0xFFFF):
            o = off(b, a)
            if (d[o] == 0x8B and d[o - 1] in TXT | {0x8B} and d[o - 1] not in (0x52, 0x5F)
                    and d[o + 1] in TXT | {0xFE, 0xFF, 0xF0, 0xF4, 0xF1, 0xF5, 0x8B, 0xFC}
                    and not (b == 1 and 0xCB37 <= a <= 0xCC3C)                       # unreferenced Dragonlord copy
                    and (sum(1 for x in d[o - 20:o] if 0x30 <= x <= 0x49) >= 6 or d[o - 1] == 0x8B)):
                out.append('%02X:%04X' % (b, a))
    return out


def check_stage4_text(jp, v02, rom, fl):
    left = [(w, '%02X:%04X' % (o // 0x8000, o % 0x8000 + 0x8000)) for w in TYPO_WORDS for o in find_text(rom, build.enct(w))]
    left += [('<name>, To', '%02X:%04X' % (o // 0x8000, o % 0x8000 + 0x8000)) for o in find_text(rom, build.enct('To reach'))
             if rom[o - 2:o] == b'\x51\x00']
    ok(not left, '%s: no "retreive", "possesion", "you arrival", "foward" or "<name>, To reach" left%s'
       % (fl, '' if not left else ': ' + ' '.join('%s@%s' % x for x in left)))
    for fid, nfl, sites, old, new in build.TYPOS:
        if nfl != fl:
            continue
        o, n = build.enct(old), build.enct(new)
        for where, stub in sites:
            b, a = ba(where)
            after = v02[off(b, a) + len(o):off(b, a) + len(o) + 4]
            fine = follow(rom, b, a, len(n) + 4) == n + after and v02[off(b, a):off(b, a) + len(o)] == o
            if stub:
                fine = fine and not any(v02[off(b, stub):off(b, stub) + 8])
                fine = fine and not refs_into(v02, b, a + 1, a + len(o) - 1, (off(b, a), off(b, a + len(o) - 1)), jp)
            ok(fine, '%s: %s %s reads "%s"%s' % (fl, fid, where, new.strip(), ' (stub $%04X)' % stub if stub else ''))
    names = [rom[off(1, p):rom.index(b'\xff', off(1, p))] for t in (0xE927, 0xE9FB) for k in range(106)
             for p in [rom[off(9, t) + 2 * k] | rom[off(9, t) + 2 * k + 1] << 8] if p >= 0x8000]
    ok(not [s for s in names if b'\x2a\x00' in s], '%s: no item name has a space after its $2A line break '
       '(DW "Evil{2A} Shield")' % fl)
    for sfl, where, nxt, stub in build.STRAY_8B:
        if sfl == fl:
            b, a = ba(where)
            nb = bytes.fromhex(nxt)
            ok(v02[off(b, a)] == 0x8B and follow(rom, b, a, 2 + 4) == nb + follow(rom, b, a + 3, 4)
               and not any(v02[off(b, stub):off(b, stub) + 8])
               and not refs_into(v02, b, a + 1, a + 2, (off(b, a), off(b, a + 2)), jp),
               '%s: stray $8B at %s removed (reads on with %s)' % (fl, where, nxt))
    rest = stray_8b(rom)
    ok(set(rest) == set(KEEP_8B[fl]), '%s: the $8B left inside English lines are exactly the %d kept on purpose%s'
       % (fl, len(KEEP_8B[fl]), '' if set(rest) == set(KEEP_8B[fl]) else ': extra %s, missing %s'
          % (sorted(set(rest) - set(KEEP_8B[fl])), sorted(set(KEEP_8B[fl]) - set(rest)))))


# ----------------------------------------------------------------- v0.3 stage 4, RC2
def paths(t, pre=()):
    """Every path through a walk() tree: (control tokens in order, names as a sorted tuple). Names are compared
    as a set because Japanese and English put them in a different order."""
    ctl, names = list(pre), []
    out = []

    def rec(t, ctl, names):
        for k, tok in enumerate(t):
            if tok[0] == 'if':
                rec(tok[4], ctl + ['%s[%04X]==%02X:T' % tok[1:4]], names)
                rec(tok[5], ctl + ['%s[%04X]==%02X:F' % tok[1:4]], names)
                return
            if tok[0].startswith('ifflag'):
                rec(tok[2], ctl + ['%s %02X:T' % (tok[0], tok[1])], names)
                rec(tok[3], ctl + ['%s %02X:F' % (tok[0], tok[1])], names)
                return
            if tok[0] in ('name', 'F5'):
                names = names + ['%s' % (tok[1] if tok[0] == 'name' else 'F5 %02X' % tok[1])]
            else:
                ctl = ctl + [' '.join(str(x) for x in tok)]
        out.append((tuple(ctl), tuple(sorted(names))))
    rec(t, ctl, names)
    return out


def check_coffin(jp, v02, rom, fl):
    tj = walk(jp, 0x2B, 0xA4CC, [(0xA4CC, 0xA4FA)], {})
    te = walk(rom, 0x2B, 0xAA60, [(0xAA60, 0xAAA6)], {})
    pj, pe = paths(tj), paths(te)
    rf = refs_into(v02, 0x2B, 0xAA66, 0xAA9E, (off(0x2B, 0xAA60), off(0x2B, 0xAAA6)), jp)
    ok(pj == pe and not has_loop(te) and not rf,
       '%s: discard from a coffin ($2B:AA60) = JP $2B:A4CC: text, flag 0, end; Leaf branch restarts once; names lead + '
       'owner (F5 95, F4)%s' % (fl, '' if pj == pe else ': JP %s / EN %s' % (pj, pe)))
    a = 0xAB05
    msg = follow(rom, 0x2B, a, 0x4C)                          # through the DW detour
    got = [msg[k + 1] for k in range(len(msg) - 1) if msg[k] == 0xF5]
    j = [jp[off(0x2B, 0xA534) + k + 1] for k in range(0x26) if jp[off(0x2B, 0xA534) + k] == 0xF5]
    ok(got == [0x95, 0x8D, 0x93, 0x8F] and sorted(j) == sorted(got),
       '%s: give between two coffins ($2B:AB05): the lead takes the item from the giver\'s coffin ($0C93) into the '
       'receiver\'s ($0C8F), as JP $2B:A534 (codes %s)' % (fl, ' '.join('%02X' % x for x in got)))


def possessives_left(d):
    """A name code followed by 's' and a space, line break or punctuation: '<name>s coffin'."""
    hits = []
    for b in TEXT_BANKS:
        for a in range(0x8000, 0xFFFC):
            o = off(b, a)
            for code, n in ((0xF4, 1), (0xF5, 2), (0xF1, 3)):
                if d[o] == code and d[o + n] == 0x42 and d[o + n + 1] in (0x00, 0xFE, 0x50, 0x51, 0x58):
                    if code == 0xF5 and d[o + 1] not in (0x8F, 0x93, 0x95, 0x8D, 0xA4):
                        continue
                    if code == 0xF1 and (d[o + 2] != 0x01 or d[o + 1] not in (0x56, 0x5F, 0x68, 0x71, 0x89, 0x92)):
                        continue
                    if sum(1 for y in d[o - 15:o] if 0x30 <= y <= 0x49) < 3 and d[o - 1] not in (0x8B, 0xE5, 0xFD, 0x00):
                        continue
                    hits.append('%02X:%04X' % (b, a))
    return hits


def check_possessive(jp, v02, rom, fl):
    left = possessives_left(rom)
    ok(not left, '%s: no possessive without its apostrophe after a name ("<name>s") left (v0.2 had %d)%s'
       % (fl, len(possessives_left(v02)), '' if not left else ': ' + ' '.join(left)))
    for where, stub in build.POSSESSIVE[fl]:
        b, a = ba(where)
        nxt = v02[off(b, a) + 1:off(b, a) + 3]
        ok(v02[off(b, a)] == 0x42 and follow(rom, b, a, 4) == b"\x55\x42" + nxt and not any(v02[off(b, stub):off(b, stub) + 8])
           and not refs_into(v02, b, a + 1, a + 2, (off(b, a), off(b, a + 2)), jp),
           '%s: possessive at %s reads "\'s"' % (fl, where))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--jp', default=build.JP)
    ap.add_argument('--rpgone', default=os.path.join(build.ROOT, 'work', 'DQV20%s.IPS'))
    ap.add_argument('--mziab', default=os.path.join(build.ROOT, 'work', 'dq12fix_%s.bps'))
    a = ap.parse_args()
    jp = build.load_jp(a.jp)
    v02ids = {fid for fid, _ in build.FIXES} - set(build.V03)
    roms = {}
    for fl in ('dq', 'dw'):
        print('== %s' % fl)
        base = build.third_party_base(jp, fl, a.rpgone % fl.upper(), a.mziab % fl)
        v02 = apply(base, fl, v02ids)
        ok(zlib.crc32(v02) == V02_CRC[fl], '%s: v0.3 fixes skipped -> v0.2 (CRC32 %08X)' % (fl, zlib.crc32(v02)))
        v03 = apply(base, fl, {fid for fid, _ in build.FIXES})
        roms[fl] = (base, v02, v03)
        check_footprint(v02, v03, base, fl)
        check_orb(jp, v03, fl)
        check_nun(jp, v03, fl)
        check_flute(jp, v03, fl)
        check_king(jp, v03, fl)
        check_chance(jp, v03, fl)
        check_confused_attack(jp, v03, fl)
        print('   -- stage 2')
        check_item_menu_name(jp, v03, fl)
        check_inn(jp, v03, fl)
        check_vault(jp, v03, fl)
        check_after_hargon(jp, v03, fl)
        check_vault_layout(jp, v03, fl)
        check_garbage(jp, v02, v03, fl)
        check_curse_laugh(jp, v03, fl)
        check_poison_cure(jp, v03, fl)
    check_transform(jp, roms['dq'][2], 'dq', roms['dw'][2])
    check_transform(jp, roms['dw'][2], 'dw', None)
    for fl in ('dq', 'dw'):
        print('== %s stage 3' % fl)
        base, v02, v03 = roms[fl]
        other = roms['dw' if fl == 'dq' else 'dq'][2]
        check_names(jp, v02, v03, other, fl)
        check_lead(jp, v02, v03, fl)
        check_exp(jp, v03, fl)
        check_field_spell(jp, v03, fl)
        check_small(jp, v02, v03, fl)
    for fl in ('dq', 'dw'):
        print('== %s stage 4' % fl)
        base, v02, v03 = roms[fl]
        check_heal_break(jp, v03, fl)
        check_field_lead(jp, v02, v03, fl)
        check_stage4_text(jp, v02, v03, fl)
        check_coffin(jp, v02, v03, fl)
        check_possessive(jp, v02, v03, fl)
    print('== the same checks on v0.2 (expected to fail where v0.3 fixes something)')
    for fl in ('dq', 'dw'):
        n0 = len(fails)
        v02 = roms[fl][1]
        for fn in (check_orb, check_nun, check_flute, check_king, check_chance, check_confused_attack,
                   check_item_menu_name, check_inn, check_vault, check_vault_layout, check_after_hargon,
                   check_curse_laugh, check_poison_cure, check_exp, check_field_spell):
            fn(jp, v02, fl)
        check_names(jp, v02, v02, roms['dw' if fl == 'dq' else 'dq'][1], fl)
        check_lead(jp, v02, v02, fl)
        check_small(jp, v02, v02, fl)
        check_heal_break(jp, v02, fl)
        check_field_lead(jp, v02, v02, fl)
        check_stage4_text(jp, v02, v02, fl)
        check_coffin(jp, v02, v02, fl)
        check_possessive(jp, v02, v02, fl)
        ok(not literal_escapes(v02), '%s: no literal hex escapes in the text banks' % fl)
        if fl == 'dq':
            check_transform(jp, v02, 'dq', None)
        print('   %s v0.2: %d check(s) fail, as expected' % (fl, len(fails) - n0))
        del fails[n0:]
    print('FAILURES: %d' % len(fails))
    for f in fails:
        print('  ' + f)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
