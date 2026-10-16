#!/bin/sh
# Packs one plugin folder, signed, lists it in pokeldn-source.json and publishes it as a GitHub
# release tagged <id>-<version>. Needs a pokeldn checkout (POKELDN, default ../pokeldn) and the
# signing key (KEY, default ~/.config/pokeldn/decrypt-plugins.pem).
#
#   sh tools/publish.sh sv-raid-battle
set -e
folder="$1"
[ -f "$folder/plugin.toml" ] || { echo "usage: sh tools/publish.sh <plugin folder>" >&2; exit 2; }
root=$(cd "$(dirname "$0")/.." && pwd)
pokeldn=${POKELDN:-$root/../pokeldn}
key=${KEY:-$HOME/.config/pokeldn/decrypt-plugins.pem}
python=$pokeldn/.venv/bin/python
[ -x "$python" ] || python=python3
mkdir -p "$root/dist"
cd "$root/dist"
out=$("$python" "$pokeldn/scripts/pack_plugin.py" "$root/$folder" --key "$key")
echo "$out"
file=$(echo "$out" | grep "\.pokeplugin:" | head -1 | cut -d: -f1)
tag=${file%.pokeplugin}
cd "$root"
"$python" "$pokeldn/scripts/plugin_source.py" "dist/$file" -o pokeldn-source.json \
    --download "https://github.com/Decryptu/pokeldn-decrypt-plugins/releases/download/{id}-{version}/{file}" \
    --icon "https://raw.githubusercontent.com/Decryptu/pokeldn-decrypt-plugins/main/$folder/icon.png"
if [ "${PUBLISH:-1}" = 1 ]; then
    gh release create "$tag" "dist/$file" --title "$tag" --notes "$folder ${tag##*-}" \
        -R Decryptu/pokeldn-decrypt-plugins
fi
