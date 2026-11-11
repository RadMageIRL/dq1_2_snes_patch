"""Build the fixed DQ I+II ROMs and patches.

Input (per flavor): work/03_rpgone20_titlefix_<dq|dw>.sfc
  = headerless JP (CRC32 98BB6853) + RPGOne v2.0 IPS + mziab title fix v1.0.
Output: work/out/<flavor>/ fixed ROM, IPS and BPS against the headerless JP ROM.

Every change asserts the bytes it replaces, so a wrong input fails loudly.
usage: python tools/build.py [--only fixid,fixid] [--skip fixid] [--out DIR] [--release DIR]
Regression checks: python tools/check_fixes.py (no emulator needed).
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


# ================================================================ v0.3 stage 1
# Each correction is derived from the original Japanese script or from RPGOne's own other
# flavor (noted per fix). Old bytes are asserted in full. Fixes that touch only one flavor
# also assert the other flavor's bytes, so a wrong input fails loudly.

def fix_orb_after_hargon(rom, fl):
    # DQ2, Descendant's Orb after Hargon. "D8 0D" yes/no: Yes ($9D77 DQ / $9D88 DW) ends its
    # last line with F0 and no FF, so it runs on into the No text ($9DCD / $9DDE), whose
    # D8 03 jumps back to the question: the conversation never ends. JP's Yes message
    # ($2B:9B1E) ends with FF. Same one-byte fix in both flavors.
    a = 0x9DCC if fl == 'dq' else 0x9DDD
    put(rom, 0x2B, a - 3, '505050f0fd5f8b13', '505050fffd5f8b13', 'orb: end the Yes message')


def fix_nun_after_hargon(rom, fl):
    # DQ2, nun after Hargon (DQ flavor). After "Thanks to you, the people have been saved."
    # the window-restart D8 03 at $33:C9D0 jumps back to $C9A2, the start of that same line,
    # so it repeats forever. JP ($0F:F170) is one linear message; RPGOne's DW flavor has the
    # same D8 03 pointing at the byte after itself ($33:CA1C -> $CA21). DQ now does too.
    if fl == 'dq':
        put(rom, 0x33, 0xC9CE, '50f0d80301a2c9fd5f8b23', '50f0d80301d5c9fd5f8b23', 'nun: restart, not loop')
    else:
        put(rom, 0x33, 0xCA1C, 'd8030121ca', 'd8030121ca', 'nun (DW): already a restart')


def fix_flute_crests(rom, fl):
    # DQ2, Echoing Flute. The five map checks ([$0021] = $2D/$35/$63/$7E/$99) all jumped to
    # the crest-1 flag test (FB C9), so after the first crest was taken the flute never
    # echoed at the other four sites. JP ($2B:9815) sends each map to its own flag test:
    # $2D->C9, $35->CB, $63->CD, $7E->CC, $99->CA. Same order of tests in both flavors.
    base = 0x9976 if fl == 'dq' else 0x997B          # first E9 [0021]==2D
    tests = base + 0x32                              # FB C9 block; blocks are 11 bytes apart
    old = b''.join(bytes([0xE9, 0x21, 0x00, m, tests & 0xFF, tests >> 8]) for m in (0x2D, 0x35, 0x63, 0x7E, 0x99))
    new = b''.join(bytes([0xE9, 0x21, 0x00, m, (tests + 11 * k) & 0xFF, (tests + 11 * k) >> 8])
                   for k, m in enumerate((0x2D, 0x35, 0x63, 0x7E, 0x99)))
    for k, flag in enumerate((0xC9, 0xCB, 0xCD, 0xCC, 0xCA)):  # each target is its own test
        o = off(0x2B, tests + 11 * k)
        if rom[o:o + 2] != bytes([0xFB, flag]):
            raise SystemExit('flute: no FB %02X at 2B:%04X' % (flag, tests + 11 * k))
    put(rom, 0x2B, base, old, new, 'flute: per-crest flag tests')


def fix_king_prince_party3(rom, fl):
    # DQ2, King of Laurasia, party of three (completes v0.2 king_prince). With flag $9C set
    # (D8 03 at $81A2 DQ / $81A1 DW) or the princess at 0 HP (E9 [0C0B]==00 at $81A8 / $81A7),
    # RPGOne still sent the King to $8026 (FB B3 -> "the Prince ... came looking for you",
    # sets $9E: the prince reappears at the Leftwyne inn). JP $14:8135 and $813B go to the
    # short "You've returned safely" text, = $802B here (checked by king_prince).
    a = 0x81A2 if fl == 'dq' else 0x81A1
    put(rom, 0x14, a, 'd803012680ffe90b0c002680', 'd803012b80ffe90b0c002b80', 'king: party-of-three branches')
    put(rom, 0x14, 0x802B, 'fd', 'fd', 'king: short speech starts here')


# Chance (DQ2 spell $19): battle script $01:8F02 (both flavors), JP $01:E444. Byte runs below
# are RPGOne's own text; only control codes, targets and the slot-0 name change.
CH_FREE = 0xFF40                        # bank $01 tail, zero in JP, v2.0 DQ and v2.0 DW
HEALED = '55420046 3e443d33 42004634 41340037 34303b34 3358'.replace(' ', '')  # 's wounds were healed!
NOEFFECT = '00373033 003d3e00 34353534 324358'.replace(' ', '')                # " had no effect!"
REVIVED = '00463042 00413445 38453433 58'.replace(' ', '')                     # " was revived!" ($01:8959)
APPEARED = '00303f3f 34304134 3358'.replace(' ', '')                           # " appeared!"


def fix_chance(rom, fl):
    """Restore JP's control flow in Chance's outcome scripts (JP $01:E444).

    Roll 7 (monsters flee) and roll 4 (full HP): RPGOne jumped to the 'X casts Chance!'
    message (D8 03 -> $8920, ending in FF) where JP calls it (F1 7B DF), so the script ended
    there: no flee messages, no rewards, no battle-end music restore. Roll 6 (confuse): JP
    'D8 24 00 F5 A4' became 'F1 F5 A4', a call into $01:A4F5 that printed 'damage!' and broke
    the loop after one monster. Roll 4 also had wrong 'was dead' targets, a no-op absent-slot
    check, a call where JP restarts the window, and a jump into roll 6 (JP: next slot).
    Text (user-approved, v0.3): JP's 'revived' line for roll 4 (RPGOne's ' had no effect!')
    now uses RPGOne's own Revive wording ' was revived!', and the slot-0 lines of the heal
    outcomes (rolls 0 and 4) and of the flee outcome (roll 7, '<slot 0> appeared!') name
    party slot 0 (F1 56 01) as JP does, not the caster (F4).
    """
    tail = 'ca9d' if fl == 'dq' else 'cc9d'      # D8 03 target ($9DCA / $9DCC) after slot 2
    # sanity: the dispatch and the shared parts are where this fix expects them
    put(rom, 0x01, 0x8F02, 'e9311000338fe9311001bd8f', 'e9311000338fe9311001bd8f', 'chance: dispatch')
    put(rom, 0x01, 0x8F1A, 'e9311004d58f', 'e9311004d58f', 'chance: roll 4 entry')
    put(rom, 0x01, 0x90C3, 'd80c00d80301' + tail + 'ff', 'd80c00d80301' + tail + 'ff', 'chance: roll 4 end')
    free = off(0x01, CH_FREE)
    if any(rom[free:free + 0x69]):
        raise SystemExit('chance: $01:%04X-$%04X is not free' % (CH_FREE, CH_FREE + 0x68))

    def stub(at, code):
        put(rom, 0x01, at, '00' * len(code), code, 'chance: new code at 01:%04X' % at)
        return at + len(code)

    def le(a):
        return bytes([a & 0xFF, a >> 8])

    # --- roll 4, slot 0: rebuilt at $FF40 in JP's layout (JP $01:E504-$E54A) -------------
    s0, slot1 = CH_FREE, 0x9024
    revived0 = s0 + 30 + 25 + 1 + 3                 # after test/copy/sound, healed text, F0, FC
    join0 = revived0 + 16 + 1
    block = (bytes.fromhex('f12089')                               # call "X casts Chance!"
             + bytes.fromhex('e99d0cff') + le(slot1)               # slot 0 absent -> slot 1
             + bytes.fromhex('e0090ca00c' 'd80c00')                # HP = max HP, refresh
             + bytes.fromhex('e99d0c00') + le(revived0)            # was dead -> revived text
             + bytes.fromhex('e1b0101d' 'd82c00')                  # heal sound
             + bytes.fromhex('f15601' + HEALED + 'f0')            # <slot 0>'s wounds were healed!
             + b'\xfc' + le(join0)
             + bytes.fromhex('f15601' + REVIVED + 'f0')           # <slot 0> was revived!
             + bytes.fromhex('d80301') + le(slot1) + b'\xff')      # window restart -> slot 1
    assert len(block) == 82 and s0 + block.index(bytes.fromhex('f15601' + REVIVED)) == revived0
    nxt = stub(s0, block)
    old_slot0 = ('d803012089' 'e99d0cff2490' 'e0090ca00c' 'd80c00' 'e99d0c00f58f' 'e1b0101d' 'd82c00'
                 'f4' + HEALED + 'f0' 'fc2090' 'f4' + NOEFFECT + 'f12490' 'ff')
    put(rom, 0x01, 0x8FD5, old_slot0, 'fc' + le(s0).hex() + 'ff' * 76, 'chance: roll 4 slot 0 -> new block')
    # --- roll 4, slot 1 (JP $E54B-$E591) --------------------------------------------------
    put(rom, 0x01, 0x9027, 'e99e0cf02d90', 'e99e0cff7890', 'chance: slot 1 absent -> slot 2')
    put(rom, 0x01, 0x9035, 'e99e0c004290', 'e99e0c006190', 'chance: slot 1 was dead -> revived text')
    put(rom, 0x01, 0x905C, 'fc7290' 'f15f01' + NOEFFECT + 'f0' 'd80301cc90' 'ff',
        'fc7290' 'ffff' 'f15f01' + REVIVED + 'f0' 'd803017890' 'ff', 'chance: slot 1 revived text, -> slot 2')
    # --- roll 4, slot 2 (JP $E592-$E5D8): only the revived text -------------------------
    put(rom, 0x01, 0x9086, 'e99f0c00b090', 'e99f0c00b290', 'chance: slot 2 was dead -> revived text')
    put(rom, 0x01, 0x90AD, 'fcc390' 'f16801' + NOEFFECT + 'f0' 'd80c00',
        'fcc390' 'ffff' 'f16801' + REVIVED + 'f0' 'd80c00', 'chance: slot 2 revived text')
    # --- roll 0 (heal all), slot-0 line: JP 'call $0156', RPGOne F4 (the caster) -----------
    r0 = nxt
    nxt = stub(r0, bytes.fromhex('d82c00' 'f15601' 'fc') + le(0x8F4A))
    put(rom, 0x01, 0x8F46, 'd82c00f4' + HEALED, 'fc' + le(r0).hex() + 'ff' + HEALED, 'chance: roll 0 slot-0 name')
    # --- roll 6 (confuse): JP 'D8 24 00 F5 A4' before the monster name --------------------
    r6 = nxt
    nxt = stub(r6, bytes.fromhex('d82400' 'f5a4' 'fc') + le(0x90F6))
    put(rom, 0x01, 0x90F3, 'f1f5a4e2', 'fc' + le(r6).hex() + 'e2', 'chance: roll 6 monster name')
    # --- roll 7 (flee): call the cast message, as JP ---------------------------------------
    r7 = nxt
    nxt = stub(r7, bytes.fromhex('f12089' 'fc') + le(0x910E))
    put(rom, 0x01, 0x9109, 'd803012089d80200', 'fc' + le(r7).hex() + 'ffff' 'd80200', 'chance: roll 7 cast call')
    assert nxt == CH_FREE + 0x69, hex(nxt)
    # --- roll 7, slot-0 'appeared' line: JP 'call $0156', RPGOne F4 (the caster) ------------
    # (same pattern as roll 0; the stub sits after fix_chance_confused_attack's 7 bytes at $FFA9)
    r7n = CH_FREE + 0x70
    stub(r7n, bytes.fromhex('d82500' 'f15601' 'fc') + le(0x914C))
    put(rom, 0x01, 0x9142, 'e9090c005791' 'd82500f4' + APPEARED + 'f0' 'e90a0c006e91',
        'e9090c005791' 'fc' + le(r7n).hex() + 'ff' + APPEARED + 'f0' 'e90a0c006e91', 'chance: roll 7 slot-0 name')


def fix_chance_confused_attack(rom, fl):
    # DQ2, a confused monster attacking (battle action $11, chosen at $0B:8AB7 only for a
    # monster whose confusion counter $1028+n is set; only Chance's confuse outcome sets it,
    # $0B:B090). RPGOne's script ($01:A2B8 DQ / $01:A2BA DW) is JP $01:F461 with two control
    # slips that show once fix_chance confuses every monster as JP does:
    #  - E8 [0C91]!=00 (damage dealt) still jumped to JP's $01:F492, untranslated leftover
    #    text whose D8 03 $F029 runs on into more leftovers: garbled Japanese, a stray
    #    "1 Key", and the battle ended with no rewards and the battle theme left playing.
    #    RPGOne's own copy of that block is right below ($A2EA DQ / $A2EC DW), same codes.
    #  - the no-damage line starts 'D8 00' where JP has 'D8 24 00', so D8 read $3C as a
    #    parameter count and swallowed the next 120 bytes. Restored through a 7-byte stub.
    a = 0xA2B8 if fl == 'dq' else 0xA2BA
    dmg, cont = a + 0x32, a + 0x0E                 # English damage block; byte after 'D8 00 3C'
    stub = CH_FREE + 0x69                          # after fix_chance's code, zero in v2.0
    put(rom, 0x01, a, 'e0600f6011' 'e8910c0092f4' 'd8003c' + '3842423433',
        'e0600f6011' 'e8910c00' + bytes([dmg & 0xFF, dmg >> 8]).hex() + 'fc' + bytes([stub & 0xFF, stub >> 8]).hex()
        + '3842423433', 'confused attack: damage target, no-damage line')
    put(rom, 0x01, dmg, 'e1b01007d82c00d82600fa8f0cde', 'e1b01007d82c00d82600fa8f0cde', 'confused attack: damage block')
    put(rom, 0x01, stub, '00' * 7, 'd824003c' 'fc' + bytes([cont & 0xFF, cont >> 8]).hex(), 'confused attack: D8 24 00 stub')


def fix_dq1_transform(rom, fl):
    # DQ1, Dragonlord refused twice: after battle 1 the field code ($00:9167, flag $52) shows
    # the message at LDY #msg / LDA #bank ($00:9186/$918B), then battle 2. RPGOne moved the
    # transformation script to bank $32 and repointed this in DW ($32:EAEC) but not in DQ,
    # which still pointed at JP's $01:CC83, now the middle of an unused copy of the accept
    # speech ("u half of the world of darkness! ... WA HA HA HA!"). RPGOne's DQ translation
    # of the scene is at $32:EA3E (same control codes as JP $01:CC83: $D5=1, flags $12/$10,
    # two D8 31 sound effects) and had no reference, so its line layout was never seen: the
    # first FD has no FE before it and the "disappears..." line has no F0, so in Mesen the
    # text ran together and off the window ("graduallydisapp|ears... ... ...What!King
    # Dragon's true|: form is revealed!"). The copy at $32:FF00 (free, zero in v2.0 DQ) is
    # that script with the line codes of RPGOne's own DW version ($32:EAEC): FE FD before
    # the second line, F0 after it, "What! <name>'s" FE "true form is revealed!". Wording,
    # flags and sound commands are unchanged. $32:EA3E itself is left as it was.
    if fl == 'dq':
        old = ('e1d50001ee1200d83100e5' + enc("King Dragon").hex() + '5542' + '00' + enc('form gradually').hex()
               + 'fd' + enc('disappears').hex() + '6000600060' + 'ee1000d83100e5' + enc('What').hex() + '58'
               + 'fd' + enc('King Dragon').hex() + '5542' + '00' + enc('true form is revealed').hex() + '58'
               + 'd8520000ff')
        new = ('e1d50001ee1200d83100e5' + enc("King Dragon").hex() + '5542' + '00' + enc('form gradually').hex()
               + 'fefd' + enc('disappears').hex() + '6000600060' + 'f0' + 'ee1000d83100e5' + enc('What').hex() + '58'
               + '00' + enc('King Dragon').hex() + '5542' + 'fe' + enc('true form is revealed').hex() + '58'
               + 'd8520000ff')
        n = len(new) // 2
        put(rom, 0x32, 0xEA3E, old, old, 'transform: RPGOne DQ script (unchanged)')
        put(rom, 0x32, 0xFF00, '00' * n, new, 'transform: DQ script, DW line layout')
        put(rom, 0x00, 0x9186, 'a083cc8453a9018555', 'a000ff8453a9328555', 'transform: pointer')
    else:
        put(rom, 0x00, 0x9186, 'a0ecea8453a9328555', 'a0ecea8453a9328555', 'transform (DW): already bank $32')


# ================================================================ v0.3 stage 2
# Data corruption and dialogue corrections. Each value comes from the Japanese original or from
# RPGOne's own text in the other flavor (noted per fix). Old bytes are asserted in full.

def fix_item_menu_name(rom, fl):
    # DQ2: RPGOne's item-name line-break handler ($30:8600, called from the expander at $09:A007
    # for every character drawn straight to a window) begins 'CMP #$2A / BEQ / RTL', then stores
    # the $2A into $7E016E. $016E is the 7th byte of party slot 2's 9-byte name ($0168, normally
    # the princess), so opening the Item menu with a two-line item name ("Leather / Armor")
    # replaced her 7th letter, or the end mark of a 6-letter name, and the save kept it. Nothing
    # reads $016E as a variable (no other access to it in the ROM), and JP has no such handler:
    # its code there is the dakuten test. The store is removed; the line break itself is kept.
    put(rom, 0x30, 0x8600, 'c92af0016b' '8f6e017e' 'c220a504186940', 'c92af0016b' 'eaeaeaea' 'c220a504186940',
        'item names: no store into the slot-2 name')


def fix_beran_inn_price(rom, fl):
    # DQ2, Beran inn (NPC records $1C:C92F/$1C:EC56 -> $34:B82D DQ / $34:B82B DW; JP $14:E0B7).
    # "One night is N gold." prints the number variable $0C91 (F6 91) in the DQ flavor, a leftover
    # value (damage, prices), where JP ($14:E0DF) and RPGOne's DW flavor print the inn price, $0C89.
    if fl == 'dq':       # "...night is " F6 91 00 " gold."
        put(rom, 0x34, 0xB86B, '4300384200f6910000363e3b33', '4300384200f6890000363e3b33', 'inn price variable')
    else:
        put(rom, 0x34, 0xB869, '4300384200f6890000363e3b33', '4300384200f6890000363e3b33', 'inn price (DW): already $0C89')


def fix_vault_balance(rom, fl):
    # DQ2 vault. The balance ($0D92, copied to $0C89 by $09:E077) goes up to 1,000,000 and a
    # deposit (in $0C91) up to 99,000, because the party may carry 99,999 gold ($1B:A479).
    # JP prints both with the 24-bit number code 'DB lo hi' (JP $2B:89FF 'DB 91 0C' for the
    # deposit, $2B:8C6F 'DB 89 0C' for the balance); RPGOne used the 16-bit 'F6 var 00', which
    # prints the value mod 65,536. Same length; DB prints without leading zeros like F6 ... 00.
    put(rom, 0x2B, 0x839E, 'fd5f8b' 'f69100' '00363e3b3351', 'fd5f8b' 'db910c' '00363e3b3351', 'vault: deposit amount, 24-bit')
    put(rom, 0x2B, 0x873C, '3d3600' 'f68900' '00363e3b3350', '3d3600' 'db890c' '00363e3b3350', 'vault: balance, 24-bit')


def fix_vault_balance_layout(rom, fl):
    # Layout only, no wording change (separate id so it can be dropped). "*: Currently, I'm holding
    # N gold." fills the window with a 4-digit N; with 5 digits (already possible in v0.2 for
    # 10,000-65,535) the final "." spills onto the start of the next row, and the 24-bit balance
    # can have 7 digits. JP puts the amount on the first line and breaks after it. The space after
    # "holding" becomes a line break (00 -> FE, same length): "Currently, I'm holding" / "N gold."
    o = off(0x2B, 0x873F)
    assert rom[o:o + 2] in (b'\xf6\x89', b'\xdb\x89'), 'vault: balance number code at 2B:873F'   # either order of ids
    put(rom, 0x2B, 0x8737, enc('holding').hex() + '00', enc('holding').hex() + 'fe', 'vault: balance line break')


AH_TABLE = 0xF96E          # $14: JP's table of 'after Hargon' far gotos, one 8-byte stub per message


def fix_after_hargon_villagers(rom, fl):
    # DQ2, villagers after Hargon (flag $CE). JP keeps one far-goto stub per shared message at
    # $14:F96E + 8k ('D8 3C 02 lo hi 2B 00 FF'); RPGOne kept the table and put its translations in
    # 128-byte slots at $33:8C00 + $80k. Every slot's message starts at the slot except the first,
    # whose message ("Thanks to you, peace has returned...", JP $2B:B99E) starts at $33:8C20 in
    # both flavors, yet its stub and RPGOne's two copies of it still pointed at $33:8C00. In DQ that
    # is the tail of an unrelated King line ("<HERO>, open that treasure chest!"); in DW it is 32
    # bytes of padding, printed as spaces. 15 NPC scripts reach these stubs.
    stubs = [(0x14, 0xEC23 if fl == 'dq' else 0xEC77), (0x14, AH_TABLE), (0x34, 0xE249 if fl == 'dq' else 0xE257)]
    put(rom, 0x33, 0x8C20, 'fd5f8b' + enc('Thanks to you').hex(), 'fd5f8b' + enc('Thanks to you').hex(),
        'after Hargon: slot-0 message at $33:8C20')
    for k in range(1, 28):                       # the other slots start at their slot address
        o = off(0x14, AH_TABLE + 8 * k)
        assert rom[o:o + 3] == b'\xd8\x3c\x02' and rom[o + 5] == 0x33, k
        assert rom[off(0x33, rom[o + 3] | rom[o + 4] << 8):][:3] == b'\xfd\x5f\x8b', k
    for b, a in stubs:
        put(rom, b, a, 'd83c02008c3300ff', 'd83c02208c3300ff', 'after Hargon: stub at %02X:%04X' % (b, a))


# Literal hex escapes left in RPGOne's text (",60", ",60,", ",60,fe", ",60,f0", ",fe"). Each one
# spells the code that RPGOne meant: $60 is the ellipsis, FE a new line, F0 a wait. Where the real
# code follows the literal, the literal is removed; where it does not (",60,How"), the literal
# becomes the ellipsis byte. RPGOne's DQ flavor has these lines without the escapes, and in every
# such line the result equals its DQ bytes. The text after each edit moves up to the message's end
# (its FF), the freed bytes become FF, and address operands inside the moved text are adjusted.
# check_fixes.py verifies that nothing else in the ROM points into a moved span.
L60, L60C, L60FE, L60F0, LFE = '510701', '51070151', '510701513534', '510701513501', '513534'
GARBAGE = {   # (bank, first edit, span end FF): [(address, old, new), ...]
    'dq': [
        ((0x14, 0x9AFC, 0x9B59), [(0x9AFC, LFE + 'fe', 'fe')]),                       # friend,,fe
        ((0x2B, 0x93F3, 0x9412), [(0x93F3, LFE + 'fe', 'fe')]),                       # cursed!,fe
        ((0x33, 0x9D32, 0x9E0C), [(0x9D32, L60FE + '60fe', '60fe')]),                 # Ah prince <HERO>,60,fe
        ((0x33, 0xA0D2, 0xA0EE), [(0xA0D2, L60FE + '60fe', '60fe')]),                 # Prince <HERO>,60,fe
        ((0x34, 0x88FF, 0x8928), [(0x88FF, LFE + 'fe', 'fe')]),                       # careful,,fe
    ],
    'dw': [
        ((0x2B, 0x93F2, 0x9411), [(0x93F2, LFE + 'fe', 'fe')]),
        ((0x33, 0x9D2C, 0x9E07), [(0x9D2C, L60FE + '60fe', '60fe')]),
        ((0x33, 0xA0D0, 0xA0EC), [(0xA0D0, L60FE + '60fe', '60fe')]),
        ((0x33, 0xB20D, 0xB231), [(0xB20D, L60FE + '60fe', '60fe')]),                 # Fix this one.,60,fe
        ((0x33, 0xB573, 0xB589), [(0xB573, L60C + '17', '6017'),                      # Oh,60,How
                                  (0xB583, L60 + '606060ff', '606060ff')]),           # terrible,60...
        ((0x33, 0xB5F8, 0xB64E), [(0xB5F8, L60C + '1f', '601f')]),                    # Pl,60,Please
        ((0x33, 0xB8DC, 0xB8E0), [(0xB8DC, L60 + '60ff', '60ff')]),                   # fire,60
        ((0x33, 0xBB1A, 0xBB1E), [(0xBB1A, L60 + '60ff', '60ff')]),                   # Hargon,60
        ((0x33, 0xBBB2, 0xBBD5), [(0xBBB2, L60C + '29', '6029'),                      # Zzz,60,Zzz
                                  (0xBBD1, L60 + '60ff', '60ff')]),                   # Zzz,60
        ((0x33, 0xBE11, 0xBE15), [(0xBE11, L60 + '60ff', '60ff')]),                   # Ahhhh,60
        ((0x33, 0xC1AB, 0xC1AF), [(0xC1AB, L60 + '60ff', '60ff')]),                   # crackle,60
        ((0x33, 0xC314, 0xC414), [(0xC314, L60C + '6060d852', '6060d852'),            # I,60,
                                  (0xC3FE, L60 + '60d854', '60d854'),                 # forth,60
                                  (0xC40A, L60C + '58', '6058')]),                    # Ugghh,60,!
        ((0x33, 0xC64C, 0xC650), [(0xC64C, L60 + '60ff', '60ff')]),                   # be?,60
        ((0x33, 0xC6F7, 0xC6FB), [(0xC6F7, L60 + '60ff', '60ff')]),                   # That is decided,60
        ((0x33, 0xC77A, 0xC77E), [(0xC77A, L60 + '60ff', '60ff')]),                   # All is decided,60
        ((0x33, 0xC9CA, 0xCAA9), [(0xC9CA, L60FE + '60fe', '60fe'),                   # nun: <HERO>,60,fe
                                  (0xC9DB, L60FE + '60fe', '60fe'),                   # <Cannock>,60,fe
                                  (0xC9E6, L60F0 + '60f0', '60f0')]),                 # <princess>,60,f0
        ((0x34, 0x8903, 0x892C), [(0x8903, LFE + 'fe', 'fe')]),                       # careful,,fe
    ],
}
TLEN = {0xE0: 5, 0xE1: 4, 0xE7: 3, 0xE8: 6, 0xE9: 6, 0xEA: 5, 0xFB: 5, 0xEE: 3, 0xEF: 3, 0xF1: 3, 0xF5: 2,
        0xFC: 3, 0xF6: 3, 0xDB: 3, 0xF7: 4, 0xFA: 4, 0xDE: 3}
TONE = {0xF0, 0xF4, 0xFD, 0xFE, 0xE2, 0xE5, 0xDC, 0xDD}


def text_operands(rom, bank, start, stop):
    """Address operands in the script bytes start..stop (inclusive): [(operand address, target)].
    Fails on a code whose length is not known, so a misparse cannot go unnoticed."""
    out, a = [], start
    while a <= stop:
        o = off(bank, a)
        x = rom[o]
        if x < 0xD8 or x in TONE or x == 0xFF:
            a += 1
        elif x == 0xD8:
            n = rom[o + 2]
            out += [(a + 3 + 2 * k, rom[o + 3 + 2 * k] | rom[o + 4 + 2 * k] << 8) for k in range(n)]
            a += 3 + 2 * n
        elif x in TLEN:
            p = {0xE8: 4, 0xE9: 4, 0xEA: 3, 0xFB: 3, 0xFC: 1}.get(x)
            if p:
                out.append((a + p, rom[o + p] | rom[o + p + 1] << 8))
            a += TLEN[x]
        else:
            raise SystemExit('text: unknown code %02X at %02X:%04X' % (x, bank, a))
    return out


def shrink_text(rom, bank, start, stop, edits, what):
    """Apply same-or-shorter edits inside bank:start..stop (stop = the FF ending the span), move
    the rest of the span up, fill the freed bytes with FF and adjust address operands that point
    into the span. Returns the old -> new address map of the span."""
    assert rom[off(bank, stop)] == 0xFF, what
    ops = text_operands(rom, bank, start, stop)
    new, amap, a, ei = bytearray(), {}, start, 0
    edits = sorted(edits)
    while a <= stop:
        if ei < len(edits) and a == edits[ei][0]:
            ea, old, nw = edits[ei]
            old, nw = bytes.fromhex(old), bytes.fromhex(nw)
            put(rom, bank, ea, old, old, what)          # assert
            assert old.endswith(nw[1:]) and len(nw) <= len(old), (what, hex(ea))
            # the kept real bytes are the tail of 'old'; map them to their new place
            for k in range(len(nw)):
                amap[ea + len(old) - len(nw) + k] = start + len(new) + k
            new += nw
            a += len(old)
            ei += 1
            continue
        amap[a] = start + len(new)
        new.append(rom[off(bank, a)])
        a += 1
    assert ei == len(edits), what
    for opa, tgt in ops:                            # operand positions and targets inside the span
        if start < tgt <= stop:
            if tgt not in amap:
                raise SystemExit('%s: operand at %02X:%04X targets an edited byte %04X' % (what, bank, opa, tgt))
            nt = amap[tgt]
            p = amap[opa] - start
            new[p], new[p + 1] = nt & 0xFF, nt >> 8
    new += b'\xff' * (stop + 1 - start - len(new))
    rom[off(bank, start):off(bank, stop) + 1] = new
    return amap


def fix_garbage_text(rom, fl):
    for (bank, start, stop), edits in GARBAGE[fl]:
        shrink_text(rom, bank, start, stop, [(a, o, n) for a, o, n in edits], 'garbage %02X:%04X' % (bank, start))


def fix_curse_laugh_line(rom, fl):
    # DQ2, curse-removal NPC (dispatcher $34:8DC7 DQ / $34:8DCF DW; JP $14:C83B -> $14:C8A3) when a
    # member is cursed: "*: Wow! / This is a new type of / curse that I can't remove. / You have to
    # excuse me." D8 52 (a short pause with a sound, as in JP) FE "Heh heh heh...". The laugh is a
    # 5th line in the 4-row window, started right after the pause, and it is drawn over row 1
    # instead of scrolling: garbled text. JP's message is 4 lines (its first line holds "Wow! This
    # is a new", the laugh shares the 4th). RPGOne's English is too wide to put the laugh on the
    # 4th line, so "Wow!" joins the 2nd line instead (FE -> space): 4 lines, the pause and the laugh
    # unchanged. Layout only; no wording change.
    s = 0x8E63 if fl == 'dq' else 0x8E6B
    a = 0x8EB2 if fl == 'dq' else 0x8EBA
    put(rom, 0x34, a - 3, '3c3450' 'd85200' 'fe' + enc('Heh').hex(), '3c3450' 'd85200' 'fe' + enc('Heh').hex(),
        'curse laugh: pause + new line (unchanged)')
    put(rom, 0x34, s, 'fd5f8b' + enc('Wow').hex() + '58' 'fe' + enc('This').hex(),
        'fd5f8b' + enc('Wow').hex() + '58' '00' + enc('This').hex(), 'curse laugh: "Wow!" joins the next line')


def fix_poison_cure_message(rom, fl):
    # DQ2 battle script for the poison-cure result (index 1 of the spell switch 'D8 10' at
    # $01:8937; JP $01:DF93 -> $E00C). JP calls the cast message (F1 7B DF) and then restarts
    # the window on "The poison was removed from X's body!" (D8 03 -> $E015). RPGOne jumped to
    # the cast message instead (D8 03 -> $8920, which ends with FF) and called the poison text
    # after it, so the script ended after "X casts ...!" and skipped the battle's common tail, as
    # in Chance rolls 4 and 7 before v0.3. Same length: call the cast message, restart on $89DE.
    put(rom, 0x01, 0x89D5, 'd803012089' 'f1de89' 'ff' '233734', 'f12089' 'd80301de89' 'ff' '233734', 'poison cure: call, then restart')


# ================================================================ v0.3 stage 3
# Translation polish and consistency. Names come from the same flavor's own item and monster tables
# (RPGOne's choice for that flavor), control codes from the Japanese original, wording from RPGOne's
# text in the other flavor where one exists. Old bytes are asserted in full.
#
# Text whose length changes is not moved: the first len(old)-3 bytes of the new text are written in
# place, then 'FC lo hi' (the expander's goto, handler $09:A1B4: it only reloads the read pointer and
# writes nothing to the text buffer) jumps to a short stub in zero-filled free space of the same bank,
# which holds the rest of the new text and 'FC' back to the byte after the old text. The window shows
# exactly the new text; no other byte of the message moves. Each fix has its own stub addresses, so
# every fix can be applied or skipped on its own.

def fc(a):
    assert 0x8000 <= a and 0xFF not in (a & 0xFF, a >> 8), hex(a)
    return bytes([0xFC, a & 0xFF, a >> 8])


def reword(rom, bank, at, old, new, stub, what):
    old = bytes.fromhex(old) if isinstance(old, str) else bytes(old)
    new = bytes.fromhex(new) if isinstance(new, str) else bytes(new)
    put(rom, bank, at, old, old, what)
    if len(new) == len(old):
        put(rom, bank, at, old, new, what)
        return
    k = len(old) - 3
    assert k >= 0 and stub, what
    tail = new[k:] + fc(at + len(old))
    put(rom, bank, stub, bytes(len(tail)), tail, what + ' (stub)')
    put(rom, bank, at, old, new[:k] + fc(stub), what)


def enct(s):
    """enc() plus the punctuation used in the names below."""
    p = {'.': 0x50, ',': 0x51, "'": 0x55, '!': 0x58, '?': 0x59}
    return b''.join(bytes([p[c]]) if c in p else enc(c) for c in s)


# Names in dialogue that disagree with the flavor's own item table ($09:E927/$09:E9FB) or with the
# flavor's naming elsewhere. (fix id, flavor, [(bank:addr, stub)], old, new); stub None = same length.
NAMES = [
    # DQ item table: Gold Key ($55). Dialogue had the DW name Golden Key.
    ('dq_gold_key', 'dq', [('14:99FF', 0xFA60), ('33:C5FD', 0xE008), ('34:8AF6', 0xE400), ('34:9D89', 0xE408),
                           ('34:9E80', 0xE410), ('34:9F87', 0xE418), ('34:C9E4', 0xE420), ('34:CAD7', 0xE428)],
     'Golden Key', 'Gold Key'),
    # DQ item table: Rain Cloud Staff ($1C). Dialogue and the use message had the DW name Staff of Rain.
    ('dq_rain_cloud_staff', 'dq', [('01:AE74', 0xFED0), ('01:B1AB', 0xFED9), ('2B:CAAB', 0xD690),
                                   ('32:D536', 0xFC00), ('32:D573', 0xFC10)], 'Staff of Rain', 'Rain Cloud Staff'),
    # DQ item table: Warrior's Ring ($23); DW calls it Fighter's Ring.
    ('dq_warriors_ring', 'dq', [('32:C779', None)], "Fighter's Ring", "Warrior's Ring"),
    # DQ item table: Sacred Loom ($5C); DW Magic Loom.
    ('dq_sacred_loom', 'dq', [('34:B20E', 0xE430)], 'Magic Loom', 'Sacred Loom'),
    # DQ item table: Bell Amulet ($4B); DW Dragon's Bane. The other DQ line ($14:961B) already says Bell Amulet.
    ('dq_bell_amulet', 'dq', [('33:B97B', 0xE000)], "Dragon's Bane", 'Bell Amulet'),
    # DQ item table and its use message ($2B:98FA): Statue of Evil ($53); DW Eye of Malroth.
    ('dq_statue_of_evil', 'dq', [('34:D539', None), ('34:D626', None), ('34:DE8F', None)], 'Eye of Malroth', 'Statue of Evil'),
    # DQ1 princess: Laura in the DQ flavor (73 lines), Gwaelin in DW.
    ('dq_laura', 'dq', [('01:C2E0', 0xFEE9)], 'Gwaelin', 'Laura'),
    # DQ1 final boss after the battle ($00:91B2 -> $01:FE30): DQ dialogue says King Dragon, DW Dragonlord.
    ('dq_king_dragon_hand', 'dq', [('01:FE56', 0xFEE2)], "Dragonlord's", "King Dragon's"),
    # Wrong item: $00:BFC3 shows this when item $14 (Dragon's Scale) is already worn (JP $2B:909D, DW the
    # same line with Dragon's Scale); the DQ line named the Bell Amulet.
    ('dq_dragon_scale_check', 'dq', [('2B:8CC5', 0xD680)], 'Bell Amulet.', "Dragon's Scale."),
    # DW item table: Fairy Water ($17/$49); two DQ1 lines had the DQ name Holy Water.
    ('dw_fairy_water', 'dw', [('01:9B67', 0xFED0), ('01:CAE6', 0xFED7)], 'Holy Water', 'Fairy Water'),
    # DW town: Hauksness in its three other lines.
    ('dw_hauksness', 'dw', [('32:F20E', 0xFC20)], 'Haukness', 'Hauksness'),
    # Wrong prize name: the lottery's 4th prize gives item $4B (E1 E8 00 4B, D8 24), which DW calls
    # Dragon's Bane (DQ: Bell Amulet, as its line says); the DW line named the Dragon Scale.
    ('dw_lottery_prize', 'dw', [('2B:C779', 0xD6B0)], 'Dragon Scale!', "Dragon's Bane!"),
    # Spelling (documented in the audit), both flavors.
    ('typo_miracle', 'dq', [('34:D5F2', None)], 'mircale', 'miracle'),
    ('typo_miracle', 'dw', [('34:D5FC', None)], 'mircale', 'miracle'),
    ('typo_far_too', 'dq', [('2B:BB51', 0xD6A0)], 'far to important', 'far too important'),
    ('typo_far_too', 'dw', [('2B:BB55', 0xD6A0)], 'far to important', 'far too important'),
]


def name_fix(fid):
    def fn(rom, fl):
        for f, nfl, sites, old, new in NAMES:
            if f != fid:
                continue
            for where, stub in sites:
                b, a = (int(x, 16) for x in where.split(':'))
                if nfl == fl:
                    reword(rom, b, a, enct(old), enct(new), stub, '%s %s' % (fid, where))
    return fn


# Lines that name the hero (F4) where JP names the party's lead member (F5 95: the first living member,
# the one who walks in front), and that can be shown while the hero is dead. (JP address of the F5 95,
# DQ site, DW site, old bytes from the F4 on, new bytes). Stubs: 8 bytes each from STUB_LEAD[bank].
LEAD = [
    # greetings before the level advice, chosen by map (E9 [0021]==...): King of Laurasia "Ahh <name>, You're
    # back!", priests "Oh <name>, you've returned!" and "Ah <name>, you're back!" (JP $14:82F3/$830C/$8325)
    ('14:82F3', '14:84AF', '14:84B0', 'f451fe', 'f59551fe'),
    ('14:830C', '14:84CC', '14:84CD', 'f45100', 'f5955100'),
    ('14:8325', '14:84EC', '14:84ED', 'f45100', 'f5955100'),
    # King of Laurasia / priests, flag $0E farewell (JP $14:8662), shared "*:" line
    ('14:8662', '14:89CE', '14:89CC', 'f458ff', 'f59558ff'),
    # King of Laurasia, map $35: "Until we meet again, <name>!" (JP $14:86AB)
    ('14:86AB', '14:8A5E', '14:8A5D', 'f458ff', 'f59558ff'),
    # King of Laurasia, hero at 0 HP (E9 [0C09]==00): "<name> I ask that you serve my son well." (JP $14:86D1)
    ('14:86D1', '14:8A9D', '14:8A9D', 'f40018', 'f5950018'),
    # King of Sumaltria/Cannock, flag $09: "Ah, it's <name>" (JP $14:9C74). DQ also lacked the space
    # after "it's" that DW has.
    ('14:9C74', '14:B082', '14:B094', ('f4fe00', 'f450fe'), ('00f595fe00', 'f59550fe')),
    # same King, flag $AD: "There you are <name>." (JP $14:9D15)
    ('14:9D15', '14:B172', '14:B18B', 'f450f0', 'f59550f0'),
    # same King, flag $0B: "Now <name> we will all be waiting." (JP $14:9DD3)
    ('14:9DD3', '14:B2C6', '14:B2DF', 'f4fe00', 'f595fe00'),
    # priests (shared save script, JP $14:A839 -> $14:AB20): "Rest well <name>!" (JP $14:AB2F)
    ('14:AB2F', '14:C8DB', '14:C907', 'f458fe', 'f59558fe'),
    # priests' farewells (JP $14:AB8B, $14:AB97, $14:ABBC)
    ('14:AB8B', '14:C969', '14:C996', 'f458ff', 'f59558ff'),
    ('14:AB97', '14:C976', '14:C9A4', 'f458ff', 'f59558ff'),
    ('14:ABBC', '14:C9C6', '14:C9F5', 'f458ff', 'f59558ff'),
    # former Laurasia servant, hero at 0 HP branch: "...a baby, <name>." (JP $14:A474)
    ('14:A474', '14:BDA7', '14:BDD5', 'f450fe', 'f59550fe'),
    # messenger, reached from the hero-at-0-HP / prince-alive branch: "Oh is that you <name>?" (JP $14:DD5A)
    ('14:DD5A', '34:B309', '34:B30F', 'f459fe', 'f59559fe'),
    # King of Dercondal: "Ah <name>! Welcome to Dercondal Castle!" (JP $14:E87E)
    ('14:E87E', '34:C481', '34:C481', 'f458fe', 'f59558fe'),
    # two villagers (JP bank $0F): "Ahh, It's <name>." and "...meet Hargon, <name>," (JP $0F:E6A1, $0F:E9A2)
    ('0F:E6A1', '33:B6B2', '33:B6C5', 'f450fe', 'f59550fe'),
    ('0F:E9A2', '33:BC1B', '33:BC3C', 'f451fe', 'f59551fe'),
    # priest (JP $14:F7FF), before Hargon: "So you have come <name>!" (JP $14:F80B)
    ('14:F80B', '34:E02E', '34:E038', 'f458f0', 'f59558f0'),
]
STUB_LEAD = {0x14: 0xFA70, 0x33: 0xE010, 0x34: 0xE440}


def lead_edit(rom, fl, entry):
    """(address, old, new) for one LEAD entry. Where the name ends its message ('F4 x FF'), the edit
    starts two text bytes earlier instead, so that the message's FF stays where it is."""
    jp, dq, dw, old, new = entry
    b, a = (int(x, 16) for x in (dq if fl == 'dq' else dw).split(':'))
    o, n = (old[0 if fl == 'dq' else 1], new[0 if fl == 'dq' else 1]) if isinstance(old, tuple) else (old, new)
    o, n = bytes.fromhex(o), bytes.fromhex(n)
    if o.endswith(bytes([0xFF])):
        pre = bytes(rom[off(b, a) - 2:off(b, a)])
        assert all(c < 0xD8 or c == 0xFE for c in pre), (dq, pre.hex())
        return b, a - 2, pre + bytes([0xF4]), pre + bytes([0xF5, 0x95])
    return b, a, o, n


