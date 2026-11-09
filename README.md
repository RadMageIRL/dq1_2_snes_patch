# Dragon Quest I+II (SFC) English, Fixed

One patch for the original Japanese *Dragon Quest I+II* (Super Famicom) that applies
RPGOne's English translation v2.0, mziab's title screen fix, and my fixes for the bugs
players have reported in that translation, including the Leaf of the World Tree
softlock in Dragon Quest II.

---

## Most of this is someone else's work

**RPGOne Translations and EvilTeam Tradução translated these games.** Every line of
English you read is theirs. Their credits, from the v2.0 readme: ChrisRPG (project
leader, hacking, editing), SpSpiff (English script), Arch Demon and Brightman (script
editing), Byuu (ASM programming, credited on romhacking.net as Near), Cynsob and Zeke_D
(the DQST savestate tool), and a long list of testers.

**mziab fixed the broken Dragon Quest I title screen in 2012.** That fix is his. It is
included unchanged, byte for byte, and this patch applies it before anything of mine.

Their wording is not changed, with two exceptions, both listed below: one line in the
Dragonlord's speech that printed stray digits, and one stray digit in the Princess's
Love message. Everything else I changed is code, pointers, or which name a line prints.

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
  lava areas. I have not investigated it yet.
- **The second Prince of Cannock.** A review reports him standing in town while he is
  already in your party. RPGOne's readme calls this partly fixed. Not investigated.
- **Untranslated Dragon Quest I ending text.** The romhacking.net entry says the King's
  ending text is untranslated if you rescue the princess but do not bring her back. I
  traced every branch of the ending against the Japanese script and found none that
  reaches untranslated text, so I could not confirm it.
- **The Dragon Quest II status submenu** lists "Status" twice. Not investigated.
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
| DQ, headerless | 2,097,152 | `854DA5FA` | `b5c44b111f2f03edc45db8b462085169e02854d3` |
| DQ, headered | 2,097,664 | `9801E511` | `0fc108e6d3a6c10d789a8941c97b42695bc4199a` |
| DW, headerless | 2,097,152 | `39590904` | `d941b977fe9d3d0edd8c92b88e6cff25dbadcbee` |
| DW, headered | 2,097,664 | `241549EF` | `bd497b9de5626b922406745970cc090574e4c2d2` |

Patch files (SHA-1):

| File | SHA-1 |
|---|---|
| `dq1-2-fixed-patch-radmageirl-dq.bps` | `fc179d473de5c26f3562b86c1328903b2c21802b` |
| `dq1-2-fixed-patch-radmageirl-dq.ips` | `d91a237bd3e3962c4d6938ba4661e10e266d9778` |
| `dq1-2-fixed-patch-radmageirl-dw.bps` | `ae5f9a9217f7a7e0c99b01478eb5149d42993f0b` |
| `dq1-2-fixed-patch-radmageirl-dw.ips` | `ce496276c40002eb0e7a9be62365639a47bd9e25` |
| `headered/dq1-2-fixed-patch-radmageirl-dq-headered.bps` | `9b3701dbed075d74b18bc9a43fad87f0f7219bd6` |
| `headered/dq1-2-fixed-patch-radmageirl-dq-headered.ips` | `74fd13c0814476135412e850ba272e61efa6c607` |
| `headered/dq1-2-fixed-patch-radmageirl-dw-headered.bps` | `b1bc2ffaad17da42e85f6ff569538532faeff965` |
| `headered/dq1-2-fixed-patch-radmageirl-dw-headered.ips` | `65d8fc15f1bd10c7777c80df5e24533e4ece7038` |

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
