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
| 3 | damage, accuracy, critical hits, the type chart, Tera | built: damage, stat stages and their floors and ceilings, the type chart, STAB, Tera-type boss moves (the 60-power floor after base power modifiers, a Terastallized Adaptability), accuracy and evasion stages, misses, critical hits (Focus Energy, always-critical moves), multi-hit moves, single-target moves at any position, priority moves, immune hits, recoil, drain, Steel Beam and Chloroblast, Life Orb, the type-boosting items, power rules (Payback, Hex, Reversal, Facade, Venoshock, Collision Course and kin), damage abilities (Hustle, Thick Fat, Tinted Lens, Ice Scales, Filter, Prism Armor, Purifying Salt and kin), speed ties everywhere, secondary effects (stat drops, self raises, statuses, confusion, flinch, Salt Cure, Heal Block) and self drops; refused: Terastallized players, moves whose own rule is not built |
| 4 | status moves, stat stages, the common abilities and items | built: 34 switch-in abilities, the boss's Imposter with its copied stats and failing Transform, statuses (infliction, before-move checks, residuals, cures), confusion and its self-hit, weather moves and abilities, weather ends and replacements, terrains with their power, heal and end, Tailwind, Reflect, Light Screen, Safeguard, Trick Room, Focus Energy, Stockpile, status moves that fail, contact answers (Static and kin, Rough Skin, Iron Barbs, Gooey), absorbing abilities (Sap Sipper, Motor Drive), Moody, Speed Boost, Moxie, Leftovers, Grassy Terrain; refused: two side conditions at one turn end, Trick Room's and Heal Block's ends, the long tail of single moves and abilities |
| 5 | fainting, the timer, the boss's actions and shield, the battle's end | built: the boss knocked out wins the battle; a player's knockout in a hit or at a turn's end, its faint penalty, the fainted slot's 0x21, its wait and the revive (0x23); the battle timer with its pauses and time-up (0x2b); the boss's raid actions by HP inside a round and by time from the server, raid action rounds, the shield (its 0x47 pause, damage percent, re-check, end and the failing status moves), the time-left action, the double action, stat resets with ability suppression, the Tera orb drain, extra moves at the field, the boss, a player or every player |

Over the oracle corpora `c1`, `d2`, `p1`, `q1`, `t1` and `u1` (`q1`, `t1` and `u1` with every draw logged), every round the plugin builds equals the oracle's up to the first it refuses (9,816 rounds, every logged draw equal; `tools/corpus_check.py rounds`). Served through pokeldn's `RaidBattle` with the corpus console replayed, `tools/battle_check.py` finds the server's messages equal to the oracle's at the same server time up to that point, but for message timings within a few frames around revives (pokeldn docs/sv_raid.md, The server's flow).