def fix_lead_member_names(rom, fl):
    used = {}
    for entry in LEAD:
        b, a, o, n = lead_edit(rom, fl, entry)
        k = used.get(b, 0)
        used[b] = k + 1
        reword(rom, b, a, o, n, STUB_LEAD[b] + 8 * k, 'lead name %02X:%04X' % (b, a))


def fix_cannock_king_lead(rom, fl):
    # King of Sumaltria/Cannock, flag $0A: "Well F5 FE seek out my son, <prince>." F5 FE prints the
    # string at the pointer in $0CFE/$0CFF (garbage); JP's line ($14:9CEA) has F5 95, the lead member.
    # Layout: RPGOne wrote the whole line as one row ("King: Well X seek out my son, <prince>."), which the
    # garbage hid; with the names it is 206-248 pixels wide and wraps mid-name (seen in Mesen: "Rola|ndo").
    # A line break after the lead's name, followed by a space as in RPGOne's other King lines ("/ I can never
    # count on you."): "King: Well <lead>" / " seek out my son, <prince>." JP's line also has 3 rows.
    a = 0xB13A if fl == 'dq' else 0xB153
    put(rom, 0x14, a, enc('Well').hex() + '00f5fe00' + enc('seek').hex(), enc('Well').hex() + '00f5fe00' + enc('seek').hex(),
        'Cannock King: F5 FE')
    reword(rom, 0x14, a + 5, 'f5fe00', 'f595fe00', 0xFA68, 'Cannock King: F5 95, line break')


