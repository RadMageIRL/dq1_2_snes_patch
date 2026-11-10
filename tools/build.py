"""Build the fixed DQ I+II ROMs and patches.

Input (per flavor): work/03_rpgone20_titlefix_<dq|dw>.sfc
  = headerless JP (CRC32 98BB6853) + RPGOne v2.0 IPS + mziab title fix v1.0.
Output: work/out/<flavor>/ fixed ROM, IPS and BPS against the headerless JP ROM.

Every change asserts the bytes it replaces, so a wrong input fails loudly.
usage: python tools/build.py [--only fixid,fixid] [--skip fixid]
"""
import argparse
import hashlib
import os
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import patchlib  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
JP = os.path.join(ROOT, 'work', '00_jp.sfc')


def off(bank, addr):
    return bank * 0x8000 + (addr - 0x8000)


def put(rom, bank, addr, old, new, what):
    o = off(bank, addr)
    old = bytes.fromhex(old) if isinstance(old, str) else bytes(old)
    new = bytes.fromhex(new) if isinstance(new, str) else bytes(new)
    have = bytes(rom[o:o + len(old)])
    if have != old:
        raise SystemExit('%s: %02X:%04X expected %s, found %s' % (what, bank, addr, old.hex(), have.hex()))
    rom[o:o + len(new)] = new


# ---------------------------------------------------------------- T2: idle title hook
def fix_title_idle(rom, fl):
    # RPGOne's JSL at $2C:80FC replaced 4 of the 5 bytes of LDY #$0000 / STY $5E and left
    # the $5E byte behind, so the CPU ran LSR $1CA2,X / TSB $0AA9 and called $88B4 with X=0
    # (65,535-frame wait instead of 3,100). New stub at $30:BE62 restores LDY #$0000.
    put(rom, 0x30, 0xBE62, '0000000000', 'a0000080a1', 'title stub')   # LDY #$0000 / BRA $BE08
    put(rom, 0x2C, 0x80FC, '2208be305e', '2262be30ea', 'title hook')   # JSL $30BE62 / NOP


# ---------------------------------------------------------------- 256-byte render window
def move_split(rom, bank, start, split, newsplit, what):
    """Move a 'D8 03 01 lo hi' self-jump (which restarts the 256-byte window) from
    `split` back to `newsplit`, shifting the text between them 5 bytes later."""
    o_new, o_old = off(bank, newsplit), off(bank, split)
    old = bytes(rom[o_old:o_old + 5])
    tgt = split + 5
    if old != bytes([0xD8, 0x03, 0x01, tgt & 0xFF, tgt >> 8]):
        raise SystemExit('%s: no self-jump at %02X:%04X (%s)' % (what, bank, split, old.hex()))
    mid = bytes(rom[o_new:o_old])
    t = newsplit + 5
    rom[o_new:o_new + 5] = bytes([0xD8, 0x03, 0x01, t & 0xFF, t >> 8])
    rom[o_new + 5:o_old + 5] = mid


def fix_leaf(rom, fl):
    # Leaf of the World Tree cure (DQ2). RPGOne split this message once, too late: with
    # Cannock's name >= 5 letters the split's own bytes cross offset $FF and the reader wraps.
    if fl == 'dq':
        move_split(rom, 0x2B, 0x99F3, 0x9AEF, 0x9A90, 'leaf')
    else:
        move_split(rom, 0x2B, 0x99F8, 0x9AF6, 0x9A96, 'leaf')


def enc(s):
    out = bytearray()
    for ch in s:
        if 'A' <= ch <= 'Z':
            out.append(0x10 + ord(ch) - 65)
        elif 'a' <= ch <= 'z':
            out.append(0x30 + ord(ch) - 97)
        elif ch == ' ':
            out.append(0x00)
        else:
            raise ValueError(ch)
    return bytes(out)


