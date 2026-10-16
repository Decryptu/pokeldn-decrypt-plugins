# pokeldn plugins

Plugins for [pokeldn](https://github.com/Decryptu/pokeldn), one folder each.

| folder | plugin | what it adds |
|---|---|---|
| `sv-raid-battle` | Tera Raid battle server | serves a Scarlet / Violet Tera Raid battle from the host, so the console and the program's Pokemon fight one battle |

Install one by packing its folder with pokeldn's `scripts/pack_plugin.py FOLDER --key KEY` and dropping
the `.pokeplugin` on the app's Plugins page, or name the folder in `POKELDN_PLUGINS` while developing.

Every plugin here is written from public sources and pokeldn's own protocol documentation. None carries
code or data read out of a game.