def fix_king_princess_reply(rom, fl):
    # King of Laurasia, party of three, first meeting with the princess ("Oh, is that the Princess of
    # Moonbrook?! ... feel free to come and talk with me."): the reply "Thank you, King of ..." is spoken
    # by the princess in JP ($14:81F1 'F1 92 01', her fixed name). RPGOne named party slot 1 (F1 5F 01),
    # which v0.2's identity fix turned into the prince's fixed name (F1 89 01): still the wrong speaker.
    a = 0x831E if fl == 'dq' else 0x8329
    put(rom, 0x14, a, 'fdf1890152', 'fdf1920152', 'princess reply speaker')


FS_STUB = 0xD6C0          # $2B: four 4-byte stubs 'F0 FC lo hi'


def fix_field_spell_wait(rom, fl):
    # DQ2 field spell ($00:CC8E -> $2B:ABE0, both flavors; JP $2B:A5A5). JP shows "<caster> casts <spell>!",
    # plays the effect, then waits once (F0) at the start of the result: switch D8 23 -> $A610 (F0, "nothing
    # happened") or the spell dispatch $A5D3, whose results all begin with F0 except spell $1F's. RPGOne put
    # one F0 after the cast line ($2B:ABF2) and dropped it from the results "nothing happened" ($AC4B), $1A
    # ($95CA DQ / $95CB DW), $20 ($AC96) and $09/$1D ($AD17), but kept it in the heal results ($ACEE): so the
    # heal spells needed two button presses and spell $1F one, where JP needs one and none. JP's layout is
    # restored: the cast-line F0 is removed (the rest of that message, 7 codes up to its FF at $AC0D, moves
    # up one byte; its switch targets are outside the moved bytes) and the four result paths without F0 go
    # through a 4-byte stub 'F0 FC <old target>'.
    put(rom, 0x2B, 0xABE6, 'e5f4' + '00' + enc('casts').hex() + '00f59358f0e1b01002', 'e5f4' + '00' + enc('casts').hex() + '00f59358f0e1b01002',
        'field spell: cast line')
    p1a = 0x95CA if fl == 'dq' else 0x95CB
    paths = [(0xAC09, 0xAC4B, 'D8 23 #0'),                   # operand of D8 23 (before the move below)
             (0xAC0E + 6 * 5 + 4, p1a, 'spell $1A'), (0xAC0E + 6 * 6 + 4, 0xAC96, 'spell $20'),
             (0xAC0E + 6 * 7 + 4, 0xAD17, 'spell $09'), (0xAC0E + 6 * 8 + 4, 0xAD17, 'spell $1D')]
    put(rom, 0x2B, 0xAC0E + 6 * 9, 'e9c4001f51ac', 'e9c4001f51ac', 'field spell: dispatch ends with $1F')
    stubs = {}
    for at, tgt, what in paths:
        if tgt not in stubs:
            s = FS_STUB + 4 * len(stubs)
            put(rom, 0x2B, s, '00' * 4, b'\xf0' + fc(tgt), 'field spell: wait stub for ' + what)
            stubs[tgt] = s
        put(rom, 0x2B, at, bytes([tgt & 0xFF, tgt >> 8]), bytes([stubs[tgt] & 0xFF, stubs[tgt] >> 8]), 'field spell: ' + what)
    shrink_text(rom, 0x2B, 0xABF2, 0xAC0D, [(0xABF2, 'f0e1', 'e1')], 'field spell wait')