def fix_dragonlord(rom, fl):
    # DQ1 Dragonlord's offer at $01:CB37 (both flavors; $01:8112 jumps here). 259 bytes
    # even with an empty hero name, so the yes/no command crosses offset $FF and the text
    # loops. Also ", 5 1 , ," garbage ({51}{06}{02}{51}{51} boy). Rewritten in place with
    # RPGOne's own wording from their bank $32 copy and one window restart after page 2.
    o = off(0x01, 0xCB37)
    old_hex = ('fd8b223e00483e44003730453400323e3c3400f40060fe1800303c00433734001a383d36003e35001a383d364250fe'
               '134130363e3d001a383d3660f0fd8b180037304534003134343d0046303843383d3600353e4100483e4450fe00223e'
               '00483e44003041340043373400483e443d36fe003c303d0033344243383d343300433e0030414138453450f0fd8b18'
               '3500483e440046303d4300433e003134003c4800303b3b48fe0018553b3b003638453400483e440037303b35fe003e'
               '350043373400463e413b3300f450f0fd8b2637304300333e00483e4400423048510602515100313e4859fe0026383b'
               '3b00483e44003134003c4800303b3b4859f0ddd80d0267cc3dccff')
    old = bytes.fromhex(old_hex)
    if bytes(rom[o:o + len(old)]) != old:
        raise SystemExit('dragonlord: unexpected bytes at 01:CB37')
    p2_end = old.index(bytes.fromhex('50f0fd8b183500')) + 2          # after "...arrive.{f0}"
    say = old.index(enc('What do you say'))
    tail = old.index(bytes.fromhex('fe0026383b3b'))                  # "\n Will you be my ally?"
    split_addr = 0xCB37 + p2_end
    t = split_addr + 5
    new = (old[:p2_end] + bytes([0xD8, 0x03, 0x01, t & 0xFF, t >> 8]) + old[p2_end:say]
           + enc('What do you say') + bytes([0x60]) + old[tail:])
    assert len(new) <= len(old), (len(new), len(old))
    assert new.endswith(bytes.fromhex('ddd80d0267cc3dccff'))
    rom[o:o + len(new)] = new


# ---------------------------------------------------------------- DQ2 name buffers
SLOT2_COMPACT = {   # F1 83 01 (RPGOne's 6-byte slot that runs into $0189) -> F1 68 01 (slot 2)
    'dq': ['01:8ED5', '01:8F9B', '01:9093', '01:90B0', '01:9177', '01:AB6E', '01:AB93',
           '14:8642', '14:8688', '14:C5EA', '14:C62C', '34:8573'],
    'dw': ['01:8ED5', '01:8F9B', '01:9093', '01:90B0', '01:9177', '01:AB70', '01:AB95',
           '14:8641', '14:8687', '14:C616', '14:C658', '34:8583'],
}
CANNOCK_IDENTITY = {  # F1 5F 01 (party slot 1) -> F1 89 01 (Cannock himself), as in JP
    'dq': ['14:831F', '14:A2A2', '14:A2B3', '14:A2C8', '14:A30F', '14:A406', '14:A9AC', '14:AA44',
           '14:AC05', '14:AEE0', '14:AF2B', '14:AF68', '14:AFD5', '14:B015', '14:B035', '14:B0BB',
           '14:B153', '14:B19B', '14:B1C3', '14:B25B', '14:B2FF', '14:B36A', '14:D97B', '2B:9AF5',
           '2B:9C30', '33:C998', '34:B400', '34:B43F', '34:B99D', '34:B9CE', '34:BA03', '34:BA33',
           '34:BA78', '34:BAA2'],
    'dw': ['14:832A', '14:A2B3', '14:A2C4', '14:A2D7', '14:A31F', '14:A414', '14:A9BC', '14:AA54',
           '14:AC15', '14:AEF0', '14:AF3B', '14:AF78', '14:AFE5', '14:B026', '14:B046', '14:B0D0',
           '14:B16C', '14:B1B4', '14:B1DC', '14:B274', '14:B318', '14:B383', '14:D9B8', '2B:9C41',
           '33:C9D8', '34:B407', '34:B43C'],
}


