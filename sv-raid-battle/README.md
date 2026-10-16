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
| 2 | the battle start and one plain damaging move on the boss, byte for byte with a recorded round | done: start bodies 144 of 233 equal; first rounds 19 of 232 equal, 9 different (moves with handlers, switch-in stat changes), the rest refused; the server's flow equals the oracle's over 9 whole battles |
| 3 | damage, accuracy, critical hits, the type chart, Tera | open |
| 4 | status moves, stat stages, the common abilities and items | open |
| 5 | fainting, the timer, the boss's actions and shield, the battle's end | open |
