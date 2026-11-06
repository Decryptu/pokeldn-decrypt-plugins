# Emerald swap

A pokeldn tool under FireRed and LeafGreen that streams Emerald into a running English FireRed on a
stock console, over Mystery Gift, then soft-resets into it. The FireRed title is untouched: Emerald
lasts until the game is closed.

The plugin carries no game. `emerald_bpre.bps` turns the player's own Pokemon Emerald (USA, Europe),
SHA-1 `f3ae088181bf583e55daf962a92bb46f4f1d07b7`, into the Switch build pokeldn's `tools/rse` compiles
from the public decompilation.

| part | what it does |
|---|---|
| 1 | backs the FireRed save up into the plugin's library; part 3 refuses to start without one |
| 2 | optional: writes an Emerald `.sav` beside the console's newest save |
| 3 | streams Emerald: about 3 h 20 min with an English FireRed file, about 5 h 30 min without |

Parts 2 and 3 run in one launch of the game: the application keeps the save in memory until a game
saves. Turn the console's auto-sleep off before part 3. A stream cut by sleep went back to the title
screen and went on from where it stopped in the next run; after a link error the game can stay on a
black screen, and then the stream starts over in a new launch.

Only English FireRed has a measured set of the blocks a session runs from, so every other cartridge
is refused before anything is written.

Saving in Emerald replaces the FireRed save on the console, and FireRed may then not read either copy.
From a locked game there is no Mystery Gift, so no way to restore the backup from the console. This is
read from the games' code and unmeasured. Use this with a save you can lose.

Measured on a retail Switch Lite with a XIAO ESP32S3 and the FireRed file: 3645 of 3645 blocks in
3 h 18 min, then an Emerald save loaded and saved in game. The run without a FireRed file is checked
under emulation only.

## Rebuilding the patch

    cd ../../pokeldn
    ./.venv/bin/python tools/rse/emerald_switch_build.py --tree ~/pokeemerald_switch --cart BPRE --cpp /opt/homebrew/bin/cpp-16
    cd -
    python tools/make_patch.py RETAIL.gba ~/pokeemerald_switch/pokeemerald_switch_BPRE.gba emerald_bpre.bps