def fix_names(rom, fl):
    # slot swap ($1B:A521): JP also swapped its 5-byte compact names at $0176/$017B. RPGOne
    # moved those names to 9-byte slots but left this swap, which rewrites the hero's name
    # tail and Cannock's copy. Nothing needs the compact copies swapped once the readers
    # below use the 9-byte slot names, so the 5-byte swap is removed.
    put(rom, 0x1B, 0xA557, '2008a5', 'eaeaea', 'compact swap')
    # first living party member's name ($0C95, used by F5 95): slots, not a mix
    put(rom, 0x09, 0x9953, 'a27a01', 'a25f01', 'lead name slot 1')
    put(rom, 0x09, 0x995B, 'a29201', 'a26801', 'lead name slot 2')
    # item / spell target name by party slot ($00:BCAF): slots, as in JP
    put(rom, 0x00, 0xBCAF, '710189019201', '71015f016801', 'target name table')
    # princess copy into $0183 (6 bytes before $0189) overwrote Cannock's fixed name
    # for princess names of 6+ letters; nothing reads $0183 after SLOT2_COMPACT
    put(rom, 0x09, 0xB05E, '2022b1', 'eaeaea', 'new-game princess copy')
    put(rom, 0x09, 0xB114, '2022b1', 'eaeaea', 'rename princess copy')
    for a in SLOT2_COMPACT[fl]:
        b, ad = (int(x, 16) for x in a.split(':'))
        put(rom, b, ad, 'f18301', 'f16801', 'slot2 ' + a)
    for a in CANNOCK_IDENTITY[fl]:
        b, ad = (int(x, 16) for x in a.split(':'))
        put(rom, b, ad, 'f15f01', 'f18901', 'cannock ' + a)


# ---------------------------------------------------------------- DQ1 King and Princess
def fix_dq1_level30_save(rom, fl):
    # DQ flavor only. At max level the King's "You are already strong enough" line ended
    # with FF, so the save prompt that follows it in JP never appeared. JP (and RPGOne's DW
    # flavor) end that line with F0 and fall through into "Shall I record your journey".
    if fl == 'dq':
        put(rom, 0x01, 0xB8B1, 'fffd1a', 'f0fd1a', 'level-30 save fallthrough')


def fix_dq1_princess_love(rom, fl):
    # DQ flavor only. "I hope that you are safe, {05}<HERO>." - $05 is the digit 4.
    if fl == 'dq':
        put(rom, 0x01, 0xB748 - 0x3000, '0005f450fffd', '00f450fffffd', "Princess's Love 4")


def fix_dq1_king_victory(rom, fl):
    # Flag $3B branch of the King's talk: JP goes to the "You have finally slain the
    # Dragonlord" speech, then the level/save talk. RPGOne pointed it past the speech.
    if fl == 'dq':
        put(rom, 0x01, 0xBD10, 'ea3b00cbbd', 'ea3b002bbd', 'king victory speech')
    else:
        put(rom, 0x01, 0xBD20, 'ea3b00debd', 'ea3b003bbd', 'king victory speech')


# ---------------------------------------------------------------- DQ2 menus
def fix_status_view(rom, fl):
    # DQ2 Status submenu (window $4A, RPGOne's line list at $31:8380): title "Status",
    # options Equip and view-status (JP: tsuyosa miru). RPGOne pointed the third row at the
    # title's own line ($31:8394), so the menu read Status / Equip / Status. New line
    # " View" at $31:FF00 (free in both flavors), same 8-cell width as the others.
    put(rom, 0x31, 0xFF00, '00' * 11, '9d00' + enc('View').hex() + '000000a7ff', 'view line')
    put(rom, 0x31, 0x838A, '9483', '00ff', 'status submenu row 3')


# ---------------------------------------------------------------- DQ2 second prince
def fix_king_prince(rom, fl):
    # King of Laurasia (DQ2, script $14:800C; entry $14:8000 when Cannock is ill). JP sends
    # "party of two" and "slot-2 HP 0" straight to the short "You've returned safely" text
    # (JP $802B), past the check FB B3 (flag $B3 = told at Cannock that the prince left).
    # RPGOne pointed both branches at the check itself ($8026), so with the prince already in
    # the party the King repeats "A short time ago, the Prince ... came looking for you" and
    # sets flag $9E again, which puts the prince back in the Leftwyne inn (map $28 record,
    # shown while $9E is set). Talking to that copy replays the join. Same bytes both flavors.
    put(rom, 0x14, 0x8000, 'e90a0c002680', 'e90a0c002b80', 'king: slot-2 HP 0 branch')
    put(rom, 0x14, 0x8020, 'e9e60c022680', 'e9e60c022b80', 'king: party of two branch')
    put(rom, 0x14, 0x802B, 'fd', 'fd', 'king: short speech starts here')


