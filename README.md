# pokeldn plugins

Plugins for [pokeldn](https://github.com/Decryptu/pokeldn), one folder each, and the source listing
`pokeldn-source.json` that names their released packages.

| folder | plugin | what it adds |
|---|---|---|
| `sv-raid-battle` | Tera Raid battle server | serves a Scarlet / Violet Tera Raid battle from the host, so the console and the program's Pokemon fight one battle |

## Installing

pokeldn follows this source out of the box: open **Plugins**, then **Browse**, and press **Install**
on a plugin. Another copy of pokeldn adds it under **Plugins**, **Sources** as

    Decryptu/pokeldn-decrypt-plugins

Every package is signed with key `J4LO-AFRT-JCX3-7N7V`; the install screen shows the same fingerprint.
A `.pokeplugin` from [Releases](https://github.com/Decryptu/pokeldn-decrypt-plugins/releases) can also
be dropped on the Plugins page.

## Publishing a version

Raise `version` in the plugin's `plugin.toml`, then

    sh tools/publish.sh sv-raid-battle

packs the folder signed with `~/.config/pokeldn/decrypt-plugins.pem`, lists it in
`pokeldn-source.json` with its SHA-256, and creates the `<id>-<version>` release holding the package.
Commit and push `pokeldn-source.json` afterwards: players see the new version once it is on `main`.
`exclude` in `plugin.toml` keeps tests and tools out of the package.

Every plugin here is written from public sources and pokeldn's own protocol documentation. None carries
code or data read out of a game.