EXP_SITES = {'dq': ['14:8546', '14:85D4', '14:866B', '14:C502', '14:C586', '14:C613', '2B:9E8C', '2B:9F14', '2B:9F9F',
                    '34:8489', '34:850F', '34:859C'],
             'dw': ['14:8546', '14:85D3', '14:866A', '14:C52E', '14:C5B2', '14:C63F', '2B:9E9D', '2B:9F1F', '2B:9FA9',
                    '34:8499', '34:851F', '34:85AC']}


def fix_exp_to_next_24bit(rom, fl):
    # DQ2 "<name>, to reach the next level, you need N experience." N is 24-bit: $0B:9952 stores the
    # low word at $0C91 and the high byte at $0C93 (threshold - EXP). JP prints it with 'DB 91 0C' at its
    # 12 matching sites; RPGOne used the 16-bit 'F6 91 00'. The princess's gaps from level 29 up are
    # 90,000-100,000 EXP (table $0B:B893), so she could be told e.g. 24464 instead of 90000. DQ1 lines
    # (bank $01) are 16-bit in JP too and are not touched.
    for where in EXP_SITES[fl]:
        b, a = (int(x, 16) for x in where.split(':'))
        o = off(b, a)
        assert enc('experience') in rom[o + 3:o + 14], 'exp ' + where      # DW's bank-$2B lines have no space
        put(rom, b, a, 'f69100', 'db910c', 'exp ' + where)


