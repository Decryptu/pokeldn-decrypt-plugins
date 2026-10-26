# Tera Raid battle server

A pokeldn plugin that serves a Scarlet / Violet Tera Raid battle from the host's station
(`bin/sv_host.py --raid-serve clean`), through the plugin API's battle server (1.6). A battle it cannot
reproduce exactly is refused before it starts or stopped when it diverges; the host then hands the
network over and the console fights its own battle, as without the plugin.

## Sources

The battle rules come from public mechanics: the Pokemon Showdown data files and formulas, PokeAPI and
Bulbapedia. The wire format comes from pokeldn's documentation (`docs/sv_raid.md`). The plugin holds no
game code, no game addresses and nothing read out of a game's files. The tests' fixtures are battle
messages exchanged by emulated consoles.

Move data (`raidbattle/data/moves.json`, made by `scripts/gen_moves.py`) and the type chart come from
[Pokemon Showdown](https://github.com/smogon/pokemon-showdown)'s public data, MIT licence, copyright
Guangcong Luo and contributors.

## Checking against the oracle

The tests compare each part with an oracle that stays outside this repository: a translation of the
game's battle server kept in a pokeldn checkout's `scratchpad/battle/oracle` (found through
`POKELDN_ROOT`, or a `pokeldn` folder next to this repository). Without it, those tests are skipped.

    POKELDN_ROOT=~/Documents/GitHub/pokeldn ~/Documents/GitHub/pokeldn/.venv/bin/python -m pytest tests -q

`tools/corpus_check.py start|round|rounds 'CORPUS/*.json'` compares the plugin with a corpus of oracle
battles (pokeldn's `scratchpad/battle/oracle/corpus.py` writes one): equal, refused with the reason, or
different; `rounds` walks every round, raid action rounds and revives included. `tools/battle_check.py
'CORPUS/*.json'` serves each battle again through pokeldn's `RaidBattle` with the corpus console's recorded
moves and compares the server's whole log with the oracle's.

## Milestones

| step | what | state |
|---|---|---|
| 1 | random numbers, the command queue codec, message headers | done: draws equal the oracle's on 300 seeds; 20 recorded queues round-trip |
| 2 | the battle start and one plain damaging move on the boss, byte for byte with a recorded round | done |
| 3 | damage, accuracy, critical hits, the type chart, Tera | built: damage, stat stages, the type chart, STAB, Tera-type boss moves (the 60-power floor after base power modifiers), accuracy draws, critical hits (stage-ignoring, their flags and messages), single-target moves at any position, spread moves (one position hit in a raid), priority moves, immune hits, the move's slot, recoil, drain, the type-boosting items, Overgrow / Blaze / Torrent / Swarm, Huge Power, Rivalry, a player's Adaptability, Focus Sash, turn order by staged Speed, speed ties, no critical-hit draw into Battle Armor or Shell Armor, secondary stat drops, the confusion and flinch secondaries' draws (Inner Focus unless a Mold Breaker attacks); refused: misses, a tie between actors with a handler move, a tie in the winning round, a tie at a turn's end whose residual order the sorts leave open, accuracy or evasion stages, moves outside Scarlet / Violet, Terastallized players |
| 4 | status moves, stat stages, the common abilities and items | built: 34 switch-in abilities (Intimidate and the answers Own Tempo, Inner Focus, Contrary, Defiant, Competitive and Mirror Armor, Download, Trace, the boss's Imposter, weather, terrain, stat raises, announcements, a quiet Meteor-form Shields Down), abilities whose condition a round's moves do not meet, the contact abilities' draws (Static, Poison Point, Flame Body, Cute Charm between genders, Poison Touch), Rattled; rounds under sun, rain or snow that no move or ability reads; a sandstorm from Sand Stream, Sand Spit or the boss, its damage at the turn's end and the Rock types' Special Defense; status moves whose only effect is stat stages, Air Balloon popping; refused: rounds after the boss's Imposter, other status moves, terrain, abilities that act, Moody at a turn's end |
| 5 | fainting, the timer, the boss's actions and shield, the battle's end | built: the boss knocked out wins the battle; a player's knockout, its faint penalty on the battle timer (host and console Pokemon), the fainted slot's 0x21, its wait and the revive (0x23); the end of a turn every fourth command round; the battle timer with its pauses and time-up (0x2b); the boss's raid actions by HP inside a round and by time from the server (an internal 0x51), raid action rounds, the shield (its 0x47 pause, damage percent, re-check and end, then each player's unanswered turn), the time-left action, stat resets with ability suppression, extra moves aimed at the field or the boss; refused: an extra move aimed at a player, the double action, the Tera orb drain |

Over the 794 oracle battles of corpora `c1`, `d2`, `p1` and `q1` (`q1` with every draw logged), every round the plugin
builds equals the oracle's up to the first it refuses (861 rounds, every logged draw equal), and served
through pokeldn's `RaidBattle` with the corpus console replayed, `tools/battle_check.py` finds every
message the server sends equal to the oracle's at the same server time up to that point (99 whole battles,
31,581 messages, faints, revives, shields and raid action rounds among them); none different.