# ---------------------------------------------------------------- DQ1 princess return
def fix_dq1_princess_farewell(rom, fl):
    # DQ1, bringing the princess back to the King: after the Princess's Love is handed over
    # ($01:BFF5 DQ / $01:C017 DW; JP $01:8C84) Laura says goodbye and the message ends (JP
    # "...<HERO>" FE FF). RPGOne ended her last line with F0 (wait) and no FF, so it ran on
    # into the next entry (the "talk to Laura again" lines: $C4 = 2, D8 35, switch -> case 2)
    # and played a second, reworded farewell plus the [kiss] jingle. That entry is still
    # reached normally through FB 3F at $BFA5/$BFC5, whose target is the byte after this one.
    a = 0xC057 if fl == 'dq' else 0xC07D
    put(rom, 0x01, a - 2, 'f460f0e1c40002', 'f460ffe1c40002', 'princess farewell end')


FIXES = [('title_idle', fix_title_idle), ('names', fix_names), ('leaf', fix_leaf),
         ('dragonlord', fix_dragonlord), ('dq1_level30_save', fix_dq1_level30_save),
         ('dq1_princess_love', fix_dq1_princess_love), ('dq1_king_victory', fix_dq1_king_victory),
         ('status_view', fix_status_view), ('king_prince', fix_king_prince),
         ('dq1_princess_farewell', fix_dq1_princess_farewell)]


def bps_create(src, dst):
    """Plain BPS writer: SourceRead where bytes match, TargetRead elsewhere."""
    def num(v):
        out = bytearray()
        while True:
            x = v & 0x7F
            v >>= 7
            if v == 0:
                out.append(0x80 | x)
                return bytes(out)
            out.append(x)
            v -= 1
    p = bytearray(b'BPS1') + num(len(src)) + num(len(dst)) + num(0)
    i, n = 0, len(dst)
    while i < n:
        same = i < len(src) and src[i] == dst[i]
        j = i
        while j < n and ((j < len(src) and src[j] == dst[j]) == same):
            j += 1
        ln = j - i
        if same:
            p += num(((ln - 1) << 2) | 0)
        else:
            p += num(((ln - 1) << 2) | 1) + dst[i:j]
        i = j
    p += zlib.crc32(src).to_bytes(4, 'little') + zlib.crc32(dst).to_bytes(4, 'little')
    p += zlib.crc32(p).to_bytes(4, 'little')
    return bytes(p)


JP_CRC = 0x98BB6853                       # headerless original, 1,572,864 bytes
STAGE_CRC = {                            # headerless, after each third-party patch
    'dq': {'rpgone': 0xB5AE1E89, 'mziab': 0xFA0422D4},
    'dw': {'rpgone': 0x80C078FF, 'mziab': 0xCF6A44A2},
}
RELEASE = 'dq1-2-fixed-patch-radmageirl'


def load_jp(path):
    d = open(path, 'rb').read()
    if len(d) % 0x8000 == 512:
        d = d[512:]
    if zlib.crc32(d) != JP_CRC:
        raise SystemExit('%s is not the original Japanese ROM (headerless CRC32 %08X, want %08X)'
                         % (path, zlib.crc32(d), JP_CRC))
    return d


def third_party_base(jp, fl, rpgone_ips, mziab_bps):
    """JP + RPGOne v2.0 (a headered IPS) + mziab title fix v1.0 (headerless BPS)."""
    headered = patchlib.ips_apply(bytes(512) + jp, open(rpgone_ips, 'rb').read())[512:]
    if zlib.crc32(headered) != STAGE_CRC[fl]['rpgone']:
        raise SystemExit('%s: RPGOne result CRC32 %08X unexpected' % (fl, zlib.crc32(headered)))
    rom = patchlib.bps_apply(headered, open(mziab_bps, 'rb').read())
    if zlib.crc32(rom) != STAGE_CRC[fl]['mziab']:
        raise SystemExit('%s: mziab result CRC32 %08X unexpected' % (fl, zlib.crc32(rom)))
    return rom