def fix_dq1_died_in_battle(rom, fl):
    # DQ1 King after the party is wiped out: "Oh... <HERO>, it seems you've di... in battle!" ($01:BBBE).
    # The bytes '60 8B' (an ellipsis and $8B, JP's opening-quote code: a talk sound and an indent mark)
    # stand where RPGOne's DW line ($01:BBCE) has "ed". DQ only.
    if fl == 'dq':
        put(rom, 0x01, 0xBBBE, '3338608b00' + enc('in').hex(), '3338343300' + enc('in').hex(), 'died in battle')
    else:
        put(rom, 0x01, 0xBBCE, enc('died').hex(), enc('died').hex(), 'died in battle (DW): already right')


def fix_laurasia_king_wait(rom, fl):
    # King of Laurasia after the party was wiped out: "Pitiful Prince... / I can never count on you."
    # then flag $03 and a window restart into his next speech. The line ended with FE, so the next
    # speech followed on the next row with no button wait; JP ($14:8126) ends it with F0. Both flavors.
    a = 0x8193 if fl == 'dq' else 0x8192
    put(rom, 0x14, a - 13, enc('count on you').hex() + '50' 'fe' 'ee0300d803', enc('count on you').hex() + '50' 'f0' 'ee0300d803',
        'pitiful prince wait')


TRAILING_2A = [0xD5D9, 0xD783, 0xE0D0, 0xE0E4, 0xE0EB, 0xE0F7]   # $01: Iron Axe, Hade's Shield, Life Crest, Club, Torch, Lithograph


def fix_item_name_trailing_break(rom, fl):
    # DQ only. RPGOne's $2A is the line break inside two-line item names in menus; in a message it is drawn
    # as a 4-pixel blank. Six names in the DQ item tables ($09:E927/$09:E9FB pointers) end with a $2A, so
    # messages showed "AAA used the Iron Axe !" (checked in Mesen). The $2A becomes the end mark; the old FF
    # after it stays. Names are reached only through the pointer tables, so nothing else moves.
    if fl == 'dq':
        for a in TRAILING_2A:
            put(rom, 0x01, a, '2aff', 'ffff', 'item name end %04X' % a)


def fix_beer_thief_wait(rom, fl):
    # DQ only. Thief after Hargon: "Peace has returned to the world. / Can you forgive me for stealing..."
    # ran straight into "*: Ohh, I've been dying for a beer!" in the same window (FE). JP ($14:97DF) and
    # RPGOne's DW line wait (F0) first.
    if fl == 'dq':
        put(rom, 0x14, 0xA925, enc('stealing').hex() + '60' 'fe' 'fd5f8b', enc('stealing').hex() + '60' 'f0' 'fd5f8b', 'beer thief wait')
    else:
        put(rom, 0x14, 0xA93B, enc('stealing').hex() + '60' 'f0' 'fd5f8b', enc('stealing').hex() + '60' 'f0' 'fd5f8b', 'beer thief (DW): already F0')


# ================================================================ v0.3 stage 4
# Final cleanup. Same rules as stage 3: old bytes asserted in full, text whose length changes goes
# through 'reword' detours with fixed per-fix stubs in zero-filled space, nothing moves.

def fix_field_heal_line_break(rom, fl):
    # Layout only. The field heal result "<target>'s wounds were healed!" ($2B:ACC9 after an item,
    # $2B:ACF2 after a spell; both flavors) is one row: 138 px plus the name, and the window holds
    # 206 px, so names wider than 68 px ("Mmmmmmmm", 87 px) run past the edge and the renderer wraps
    # "heal|ed!" over the next row (Mesen). RPGOne's battle copies of the line ($01:9A45, $01:ABCB)
    # break after "wounds"; the field copies now do the same (space -> FE, same length). Widest
    # possible first row: 8 x 11 px + 58 px = 146 px.
    for a in (0xACD2, 0xACFB):                       # the space after "wounds"
        put(rom, 0x2B, a - 11, 'f58f55' + enc('s wounds').hex() + '00' + enc('were healed').hex() + '58fe',
            'f58f55' + enc('s wounds').hex() + 'fe' + enc('were healed').hex() + '58fe', 'heal line break %04X' % a)


# Field messages of Dragon Quest II that name the member in $AE (F4) or in the pointer $0C8F (F5 8F)
# where JP names the lead member (F5 95). Opening the field command menu clears $AE ($00:904A), and
# neither the Search code nor the chest handlers ($1B:9413, $1B:9322) set it or $0C8F, so these lines
# named the hero even at 0 HP (seen in Mesen: "AAA searched all around..." with AAA dead; JP: the
# lead). (JP address of the F5 95, DQ site, DW site, old bytes, new bytes); stubs 8 bytes from FA_STUB.
FIELD_LEAD = [
    ('2B:9FB4', '2B:A380', '2B:A389', 'f40042', 'f5950042'),    # Search, hidden item: "<F4> searched all around..."
    ('2B:9FD0', '2B:A3A0', '2B:A3A9', 'f40033', 'f5950033'),    # Search at sea: "<F4> dove off the side of the ship!"
    ('2B:A225', '2B:A6FD', '2B:A6FD', 'f4003e', 'f595003e'),    # drawer: "<F4> opened the drawer and looked inside..."
    ('2B:A246', '2B:A731', '2B:A731', 'f4003b', 'f595003b'),    # pot: "<F4> looked inside the pot..."
]
FA_STUB = 0xD6D0          # $2B: 4 x 8 bytes


def fix_field_action_lead(rom, fl):
    for k, entry in enumerate(FIELD_LEAD):
        b, a, o, n = lead_edit(rom, fl, entry)
        reword(rom, b, a, o, n, FA_STUB + 8 * k, 'field lead %02X:%04X' % (b, a))
    # Trap chest ($C4 = $0A): "Huh? The treasure chest was a trap! <$0C8F> was poisoned!" The code right
    # after it poisons the first living member ($0C55/$0C56/$0C57 by HP), and JP ($2B:A408) names the lead.
    # $0C8F is whatever an earlier item or spell left there ($0000 after loading the test state).
    put(rom, 0x2B, 0xA98E, 'f58f00' + enc('was').hex(), 'f59500' + enc('was').hex(), 'trap chest: poisoned member')


# Spelling (approved for stage 4), as NAMES: (fix id, flavor, [(bank:addr, stub)], old, new).
TYPOS = [
    ('typo_retrieve', 'dq', [('01:AE0B', None), ('01:B143', None), ('2B:8863', None)], 'retreive', 'retrieve'),
    ('typo_retrieve', 'dw', [('01:AE0B', None), ('01:B149', None), ('2B:8863', None)], 'retreive', 'retrieve'),
    ('typo_possession', 'dq', [('2B:A2E5', 0xD6F0), ('32:D7B1', 0xFC30), ('34:9D3B', 0xE460), ('34:B5AD', 0xE468),
                               ('34:DE7E', 0xE470)], 'possesion', 'possession'),
    ('typo_possession', 'dw', [('2B:A2EE', 0xD6F0), ('32:D84A', 0xFC30), ('34:9D54', 0xE460), ('34:B5AB', 0xE468),
                               ('34:DE87', 0xE470)], 'possesion', 'possession'),
    ('typo_your_arrival', 'dq', [('14:99AD', 0xFAF0)], 'you arrival', 'your arrival'),
    ('typo_your_arrival', 'dw', [('14:99B8', 0xFAF0)], 'you arrival', 'your arrival'),
    ('typo_forward', 'dq', [('14:8A74', 0xFAF8), ('34:9466', 0xE478)], 'foward', 'forward'),
    # DQ only: "<prince>, To reach the next level" (DW's line has no name before it and starts the sentence)
    ('typo_to_reach_case', 'dq', [('2B:9EF2', None)], 'To reach', 'to reach'),
    # DW only: the three bank-$2B level-advice lines read "you need 1234experience." (DQ: "1234 experience")
    ('dw_exp_space', 'dw', [('2B:9EA0', 0xD6F8), ('2B:9F22', 0xD700), ('2B:9FAC', 0xD708)], 'experience', ' experience'),
]


