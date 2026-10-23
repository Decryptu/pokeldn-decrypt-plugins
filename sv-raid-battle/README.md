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

`tools/corpus_check.py start|round 'CORPUS/*.json'` compares the plugin with a corpus of oracle battles
(pokeldn's `scratchpad/battle/oracle/corpus.py` writes one): equal, refused with the reason, or different.

## Milestones

| step | what | state |
|---|---|---|
| 1 | random numbers, the command queue codec, message headers | done: draws equal the oracle's on 300 seeds; 20 recorded queues round-trip |
| 2 | the battle start and one plain damaging move on the boss, byte for byte with a recorded round | done |
| 3 | damage, accuracy, critical hits, the type chart, Tera | built: damage, stat stages, the type chart, STAB, Tera-type boss moves, accuracy draws, single-target moves at any position, spread moves (one position hit in a raid), priority moves, immune hits, the move's slot, recoil, the type-boosting items, Overgrow / Blaze / Torrent / Swarm, Huge Power, Rivalry, a player's Adaptability, Focus Sash, turn order by staged Speed, secondary stat drops, the confusion and flinch secondaries' draws; refused: critical hits, misses, accuracy or evasion stages, moves outside Scarlet / Violet |
| 4 | status moves, stat stages, the common abilities and items | built: 34 switch-in abilities (Intimidate and the answers Own Tempo, Inner Focus, Contrary, Defiant, Competitive and Mirror Armor, Download, Trace, the boss's Imposter, weather, terrain, stat raises, announcements, a quiet Meteor-form Shields Down), abilities whose condition a round's moves do not meet, the contact abilities' draws (Static, Poison Point, Flame Body, Cute Charm, Poison Touch), Rattled; rounds under sun, rain or snow that no move or ability reads; built: status moves whose only effect is stat stages (Growth, Growl, Charm, Scary Face, Rock Polish), Air Balloon popping; refused: rounds after the boss's Imposter, other status moves, sand, terrain, abilities that act |
| 5 | fainting, the timer, the boss's actions and shield, the battle's end | built: the boss knocked out wins the battle, the end of a turn every fourth round; refused: a partner knocked out, a boss HP trigger, the boss's timed actions (the server sends none) |

Over the 554 oracle battles of corpora `c1`, `d2` and `p1`: start bodies 538 equal, first rounds 251 equal,
whole battles 48 equal and 204 equal up to a refused round; none different.