def hashes(data):
    return {'size': len(data), 'crc32': '%08X' % zlib.crc32(data), 'md5': hashlib.md5(data).hexdigest(),
            'sha1': hashlib.sha1(data).hexdigest(), 'sha256': hashlib.sha256(data).hexdigest()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='')
    ap.add_argument('--skip', default='')
    ap.add_argument('--flavors', default='dq,dw')
    ap.add_argument('--jp', default=JP, help='original Japanese ROM, headered or not')
    ap.add_argument('--rpgone', default=os.path.join(ROOT, 'work', 'DQV20%s.IPS'),
                    help='RPGOne v2.0 IPS, %%s = DQ or DW')
    ap.add_argument('--mziab', default=os.path.join(ROOT, 'work', 'dq12fix_%s.bps'),
                    help='mziab title fix BPS, %%s = dq or dw')
    ap.add_argument('--release', default=None, help='folder to write the release patches into')
    a = ap.parse_args()
    only = set(filter(None, a.only.split(',')))
    skip = set(filter(None, a.skip.split(',')))
    jp = load_jp(a.jp)
    report = []
    for fl in a.flavors.split(','):
        rom = bytearray(third_party_base(jp, fl, a.rpgone % fl.upper(), a.mziab % fl))
        applied = []
        for fid, fn in FIXES:
            if (only and fid not in only) or fid in skip:
                continue
            fn(rom, fl)
            applied.append(fid)
        outdir = os.path.join(ROOT, 'work', 'out', fl)
        os.makedirs(outdir, exist_ok=True)
        tag = '' if not (only or skip) else '_' + '-'.join(applied)
        rom = bytes(rom)
        open(os.path.join(outdir, 'fixed_%s%s.sfc' % (fl, tag)), 'wb').write(rom)
        ips = patchlib.ips_create(jp, rom)
        bps = bps_create(jp, rom)
        assert patchlib.ips_apply(jp, ips) == rom, 'IPS round trip failed'
        assert patchlib.bps_apply(jp, bps) == rom, 'BPS round trip failed'
        open(os.path.join(outdir, 'fixed_%s%s.ips' % (fl, tag)), 'wb').write(ips)
        open(os.path.join(outdir, 'fixed_%s%s.bps' % (fl, tag)), 'wb').write(bps)
        print('%s: %s  CRC32 %08X  SHA-1 %s  (ips %d, bps %d bytes)' % (
            fl, ','.join(applied), zlib.crc32(rom), hashlib.sha1(rom).hexdigest(), len(ips), len(bps)))
        if a.release and not (only or skip):
            hjp, hrom = bytes(512) + jp, bytes(512) + rom
            hips, hbps = patchlib.ips_create(hjp, hrom), bps_create(hjp, hrom)
            assert patchlib.ips_apply(hjp, hips) == hrom and patchlib.bps_apply(hjp, hbps) == hrom
            os.makedirs(os.path.join(a.release, 'headered'), exist_ok=True)
            files = {
                '%s-%s.ips' % (RELEASE, fl): ips, '%s-%s.bps' % (RELEASE, fl): bps,
                'headered/%s-%s-headered.ips' % (RELEASE, fl): hips,
                'headered/%s-%s-headered.bps' % (RELEASE, fl): hbps,
            }
            for name, data in files.items():
                open(os.path.join(a.release, name), 'wb').write(data)
            report.append((fl, hashes(rom), hashes(hrom), {k: hashes(v) for k, v in files.items()}))
    if report:
        lines = ['base (headerless) %s' % hashes(jp), 'base (headered, all-zero header) %s' % hashes(bytes(512) + jp)]
        for fl, h, hh, fh in report:
            lines.append('%s patched (headerless) %s' % (fl, h))
            lines.append('%s patched (headered) %s' % (fl, hh))
            for k, v in fh.items():
                lines.append('  %s %s' % (k, v))
        print('\n'.join(lines))


if __name__ == '__main__':
    main()