def table_fix(table, fid):
    def fn(rom, fl):
        for f, nfl, sites, old, new in table:
            if f != fid or nfl != fl:
                continue
            for where, stub in sites:
                b, a = (int(x, 16) for x in where.split(':'))
                reword(rom, b, a, enct(old), enct(new), stub, '%s %s' % (fid, where))
    return fn


def fix_dw_evil_shield_space(rom, fl):
    # DW only. Item $43 ($09:E927/$09:E9FB -> $01:D78E) is "Evil{2A} Shield": RPGOne's menu line break $2A
    # plus a space, so the Item menu's second row reads " Shield" and messages "Evil  Shield" (the $2A is a
    # 4-px blank in messages). RPGOne's other two-line names have no space after the $2A ("Evil{2A}Tree").
    # The name is reached only through the two pointer tables, so its tail moves up one byte; the old FF stays.
    if fl == 'dw':
        put(rom, 0x01, 0xD78E, enc('Evil').hex() + '2a00' + enc('Shield').hex() + 'ff',
            enc('Evil').hex() + '2a' + enc('Shield').hex() + 'ffff', 'Evil Shield name')
    # DQ: item $43 is "Hade's Shield" (one line; its trailing $2A is item_name_trailing_break's)


# Stray $8B (JP's opening quote) inside RPGOne's sentences, not after a speaker label. The renderer ($00:B25E)
# plays the talk sound $14 for it and sets the hanging indent; in these lines the effect is an extra talk sound
# in mid-sentence (the next lines start at the left margin either way: Mesen). Removed through a 5-byte stub
# 'rest FC back'.
# (flavor, site of the $8B, the two bytes after it, stub)
STRAY_8B = [
    ('dq', '14:81D0', 'fe00', 0xFB00), ('dq', '14:89B6', 'f458', 0xFB08), ('dq', '14:8C6D', 'fe33', 0xFB10),
    ('dq', '14:8CEC', 'fe33', 0xFB18), ('dq', '14:8D6B', 'fe33', 0xFB20), ('dq', '14:9174', 'f451', 0xFB28),
    ('dq', '14:B07F', '5542', 0xFB30), ('dq', '2B:81F2', 'fe32', 0xD710), ('dq', '2B:83F1', 'fe28', 0xD718),
    ('dq', '2B:B152', 'f450', 0xD720), ('dq', '2B:B4BC', 'f458', 0xD728), ('dq', '33:B9C8', '5542', 0xE020),
    ('dq', '34:A1D5', '5542', 0xE480),
    ('dw', '14:81CF', 'fe00', 0xFB00), ('dw', '14:8C6D', 'fe33', 0xFB10), ('dw', '14:8CEC', 'fe33', 0xFB18),
    ('dw', '14:8D6B', 'fe33', 0xFB20), ('dw', '14:9178', 'f451', 0xFB28), ('dw', '14:B090', '5542', 0xFB30),
    ('dw', '2B:81F2', 'fe32', 0xD710), ('dw', '2B:83F1', 'fe28', 0xD718), ('dw', '2B:B152', 'f450', 0xD720),
    ('dw', '2B:B4BC', 'f458', 0xD728), ('dw', '33:B9E0', '5542', 0xE020), ('dw', '34:A1F0', '5542', 0xE480),
]


def fix_stray_quote_codes(rom, fl):
    for sfl, where, nxt, stub in STRAY_8B:
        if sfl == fl:
            b, a = (int(x, 16) for x in where.split(':'))
            reword(rom, b, a, '8b' + nxt, nxt, stub, 'stray $8B %s' % where)


# ---------------------------------------------------------------- v0.3 stage 4, RC2 (final cleanup)

def fix_coffin_discard_message(rom, fl):
    # DQ2 Item menu, Discard on a dead member's item (code $00:BB3x sets flag 2; message $2B:A9BA, JP $2B:A457).
    # JP $2B:A4CC: 'E9 [00E8]==5A -> A4F2', the text "<lead> takes <item> from <F4>'s coffin and discards it",
    # 'EE 00' (flag 0: the code then removes the item), FF; at A4F2 the Leaf of the World Tree ($5A) clears flag
    # $BF and restarts into that text. RPGOne put the FF before the text ($2B:AA66) instead of after it, both
    # flavors: a normal item gave no message and stayed in the coffin (Mesen), and the Leaf restarted into the
    # unterminated text forever. Their text also named $0C93 and $0C8F, which the discard code never sets (the
    # give code does), instead of the lead (F5 95) and the coffin's owner (F4, $AE), as JP. JP's order is
    # restored: the text moves up one byte over the stray FF, the FF follows 'EE 00 00', the Leaf branch at
    # $AA9F stays where the E9 points and its D8 03 now restarts at $AA66. Names: F5 93 -> F5 95, and
    # 'F5 8F s' -> 'F4 ' s' (same length; this also adds the line's missing apostrophe).
    text = (bytes.fromhex('e5f593') + enct(' took the ') + bytes.fromhex('fefdf58d') + enct(' from ')
            + bytes.fromhex('fdf58f42') + enct(' coffin') + bytes.fromhex('fefd') + enct('and discarded it.'))
    new_text = text.replace(bytes.fromhex('e5f593'), bytes.fromhex('e5f595')).replace(bytes.fromhex('fdf58f42'), bytes.fromhex('fdf45542'))
    old = bytes.fromhex('e9e8005a9faa') + b'\xff' + text + bytes.fromhex('ee0000') + bytes.fromhex('efbf00') + bytes.fromhex('d8030167aa')
    new = bytes.fromhex('e9e8005a9faa') + new_text + bytes.fromhex('ee0000') + b'\xff' + bytes.fromhex('efbf00') + bytes.fromhex('d8030166aa')
    assert len(old) == len(new)
    assert new.index(bytes.fromhex('efbf00')) == 0xAA9F - 0xAA60, 'Leaf branch must stay at $AA9F'
    put(rom, 0x2B, 0xAA60, old, new, 'coffin discard: JP order and names')


def fix_coffin_give_both_dead(rom, fl):
    # DQ2 Item menu, Give from a dead member to a dead member (flags 8 and 9; message $2B:AB05 both flavors, JP
    # $2B:A534): JP "<lead> takes <item> from <giver>'s coffin and puts it into <receiver>'s coffin". The give
    # code sets $0C93 = giver ($00:BBCA) and $0C8F = receiver ($00:BC6E). Seen in Mesen with the hero and Linda
    # dead, AAA giving to Linda: DQ "Linda took the Leather Armor from AAA's coffin, and placed it into Linda's
    # coffin." (the dead receiver acts); DW "Rolando took the Leather Armor from Linda's coffin, and placed it
    # into AAAs coffin." (giver and receiver swapped, apostrophe missing).
    if fl == 'dq':
        put(rom, 0x2B, 0xAB05, 'e5f58f00' + enct('took').hex(), 'e5f59500' + enct('took').hex(), 'give both dead: actor = lead')
    else:
        put(rom, 0x2B, 0xAB1C, 'fdf58f5542', 'fdf5935542', 'give both dead: from the giver')
        reword(rom, 0x2B, 0xAB3E, 'f59342', 'f58f5542', 0xD730, 'give both dead: into the receiver')


# Possessives written without the apostrophe after a name code ("<name>s coffin"). (flavor, address of the
# 's', stub); each 's' and the two bytes after it become "'s" + the same two bytes through an 8-byte-spaced
# stub. The coffin lines at $2B:AA7F (both) and DW $2B:AB3E get theirs from the two coffin fixes above.
POSSESSIVE = {
    'dq': [('14:BC3E', 0xFB38), ('2B:89E9', 0xD740), ('2B:8A12', 0xD748), ('2B:9294', 0xD750), ('2B:92E9', 0xD758),
           ('2B:94DD', 0xD760), ('2B:963C', 0xD768), ('2B:9A4D', 0xD770), ('2B:B658', 0xD778), ('2B:B689', 0xD780),
           ('2B:B6C8', 0xD788), ('2B:C8AD', 0xD790), ('2B:CA14', 0xD798), ('33:A7A7', 0xE028)],
    'dw': [('14:BC69', 0xFB38), ('2B:89E9', 0xD740), ('2B:8A12', 0xD748), ('2B:9293', 0xD750), ('2B:92E8', 0xD758),
           ('2B:94DC', 0xD760), ('2B:963F', 0xD768), ('2B:B65C', 0xD778), ('2B:B68D', 0xD780), ('2B:B6CC', 0xD788),
           ('2B:C8B5', 0xD790), ('2B:CA1C', 0xD798), ('33:A7A7', 0xE028)],
}
NAME_CODE_LEN = {0xF4: 1, 0xF5: 2, 0xF1: 3}


def fix_typo_possessive(rom, fl):
    for where, stub in POSSESSIVE[fl]:
        b, a = (int(x, 16) for x in where.split(':'))
        o = off(b, a)
        assert any(rom[o - n] == c for c, n in NAME_CODE_LEN.items()), 'possessive %s: no name code before the s' % where
        nxt = bytes(rom[o + 1:o + 3])
        assert all(c < 0xD8 or c in (0xFE, 0xFD, 0xF0) for c in nxt), where
        reword(rom, b, a, bytes([0x42]) + nxt, bytes([0x55, 0x42]) + nxt, stub, 'possessive %s' % where)


# ---------------------------------------------------------------- v0.4 stage 1: companion names
# New game ($09:AFBF, JP code kept by RPGOne) copies the hero name to $0156 and sums its bytes into $02,
# then calls $30:8E00 (prince) with X = ((sum >> 3) & 7) * 4 and $30:8F00 (princess) with X = (sum & 7) * 4.
# JP used those indices on two 8-name tables; RPGOne's routines ignore X and pick by the first letter.
# This replaces RPGOne's two routines inside RPGOne's own block $30:8E00-$8FFF:
#   DQ: the JP rule (the X from $09), English transliterations of the JP names.
#   DW: NES Dragon Warrior II's rule and names (PRG $1ACEB/$1AD39): the hero name in NES codes, padded
#       with $60 to 8, added with one CLC in the order 3,7,2,6,1,5,0,4; prince = sum & 7,
#       princess = (sum >> 3) & 7.
#   Both: RPGOne's eggs first (prefix RPGONE -> Square / Enix, prefix Zeke -> Anthony / Alyssa).
# Only new game reaches this code; the hidden rename ($09:B0AC / $09:B0E7) does not.

