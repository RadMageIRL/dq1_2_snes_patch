# Dragon Quest I+II (SFC) English, Fixed

One patch for the original Japanese *Dragon Quest I+II* (Super Famicom) that applies
RPGOne's English translation v2.0, mziab's title screen fix, and my fixes for the bugs
players have reported in that translation, including the Leaf of the World Tree
softlock in Dragon Quest II.

---

## Most of this is someone else's work

**RPGOne Translations and EvilTeam Traduções translated these games.** Every line of
English you read is theirs. Their full credits, from their v2.0 readme, are listed
under [Credits](#credits) at the end of this page.

**mziab fixed the broken Dragon Quest I title screen in 2012.** That fix is his. It is
included unchanged, byte for byte, and this patch applies it before anything of mine.

Their wording is not changed, with three exceptions, all listed below: one line in the
Dragonlord's speech that printed stray digits, one stray digit in the Princess's Love
message, and one new menu word, "View", in the Dragon Quest II Status menu. Everything
else I changed is code, pointers, control bytes, or which name a line prints.

---

## What this patch fixes

Each fix below says what you see, why it happens, and what I changed. "Both flavors"
means the DQ and DW versions of the translation; a few bugs exist in only one of them.

### Dragon Quest II: the Leaf of the World Tree softlock (both flavors)

**What you see.** After the Prince of Cannock falls ill at the Beran inn, feeding him
the Leaf of the World Tree starts his recovery speech, then the text box loops forever
and the game has to be reset. Reviews tied it to his name being longer than 4 letters.

**Why.** The game builds each message into a 256-byte buffer and draws it with an
8-bit index (`INC $C9` at `$00:B22F` and elsewhere), so anything past byte 255 wraps
back to byte 0. The Japanese text never came close. The English recovery speech names
the prince four times and the hero once before RPGOne's split, which they added to stay
under the limit, but the split itself sits right at the edge. With the hero named "AAA",
"Kain" ends it at byte 245; "Rolando" puts its last two bytes at 256 and 257, the game
reads the jump address from the start of the buffer instead, and it loops. In the DQ
flavor it overflows once four times the prince's name plus the hero's name reaches 30
letters: Rolando or Anthony with almost any hero name, Arthur or Square with a hero
name of 6 letters or more. Kain and the 5-letter names never reach it on their own,
but in v2.0 the swap bug described below can lengthen the hero's printed name during
the illness, which pushes more combinations over.

**What I changed.** I moved RPGOne's split earlier in the same message, to the page
break after "has recovered!", and shifted the text between the old and new split by
five bytes. Nothing outside the message moves. With 8-letter names for everyone, the
two parts now come to at most 168 and 149 bytes.

### Dragon Quest I: the Dragonlord's offer loops (both flavors)

**What you see.** Talking to the Dragonlord, his speech repeats from the start after
"Will you be my ally?" ("I am the King of Kings..." again), and one line reads
"What do you say,51,, boy?". This is the "nonsensical remark taken from the King's
dialogue" in one of the reviews.

**Why.** The same 256-byte limit. This speech is 259 bytes even with an empty hero
name, so the Yes/No command at its end crosses byte 255 and reads its targets from the
wrong place. The ",51,," is two digit characters (`$06 $02`) in the line itself.

**What I changed.** I rewrote the message in place: the same text, a split after the
second page, and "What do you say..." for the garbled line, which is the wording
RPGOne used in their other copy of this speech elsewhere in the ROM. The Yes/No
targets do not move. Both answers now work.

### Dragon Quest II: names swapped while the prince is sick (both flavors)

**What you see.** While the prince is ill, people talk about "Prince Linda", his
father says the princess has been cursed, and the hero's name can grow extra letters
on the end. Item messages can name the wrong party member.

**Why.** When the prince falls ill the game swaps his party slot with the princess's,
including their names. RPGOne widened names from 4 letters to 8 and moved them, but
three things were left behind:

1. The swap routine (`$1B:A521`) still swaps 5 bytes at the old Japanese addresses
   `$0176` and `$017B`. In the new layout those bytes are the end of the hero's name
   and the start of a copy of the prince's, so a hero named `ABCDEFGH` turns into
   `ABCDEolandFG` during the illness.
2. The Japanese script names the prince by who he is (a fixed copy at `$0189` that
   never swaps). About 30 of those lines were changed to his party slot (`$015F`),
   which holds the princess's name while he is ill. The DW flavor kept the right one
   in the sickbed scenes; the DQ flavor did not.
3. Two name lookups, the lead party member's name (`$09:994A`) and an item or spell
   target's name (`$00:BCAF`), mix slot names with fixed names, so they name the wrong
   person while the slots are swapped.

**What I changed.** I removed the 5-byte swap, since nothing needs those copies once
the readers use the 9-byte slot names. I pointed both lookups at the slot names, the
way the Japanese ones work. I changed the lines that mean the prince himself back to
`$0189`, as the Japanese script has them: 34 lines in the DQ flavor, 27 in DW. I left
the lines that really are about a party slot alone: battle messages, and the level-up
advice that shows that slot's experience.

### Dragon Quest II: the prince's name lost at a new game (both flavors)

**What you see.** With some hero names the princess is named Gloria or Samantha, and
then the prince's name prints as "ha" or as nothing in the Leaf scene, item messages,
and anywhere else that names him directly.

**Why.** RPGOne put a 9-byte copy of the princess's name at `$0183`, six bytes before
the prince's fixed name at `$0189`. A princess name of six letters or more runs past
it and overwrites the start of his name.

**What I changed.** That copy is no longer written; nothing reads it once the slot-2
text uses the princess's slot name. A new game with "Samantha" now keeps "Conan" intact.
Saves made with v2.0 keep whatever was stored; renaming the prince from the load
screen rewrites it.

### Dragon Quest II: a second Prince of Cannock (both flavors)

**What you see.** After the prince joins you at the Leftwyne inn, he can be standing in
the inn again while he is in your party, and talking to him plays his joining scene a
second time. RPGOne's readme calls this the "clone prince", partly fixed in v2.0.

**Why.** The King of Midenhall picks what to say with a list of checks. In the Japanese
script a party of two (the prince has joined) goes straight to "You've returned safely"
(`$14:802B`). RPGOne's pointers for that case, and for the one used while the prince is
ill, land five bytes early (`$14:8004`, `$14:8024`), on the check before it. So once
Cannock has told you that the prince left for Midenhall, the King repeats "A short time
ago, the Prince of Cannock came looking for you" and sets the flag that puts the prince
in the Leftwyne inn.

**What I changed.** Pointed both at the greeting, as the Japanese script does. Visiting
the King alone after Cannock still gives you that speech, which is how the prince gets
to Leftwyne in the first place.

### Dragon Quest II: "Status" twice in the Status menu (both flavors)

**What you see.** The Status submenu lists Status, Equip, Status.

**Why.** RPGOne's line list for that window (`$31:8380`) points the third row at the
window's own title line. The Japanese option means "view strength".

**What I changed.** Added a line " View" in free space at `$31:FF00`, the same width as
the other rows, and pointed the third row at it.

### Dragon Quest I: no save at level 30 (DQ flavor)

**What you see.** At the maximum level the King says you are strong enough to defeat
the Dragonlord and never asks to record your journey.

**Why.** In the Japanese script that line ends with a wait and runs straight into the
save question. In the DQ flavor it ends the message instead (`$01:B8B1`). The DW
flavor has it right.

**What I changed.** That one byte, so it waits and continues into the save question.

### Dragon Quest I: a "4" before your name with the Princess's Love (DQ flavor)

**What you see.** "I hope that you are safe, 4Name."

**Why.** A stray `$05`, the digit 4, before the name in that line (`$01:8749`).

**What I changed.** Removed it.

### Dragon Quest I: the King's victory speech is skipped (both flavors)

**What you see.** Nothing, which is the problem: "You have finally slain King Dragon,
and returned peace to the world!" is translated in the ROM but never shown.

**Why.** The branch that leads to it (flag `$3B`, `$01:BD10`) points to the level and
save talk that follows the speech instead of to the speech. The Japanese branch points
to the speech.

**What I changed.** Pointed it at the speech.

### Dragon Quest I: the princess says goodbye twice (both flavors)

**What you see.** When you carry the princess back to the King, she gives you the
Princess's Love and says goodbye, then says goodbye again in other words ("I will
continue to support you") and the kiss jingle plays a second time.

**Why.** In the Japanese script her farewell ends the message. In RPGOne its last line
ends with a wait instead of an end (`$01:C057` DQ, `$01:C07D` DW), so the game keeps
reading into the next message, a different set of her lines that the script reaches
on its own through another branch.

**What I changed.** That one byte, so the message ends where the Japanese one does. The
other branch still reaches those lines, as in the Japanese game.

### Dragon Quest I: the title screen (both flavors)

**The broken banner.** On real hardware and accurate emulators the DQ1 title shows
the Japanese banner, because RPGOne's routine copies the English tiles to video
memory while the screen is drawing, when the hardware ignores the writes. mziab's fix
splits the copy across four vertical blanks. It is included unchanged.

**The idle timer.** If you leave the DQ1 title alone, the Japanese game returns to
the attract sequence after about a minute. With RPGOne's patch it waits about 18
minutes. Their hook at `$2C:80FC` overwrote four bytes of a five-byte pair of
instructions and left the fifth behind, so the CPU ran it as a different instruction
and the wait loop started from 0 instead of 3,100 frames. I restored the missing
`LDY #$0000` in a small stub and turned the leftover byte into a `NOP`.

---

## Known issues this patch does not fix

- **The Sea Cave in Dragon Quest II.** A review reports distorted map graphics in the
  lava areas. I could not reproduce it. In Mesen 2, battles in all three lava rooms
  leave video memory and palettes exactly as the Japanese game does, and every graphics
  transfer finishes during vertical blank. If you see it, please report your emulator
  and a savestate.
- **Untranslated Dragon Quest I ending text.** The romhacking.net entry says the King's
  ending text is untranslated if you rescue the princess but do not bring her back. I
  could not reproduce it. With the princess never rescued, returned, or still carried at
  the end, the King's ending text is in English and follows the Japanese script.
  RPGOne's v1.1 notes list "Missing pointer for rescuing Princess after the defeat of
  Dragonlord fixed", so the report probably describes an older version.
- **"Rolandos complexion"** in the DQ flavor's Leaf scene is missing its apostrophe.
  That is RPGOne's text and I left it.
- **The Snes9x freeze after battle** that one review fixed by turning off CPU sound
  emulation. I did not reproduce it in Mesen 2.

---

## Which file to use

| You want | Use |
|---|---|
| Japanese-style names (Roto, Laura, Linda) | `dq1-2-fixed-patch-radmageirl-dq.bps` or `.ips` |
| NES-style names (Erdrick, Gwaelin, Cannock) | `dq1-2-fixed-patch-radmageirl-dw.bps` or `.ips` |

The two patches at the top level are for a ROM **without** a copier header. If your
ROM is 1,573,376 bytes it has a 512-byte header: either remove it, or use the matching
patch in `headered/`. The headered patches expect an all-zero header, which is what
romhacking.net lists for RPGOne's patch. The `.ips` works on any header; the `.bps`
checks the whole file, header included, and refuses anything else.

Apply the patch to the **original Japanese ROM**, not to a ROM that already has
RPGOne's patch on it. This patch already contains RPGOne's translation and mziab's fix.

### Hashes

Original Japanese ROM:

| | Size | CRC32 | SHA-1 |
|---|---|---|---|
| headerless | 1,572,864 | `98BB6853` | `1c0c6d78bf2bc29160adf48b17ebf5a5bc46230e` |
| headered (all-zero header) | 1,573,376 | `AA4D4E0A` | `122b599e80a5d1d7999d1936d2cf9f5bf5f257a9` |

Patched ROM:

| | Size | CRC32 | SHA-1 |
|---|---|---|---|
| DQ, headerless | 2,097,152 | `69567056` | `10b4409285b2984095357195c02ed55c541d20d3` |
| DQ, headered | 2,097,664 | `741A30BD` | `804348fba81090ff5f9d44df81cc09f675b996a2` |
| DW, headerless | 2,097,152 | `D1BA0360` | `dfb3ec3d61fcf9bb892314d760bfa82f0c831703` |
| DW, headered | 2,097,664 | `CCF6438B` | `632812467780a4d7dc311fb9517e4eab1082e6c0` |

Patch files (SHA-1):

| File | SHA-1 |
|---|---|
| `dq1-2-fixed-patch-radmageirl-dq.bps` | `45b6b17945aeeab002738acf8a2616be71a93678` |
| `dq1-2-fixed-patch-radmageirl-dq.ips` | `afa78b42540589b2164d77d2e1fb57b3622168b1` |
| `dq1-2-fixed-patch-radmageirl-dw.bps` | `a991b8ed9d7e011709d5ebf6177b65531055c05c` |
| `dq1-2-fixed-patch-radmageirl-dw.ips` | `f0d501b90f1c6ca52db14bfd4aee4a41052d45e0` |
| `headered/dq1-2-fixed-patch-radmageirl-dq-headered.bps` | `90d62d5591f94ad05f62d4b11fbe18f3a66945e6` |
| `headered/dq1-2-fixed-patch-radmageirl-dq-headered.ips` | `196c715eae540126f64a6ebb9f7ee87e860f9c50` |
| `headered/dq1-2-fixed-patch-radmageirl-dw-headered.bps` | `1432cf54c80519b246d895611bda5f2543115f42` |
| `headered/dq1-2-fixed-patch-radmageirl-dw-headered.ips` | `3b416031fcb55e91ba28da2c65a9fab4f8d2e218` |

---

## How I checked it

The title screen, the Leaf scene, the Dragonlord's offer, the name swap, the
new-game name bug and the level 30 save were each reproduced on RPGOne v2.0 with
mziab's fix, then checked again on the fixed build, in Mesen 2 running headless with
scripted input. Names were set to the worst case where it matters: 8-letter hero and
prince names for the Leaf scene and the swap, "Samantha" for the new-game name bug.
The Dragonlord's offer was checked inside Dragon Quest I with both answers, using a
test build that opens with that speech. The Princess's Love digit and the skipped
victory speech were checked against the script bytes and the Japanese script, not
played.

For v0.2, the second prince was reproduced on RPGOne v2.0 and v0.1 from a controlled
save state: story flags set directly, the prince joined at the Leftwyne inn, the King's
script run, then Leftwyne entered again. The Japanese ROM under the same steps shows no
second prince, and neither does the fixed build; the King's speech that sends the
prince to Leftwyne still plays when you are alone. The princess's farewell was run
through a test build that starts that message, on the Japanese ROM, v0.1 and the fixed
build. The Dragon Quest I ending was played from a save state through the ceremony and
the credits on the Japanese ROM and both flavors; the three princess cases were checked
with a test build that starts the King's ending script. The Status menu was checked in
both flavors. For the Sea Cave, battles were
forced in each lava room and video memory, palettes and DMA timing were compared with
the Japanese ROM.

For the 256-byte limit I also scanned the whole script, following every branch. After
the fixes, the only message it finds that crosses byte 255 because of long names is a
second copy of the Dragonlord's speech in bank `$32` that I found no reference to.

---

## Rebuilding

`tools/build.py` rebuilds both flavors from the three original files:

```
python tools/build.py --jp "Dragon Quest 1 & 2 (J).smc" \
    --rpgone "DQV20%s.IPS" --mziab "dq12fix_%s.bps" --release .
```

It takes your own Japanese ROM (headered or not), RPGOne's v2.0 IPS files and mziab's
BPS files, checks the CRC32 at every stage, applies each fix only after confirming the
bytes it replaces, and writes the patches. `tools/chunkscan.py` is the 256-byte scanner
and `tools/txt.py` decodes the script.

---

## Credits

### English translation v2.0 (2003): RPGOne Translations and EvilTeam Traduções

From the credits in their v2.0 readme:

| | |
|---|---|
| Project leader | ChrisRPG |
| English script | SpSpiff |
| Script editing | Arch Demon, Brightman, ChrisRPG |
| ASM programming | Arch Demon, Byuu (credited on romhacking.net as Near), ChrisRPG |
| Graphics | Brightman |
| Savestate tool (DQST) | Cynsob, Zeke_D |
| Testing | Alexander Sirlin, Arch Demon, Brennan Brooks, Brightman, ChrisRPG, Firebrand, Jeremy Gallen, Junts, King Mike, Magnus, Paul Kangas, Squall, Tony, Zeke_D |
| Additional thanks | Anoda, Brightman, Byuu, Dark Force, Emu X Haven, Endwin, Fear Gaia, Gideon Zhi, Pendy, Zeke_D |

Their own credits also appear in the game: on the screen shown at power-on, and in
the Dragon Quest I ending after the original staff.

### Title screen fix v1.0 (2012): mziab

The Dragon Quest I title screen fix, included unchanged.

### Dragon Quest I+II (1993): Enix

The original game. *Dragon Quest* and all related names are trademarks of Square Enix.

### This patch: RadMageIRL

The fixes listed above, the build script and the tools in `tools/`. Testing was done in
[Mesen 2](https://www.mesen.ca/).

---

## License

My own work in this repository is released under the [MIT License](LICENSE): the
build script and tools in `tools/`, the fixes described above, and this documentation.

That license does not cover anyone else's work. The patch files also contain RPGOne
Translations' and EvilTeam Traduções' English translation and mziab's title screen fix,
which remain theirs, and *Dragon Quest I+II* belongs to Square Enix. As RPGOne's readme
asks, do not distribute these patches with a ROM image; please do not distribute
patched ROMs either.
