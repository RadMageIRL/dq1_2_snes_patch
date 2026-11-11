# Changelog

## v0.3.0 (2026-11-10)

Details for each fix are in the README under "Fixed in v0.3".

- Corrections to earlier notes: the v0.1 Dragonlord fix changed an unused copy of his
  speech, so it fixed nothing a player sees (the speech in the game already worked), and
  the v0.2 second-prince fix missed the party of three. Both entries below are corrected.
- Dragon Quest II: no more endless conversations after Hargon (Descendant's Orb, a nun);
  the right villager line after Hargon; the curse-removal man's laugh no longer garbles
  his window; two speeches wait for a button again.
- Dragon Quest II: the second Prince of Cannock no longer appears with a party of three.
- Dragon Quest II: the Echoing Flute finds every crest site; all eight Chance outcomes
  work; field spell results wait like the Japanese game; the Item menu no longer changes
  the princess's name; the poison-cure battle script is fixed.
- Dragon Quest II: discarding an item from a dead member's coffin works again (it did
  nothing, and the Leaf of the World Tree repeated its message forever); giving an item
  between two coffins names the right members.
- Dragon Quest II: right numbers for the Beran inn price (DQ), the vault over 65,535 gold
  and "you need N experience" over 65,535.
- Lines that should name the party's leader do so when the hero is dead (19 dialogue
  lines and the field messages for searching, drawers, pots and the trap chest); the
  King of Cannock's line that printed garbage; the princess's reply to the King.
- Item, character and place names made consistent with each flavor's own item list and
  script; two wrong item names (Dragon's Scale, the lottery prize).
- Dragon Quest I (DQ flavor): the Dragonlord's transformation shows RPGOne's own
  translation instead of a fragment of another speech.
- Text: literal codes such as ",60," removed (28 places), item names without trailing
  gaps, the field heal line fits wide names, spelling fixes, possessive apostrophes after
  names (15 lines in each flavor), "died" (DQ1), stray quote codes removed.

## v0.2 (2026-11-09)

- Dragon Quest II: the second Prince of Cannock no longer appears. After he joined you,
  the King of Midenhall repeated his "the prince came looking for you" speech, which put
  a copy of the prince back in the Leftwyne inn; talking to it replayed his joining
  scene. The King now gives his normal greeting, as in the Japanese game. (Corrected in
  v0.3: this covered a party of two and the prince's illness, not a party of three.)
- Dragon Quest II: the Status submenu reads Status / Equip / View instead of listing
  "Status" twice.
- Dragon Quest I: when you bring the princess back, her farewell ends where the Japanese
  game ends it, instead of running on into a second, reworded farewell and kiss.
- Known issues: the Sea Cave graphics report and the untranslated Dragon Quest I ending
  report were investigated and could not be reproduced (details in the README).

## v0.1 (2026-11-09)

First version. One patch per name flavor (DQ and DW) for the original Japanese ROM,
headerless and headered, containing RPGOne's English translation v2.0, mziab's title
screen fix v1.0, and these fixes:

- Dragon Quest II: the Leaf of the World Tree recovery speech no longer loops. The
  message overflowed the game's 256-byte text window with longer names.
- Dragon Quest II: while the Prince of Cannock is ill, lines about him use his own
  name again instead of the princess's, and the hero's name no longer gains extra
  letters.
- Dragon Quest II: item and spell messages name the right party member while the
  party is swapped.
- Dragon Quest II: a princess named Gloria or Samantha no longer erases the prince's
  name at the start of a new game.
- Dragon Quest I: the Dragonlord's offer no longer loops, both answers work, and the
  "What do you say,51,, boy?" line reads "What do you say...". (Corrected in v0.3: this
  changed an unused copy of his speech; the speech the game shows already worked.)
- Dragon Quest I (DQ flavor): the King offers to save at level 30.
- Dragon Quest I (DQ flavor): no "4" before your name with the Princess's Love.
- Dragon Quest I: the King's "You have finally slain King Dragon" speech is reachable
  again.
- Dragon Quest I: the title screen returns to the attract sequence after about a minute,
  as in the Japanese game, instead of about 18 minutes.