def asm(src, labels=None):
    """Two-pass assembler for the few 65816 forms used below (8-bit A unless an immediate has
    4 hex digits, 16-bit X/Y; DB = $30). Returns ([(org, bytes)], labels)."""
    imp = {'PHB': 0x8B, 'PHX': 0xDA, 'PHY': 0x5A, 'PHK': 0x4B, 'PLB': 0xAB, 'PLX': 0xFA, 'PLY': 0x7A,
           'PHA': 0x48, 'PLA': 0x68, 'RTL': 0x6B, 'RTS': 0x60, 'INX': 0xE8, 'INY': 0xC8, 'CLC': 0x18,
           'SEC': 0x38, 'TAX': 0xAA, 'XBA': 0xEB, 'ASL': 0x0A, 'LSR': 0x4A, 'DEC': 0x3A}
    imm = {'REP': 0xC2, 'SEP': 0xE2, 'LDA': 0xA9, 'LDX': 0xA2, 'LDY': 0xA0, 'CMP': 0xC9, 'CPX': 0xE0,
           'CPY': 0xC0, 'ADC': 0x69, 'SBC': 0xE9, 'AND': 0x29}
    mem = {('JSR', ''): 0x20, ('JMP', ''): 0x4C, ('LDA', 'X'): 0xBD, ('LDA', 'Y'): 0xB9, ('LDY', 'X'): 0xBC,
           ('CMP', 'X'): 0xDD, ('CMP', 'Y'): 0xD9, ('STA', 'LX'): 0x9F, ('LDA', 'S'): 0xA3, ('ADC', 'S'): 0x63}
    rel = {'BEQ': 0xF0, 'BNE': 0xD0, 'BCC': 0x90, 'BCS': 0xB0, 'BRA': 0x80}
    lab = dict(labels or {})

    def val(x, final):
        if x.startswith('$'):
            return int(x[1:], 16)
        x, _, add = x.partition('+')
        return (lab[x] if final else lab.get(x, 0x8000)) + int(add or 0)

    def one_pass(final):
        segs, pc, out = [], None, None
        for raw in src.splitlines():
            line = raw.split(';')[0].strip()
            if not line:
                continue
            if line.startswith('ORG '):
                if out is not None:
                    segs.append((org, bytes(out)))
                org = pc = int(line[5:], 16)
                out = bytearray()
                continue
            if line.endswith(':'):
                name = line[:-1]
                assert not final or lab[name] == pc, name
                lab[name] = pc
                continue
            op, _, arg = line.partition(' ')
            arg = arg.strip()
            if op == 'DB':
                b = bytes(int(x, 16) for x in arg.split())
            elif op == 'DW':
                b = b''.join(val(x.strip(), final).to_bytes(2, 'little') for x in arg.split(','))
            elif arg in ('', 'A'):
                b = bytes([imp[op]])
            elif arg.startswith('#'):
                v = arg[1:]
                n = (len(v) - 1) // 2 if v.startswith('$') else 2
                b = bytes([imm[op]]) + val(v, final).to_bytes(n, 'little')
            elif op in rel:
                d = val(arg, final) - (pc + 2)
                assert not final or -128 <= d <= 127, 'branch out of range: ' + line
                b = bytes([rel[op], d & 0xFF])
            else:
                base, _, idx = arg.partition(',')
                if base.startswith('$') and len(base) == 7:
                    b = bytes([mem[(op, 'L' + idx)]]) + int(base[1:], 16).to_bytes(3, 'little')
                elif idx == 'S':
                    b = bytes([mem[(op, 'S')], int(base[1:], 16)])
                else:
                    b = bytes([mem[(op, idx)]]) + val(base, final).to_bytes(2, 'little')
            out += b
            pc += len(b)
        segs.append((org, bytes(out)))
        return segs

    one_pass(False)
    return one_pass(True), lab


# DQ: transliterations of the JP lists at $09:B06C / $09:B08C, in JP order (index 0-7).
COMPANIONS = {
    'dq': (['Rand', 'Kain', 'Arthur', 'Conan', 'Cookie', 'Tonnura', 'Sukesan', 'Paulo'],
           ['Airin', 'Maria', 'Nana', 'Akina', 'Purin', 'Maiko', 'Linda', 'Samantha']),
    # DW: NES Dragon Warrior II, PRG $1AD39 (prince) and $1AD79 (princess), 8-byte entries, in ROM order.
    'dw': (['Bran', 'Glynn', 'Talint', 'Numor', 'Lars', 'Orfeo', 'Artho', 'Esgar'],
           ['Varia', 'Elani', 'Ollisa', 'Roz', 'Kailin', 'Peta', 'Illyth', 'Gwen']),
}
COMPANION_EGGS = [('RPGONE', 'prefix', 'Square', 'Enix'), ('Zeke', 'prefix', 'Anthony', 'Alyssa')]   # RPGOne v2.0
RADMAGE_EGG = [('Rad', 'exact', 'Edric', 'Gwen'), ('RadMage', 'exact', 'Edric', 'Gwen')]
# English name-entry punctuation -> NES name-entry code (both games typed in Mesen): . , ; ' ... ! ? arrow
NES_PUNCT = [(0x50, 0x6B), (0x51, 0x69), (0x53, 0x70), (0x55, 0x67), (0x56, 0x75), (0x58, 0x6F), (0x59, 0x6E),
             (0x54, 0x63)]
NAMING_BLOCK_CRC = 0xC8772B29        # RPGOne's $30:8E00-$8FFF (both flavors, v2.0 = v0.3.0)
NAME_POOL = (0x8468, 0x8520)         # zero in RPGOne, right after its name list $30:8400-$8467

NAMING_SRC = '''
ORG $8E00
prince:
  PHB
  PHX
  PHY
  PHK
  PLB
  LDA #$00
  JMP common
common:
  PHA                 ; 1,S = 0 prince / 1 princess; 4,S = X from $09 (JP index * 4)
  JSR egg
  BCC normal
  DEC A               ; egg id 1.. -> pointer (id - 1) * 4 + which * 2
  ASL A
  ASL A
  CLC
  ADC $01,S
  ADC $01,S
  REP #$20
  AND #$00FF
  TAX
  SEP #$20
  LDY eggptr,X
  BRA copy
normal:
{normal}
pick:
  LDA $01,S
  BNE pick2
  LDY princetab,X
  BRA copy
pick2:
  LDY princesstab,X
copy:
  LDA $01,S
  BNE copy2
  LDX #$015F
  BRA copyl
copy2:
  LDX #$0168
copyl:
  LDA $0000,Y
  STA $7E0000,X
  CMP #$FF
  BEQ done
  INX
  INY
  BRA copyl
done:
  PLA
  PLY
  PLX
  PLB
  RTL
egg:                  ; C set and A = egg id when $0156 matches a record: pattern, FE (prefix) or FF (exact), id
  LDX #eggtab
egg_rec:
  LDA $0000,X
  BEQ egg_none
  LDY #$0000
egg_cmp:
  LDA $0000,X
  CMP #$FE
  BEQ egg_hit
  CMP $0156,Y
  BNE egg_miss
  CMP #$FF
  BEQ egg_hit
  INX
  INY
  BRA egg_cmp
egg_miss:
  LDA $0000,X
  INX
  CMP #$FE
  BEQ egg_next
  CMP #$FF
  BNE egg_miss
egg_next:
  INX
  BRA egg_rec
egg_hit:
  LDA $0001,X
  SEC
  RTS
egg_none:
  CLC
  RTS
ORG $8F00
princess:
  PHB
  PHX
  PHY
  PHK
  PLB
  LDA #$01
  JMP common
{extra}
princetab:
  DW {princetab}
princesstab:
  DW {princesstab}
eggptr:
  DW {eggptr}
eggptr_free:
  DB 00 00 00 00
eggtab:
  DB {eggtab}
eggtab_end:
  DB 00
'''
NAMING_NORMAL = {
    'dq': '''
  REP #$20
  LDA $04,S           ; JP: X = index * 4 -> table offset index * 2
  LSR A
  TAX
  SEP #$20
''',
    'dw': '''
  JSR nessum
  XBA
  LDA $01,S
  BNE dw_q
  XBA
  AND #$07            ; NES: prince = sum & 7
  BRA dw_i
dw_q:
  XBA
  LSR A               ; NES: princess = (sum >> 3) & 7
  LSR A
  LSR A
  AND #$07
dw_i:
  REP #$20
  AND #$00FF
  ASL A
  TAX
  SEP #$20
'''}
NAMING_EXTRA = {
    'dq': '',
    'dw': '''
nessum:               ; A = the NES sum of the hero name at $0156 (NES codes, $60 after the end)
  LDY #$0000
  LDX #$0000
ns_pos:
  CPY #$0000
  BNE ns_pad
  LDA $0156,X
  CMP #$FF
  BNE ns_map
  INY
ns_pad:
  LDA #$60
  BRA ns_push
ns_map:
  JSR nesmap
ns_push:
  PHA
  INX
  CPX #$0008
  BNE ns_pos
  LDA #$00            ; position p is at (8 - p),S; NES order 3,7,2,6,1,5,0,4, one CLC
  CLC
  ADC $05,S
  ADC $01,S
  ADC $06,S
  ADC $02,S
  ADC $07,S
  ADC $03,S
  ADC $08,S
  ADC $04,S
  PLX
  PLX
  PLX
  PLX
  RTS
nesmap:               ; English name code -> NES name code
  CMP #$10
  BCC nm_punct
  CMP #$2A
  BCS nm_lower
  ADC #$14            ; A-Z (carry clear)
  RTS
nm_lower:
  CMP #$30
  BCC nm_punct
  CMP #$4A
  BCS nm_punct
  SBC #$25            ; a-z: carry clear, so this subtracts $26
  RTS
nm_punct:
  PHX
  LDX #$0000
nm_loop:
  CMP punct,X
  BEQ nm_found
  INX
  INX
  CPX #$0010
  BNE nm_loop
  PLX                 ; no NES equivalent (digits, space, other marks): keep the code
  RTS
nm_found:
  LDA punct+1,X
  PLX
  RTS
punct:
  DB {punct}
'''}


def companion_pool(rom, fl):
    """Addresses of every name string the naming code needs: RPGOne's list is reused where it has the
    name; the others go into the zero pool after it. Returns ({name: addr}, [(addr, bytes)] to write)."""
    have, pool = {}, []
    a = 0x8400
    while a < 0x8468:                            # RPGOne's list: FF-terminated names
        e = rom.index(b'\xff', off(0x30, a))
        have[bytes(rom[off(0x30, a):e])] = a
        a += e - off(0x30, a) + 1
    prince, princess = COMPANIONS[fl]
    names = prince + princess + [n for _, _, p, q in COMPANION_EGGS for n in (p, q)]
    addr, nxt = {}, NAME_POOL[0]
    for n in names:
        b = enc(n)
        if n in addr:
            continue
        if b in have:
            addr[n] = have[b]
        else:
            addr[n] = nxt
            pool.append((nxt, b + b'\xff'))
            nxt += len(b) + 1
    assert nxt <= NAME_POOL[1], 'name pool full'
    return addr, pool


def naming_layout(rom, fl):
    addr, pool = companion_pool(rom, fl)
    prince, princess = COMPANIONS[fl]
    eggtab = []
    for i, (pat, kind, _, _) in enumerate(COMPANION_EGGS):
        eggtab += list(enc(pat)) + [0xFE if kind == 'prefix' else 0xFF, i + 1]
    src = NAMING_SRC.format(
        normal=NAMING_NORMAL[fl], extra=NAMING_EXTRA[fl].replace('{punct}', ' '.join('%02X %02X' % pq for pq in NES_PUNCT)),
        princetab=', '.join('$%04X' % addr[n] for n in prince),
        princesstab=', '.join('$%04X' % addr[n] for n in princess),
        eggptr=', '.join('$%04X' % addr[n] for _, _, p, q in COMPANION_EGGS for n in (p, q)),
        eggtab=' '.join('%02X' % x for x in eggtab))
    segs, lab = asm(src)
    return segs, lab, pool, addr


def fix_companion_names(rom, fl):
    segs, lab, pool, _ = naming_layout(rom, fl)
    o = off(0x30, 0x8E00)
    have = bytes(rom[o:o + 0x200])
    if zlib.crc32(have) != NAMING_BLOCK_CRC:
        raise SystemExit('companion_names: $30:8E00-$8FFF CRC32 %08X, want %08X' % (zlib.crc32(have), NAMING_BLOCK_CRC))
    block = bytearray(0x200)
    for org, b in segs:
        assert 0x8E00 <= org and org + len(b) <= (0x8F00 if org < 0x8F00 else 0x9000), 'naming code overflows its page'
        block[org - 0x8E00:org - 0x8E00 + len(b)] = b
    rom[o:o + 0x200] = block
    for a, b in pool:
        put(rom, 0x30, a, bytes(len(b)), b, 'companion_names: name %04X' % a)


def fix_companion_names_radmage(rom, fl):
    """Hero named exactly Rad or RadMage: Edric / Gwen. Needs companion_names (adds to its egg table)."""
    segs, lab, pool, addr = naming_layout(rom, fl)
    o = off(0x30, 0x8E00)
    if bytes(rom[o:o + len(segs[0][1])]) != segs[0][1]:
        raise SystemExit('companion_names_radmage needs companion_names')
    used = max(a + len(b) for a, b in pool) if pool else NAME_POOL[0]
    extra = []
    for n in ('Edric', 'Gwen'):
        if n not in addr:
            b = enc(n) + b'\xff'
            put(rom, 0x30, used, bytes(len(b)), b, 'companion_names_radmage: name %s' % n)
            addr[n] = used
            used += len(b)
            extra.append(n)
    assert used <= NAME_POOL[1]
    p, q = RADMAGE_EGG[0][2], RADMAGE_EGG[0][3]
    put(rom, 0x30, lab['eggptr_free'], bytes(4), addr[p].to_bytes(2, 'little') + addr[q].to_bytes(2, 'little'),
        'companion_names_radmage: egg pointers')
    rec = b''.join(enc(pat) + bytes([0xFF, len(COMPANION_EGGS) + 1]) for pat, kind, _, _ in RADMAGE_EGG
                   if kind == 'exact') + b'\x00'
    put(rom, 0x30, lab['eggtab_end'], bytes(len(rec)), rec, 'companion_names_radmage: egg records')
    assert lab['eggtab_end'] + len(rec) <= 0x9000


# ---------------------------------------------------------------- v0.4 stage 2: item names
# Item names are FF-terminated strings in bank $01 ($2A = menu row break). They are reached through table A
# $09:E927 (field messages), table B $09:E9FB (menus, Status/Equip lists, battle messages) and the menu-entry
# templates in bank $09 that call the string directly (F7 lo hi len). A name that moves must be re-pointed in all
# of them; nothing else refers to these strings (whole-ROM scan, docs/V04_STAGE2_REPORT.md).
ITEM_TABLE_A, ITEM_TABLE_B = 0xE927, 0xE9FB


def item_ptr(rom, table, item):
    o = off(0x09, table) + 2 * item
    return rom[o] | rom[o + 1] << 8


def item_text(rom, ptr):
    o = off(0x01, ptr)
    return bytes(rom[o:rom.index(b'\xff', o)])


def item_refs(rom, ptr):
    """Bank-$09 addresses of every 2-byte reference to the bank-$01 string at ptr: table entries and F7 calls."""
    refs = [t + 2 * i for t in (ITEM_TABLE_A, ITEM_TABLE_B) for i in range(0x6A) if item_ptr(rom, t, i) == ptr]
    b = rom[off(0x09, 0x8000):off(0x09, 0x8000) + 0x8000]
    pat = bytes([0xF7, ptr & 0xFF, ptr >> 8])
    i = b.find(pat)
    while i >= 0:
        refs.append(0x8000 + i + 1)
        i = b.find(pat, i + 1)
    return sorted(refs)


def ench(s):
    """Item-name text: enct() plus '|' = $2A, RPGOne's menu row break."""
    return b''.join(b'\x2a' if c == '|' else enct(c) for c in s)


def move_item_name(rom, item, old, new, at, nrefs, what):
    """Write new at $01:at and point every reference to item's current string there (old string left, unreferenced)."""
    p = item_ptr(rom, ITEM_TABLE_B, item)
    have = item_text(rom, p)
    if have not in (ench(old), ench(old) + b'\x2a'):            # trailing break: item_name_trailing_break skipped
        raise SystemExit('%s: item $%02X reads %s' % (what, item, have.hex()))
    refs = item_refs(rom, p)
    if len(refs) not in nrefs:
        raise SystemExit('%s: %d references to $01:%04X, expected %s' % (what, len(refs), p, nrefs))
    put(rom, 0x01, at, bytes(len(ench(new)) + 1), ench(new) + b'\xff', what + ' (new string)')
    for r in refs:
        put(rom, 0x09, r, p.to_bytes(2, 'little'), at.to_bytes(2, 'little'), what + ' (reference $09:%04X)' % r)


def fix_item_message_name_19(rom, fl):
    # Item $19 (JP stone tablet): table A, used by field messages, points at item $1B's "Silver Harp" in both
    # flavors. JP's table A has its own entry for $19 ($01:DD00) and RPGOne made A = B for every other item.
    harp = {'dq': 0xD9AA, 'dw': 0xD9E0}[fl]
    assert item_ptr(rom, ITEM_TABLE_A, 0x1B) == harp and item_text(rom, harp) == ench('Silver|Harp')
    put(rom, 0x09, ITEM_TABLE_A + 2 * 0x19, harp.to_bytes(2, 'little'),
        item_ptr(rom, ITEM_TABLE_B, 0x19).to_bytes(2, 'little'), 'item_message_name_19')


def fix_dq_chain_sickle(rom, fl):
    # DQ $29 kusarigama: "Chain Whip" -> "Chain Sickle" (DW and JP: chain sickle). 2 bytes longer: moved.
    if fl == 'dq':
        move_item_name(rom, 0x29, 'Chain|Whip', 'Chain|Sickle', 0xFFC0, {6}, 'dq_chain_sickle')


def fix_dq_hades_shield(rom, fl):
    # DQ $43: "Hade's Shield" -> "Hades' Shield" (same length, same one-row layout).
    if fl == 'dq':
        p = item_ptr(rom, ITEM_TABLE_B, 0x43)
        assert p == 0xD776 and item_text(rom, p) in (ench("Hade's Shield"), ench("Hade's Shield|"))
        put(rom, 0x01, 0xD77A, '5542', '4255', 'dq_hades_shield')


def fix_dq_hades_shield_rows(rom, fl):
    # DQ $43 on two menu rows ("Hades'" / "Shield", like DW's "Evil" / "Shield"). As one 13-tile row it fills the
    # right column of the battle item list, and the left entry then loses its second row (RPGOne v2.0 to v0.3.0,
    # Mesen). In messages $2A is a 4-px blank like the space it replaces.
    if fl == 'dq':
        p = item_ptr(rom, ITEM_TABLE_B, 0x43)
        assert p == 0xD776 and item_text(rom, p)[:7] in (ench("Hade's "), ench("Hades' "))
        put(rom, 0x01, 0xD77C, '00', '2a', 'dq_hades_shield_rows')


def fix_dq_stone_tablet(rom, fl):
    # DQ $19 sekiban: "Lithograph" -> "Stone Tablet", one menu row of 12 tiles, like "Lithograph".
    # Moved (13 bytes, the old slot has 12). References: table B, 2 templates, and table A if
    # item_message_name_19 ran.
    if fl == 'dq':
        move_item_name(rom, 0x19, 'Lithograph', 'Stone Tablet', 0xFFD0, {3, 4}, 'dq_stone_tablet')


FIXES = [('title_idle', fix_title_idle), ('names', fix_names), ('leaf', fix_leaf),
         ('dragonlord', fix_dragonlord), ('dq1_level30_save', fix_dq1_level30_save),
         ('dq1_princess_love', fix_dq1_princess_love), ('dq1_king_victory', fix_dq1_king_victory),
         ('status_view', fix_status_view), ('king_prince', fix_king_prince),
         ('dq1_princess_farewell', fix_dq1_princess_farewell),
         # v0.3 stage 1
         ('orb_after_hargon', fix_orb_after_hargon), ('nun_after_hargon', fix_nun_after_hargon),
         ('flute_crests', fix_flute_crests), ('king_prince_party3', fix_king_prince_party3),
         ('chance', fix_chance), ('chance_confused_attack', fix_chance_confused_attack),
         ('dq1_transform', fix_dq1_transform),
         # v0.3 stage 2
         ('item_menu_name', fix_item_menu_name), ('beran_inn_price', fix_beran_inn_price),
         ('vault_balance', fix_vault_balance), ('vault_balance_layout', fix_vault_balance_layout),
         ('after_hargon_villagers', fix_after_hargon_villagers),
         ('garbage_text', fix_garbage_text), ('curse_laugh_line', fix_curse_laugh_line),
         ('poison_cure_message', fix_poison_cure_message),
         # v0.3 stage 3
         ('field_spell_wait', fix_field_spell_wait), ('exp_to_next_24bit', fix_exp_to_next_24bit),
         ('king_princess_reply', fix_king_princess_reply), ('cannock_king_lead', fix_cannock_king_lead),
         ('lead_member_names', fix_lead_member_names)]
FIXES += [(fid, name_fix(fid)) for fid in dict.fromkeys(f for f, *_ in NAMES)]
FIXES += [('dq1_died_in_battle', fix_dq1_died_in_battle), ('laurasia_king_wait', fix_laurasia_king_wait),
          ('beer_thief_wait', fix_beer_thief_wait), ('item_name_trailing_break', fix_item_name_trailing_break)]
# v0.3 stage 4
FIXES += [('field_heal_line_break', fix_field_heal_line_break), ('field_action_lead', fix_field_action_lead)]
FIXES += [(fid, table_fix(TYPOS, fid)) for fid in dict.fromkeys(f for f, *_ in TYPOS)]
FIXES += [('dw_evil_shield_space', fix_dw_evil_shield_space), ('stray_quote_codes', fix_stray_quote_codes)]
FIXES += [('coffin_discard_message', fix_coffin_discard_message), ('coffin_give_both_dead', fix_coffin_give_both_dead),
          ('typo_possessive', fix_typo_possessive)]
V03_STAGE1 = ['orb_after_hargon', 'nun_after_hargon', 'flute_crests', 'king_prince_party3',
              'chance', 'chance_confused_attack', 'dq1_transform']
V03_STAGE2 = ['item_menu_name', 'beran_inn_price', 'vault_balance', 'vault_balance_layout',
              'after_hargon_villagers', 'garbage_text', 'curse_laugh_line', 'poison_cure_message']
_S4 = [fid for fid, _ in FIXES].index('field_heal_line_break')
V03_STAGE3 = [fid for fid, _ in FIXES[FIXES.index(('field_spell_wait', fix_field_spell_wait)):_S4]]
V03_STAGE4 = [fid for fid, _ in FIXES[_S4:]]
V03 = V03_STAGE1 + V03_STAGE2 + V03_STAGE3 + V03_STAGE4
# v0.4 stage 1
FIXES += [('companion_names', fix_companion_names), ('companion_names_radmage', fix_companion_names_radmage)]
V04_STAGE1 = ['companion_names', 'companion_names_radmage']
# v0.4 stage 2
FIXES += [('item_message_name_19', fix_item_message_name_19), ('dq_chain_sickle', fix_dq_chain_sickle),
          ('dq_hades_shield', fix_dq_hades_shield), ('dq_hades_shield_rows', fix_dq_hades_shield_rows),
          ('dq_stone_tablet', fix_dq_stone_tablet)]
V04_STAGE2 = ['item_message_name_19', 'dq_chain_sickle', 'dq_hades_shield', 'dq_hades_shield_rows', 'dq_stone_tablet']
V04 = V04_STAGE1 + V04_STAGE2


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
    ap.add_argument('--out', default=os.path.join(ROOT, 'work', 'out'),
                    help='folder for the built ROMs and patches (default work/out)')
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
        outdir = os.path.join(a.out, fl)
        os.makedirs(outdir, exist_ok=True)
        tag = '' if not (only or skip) else '_' + '-'.join(applied)
        if len(tag) > 80:                    # Windows path limit: name the subset by size and checksum
            tag = '_%dfixes_%08x' % (len(applied), zlib.crc32(','.join(applied).encode()))
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
