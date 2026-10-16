"""raidbattle/data/abilities.json and items.json from Pokemon Showdown's server source (MIT licence,
https://github.com/smogon/pokemon-showdown, data/abilities.ts and data/items.ts): each entry's
callback names, keyed by number.
    gen_effects.py ABILITIES.ts ITEMS.ts"""
import json, os, re, sys

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "raidbattle", "data")


def callbacks(path):
    parts = re.split(r"\n\t([a-z0-9]+): \{(?=\n)", open(path).read())
    out = {}
    for body in parts[2::2]:
        num = re.search(r"\n\t\tnum: (-?\d+)", body)
        if not num or int(num.group(1)) <= 0:
            continue
        keys = set(re.findall(r"\n\t\t(on[A-Za-z]+|condition|boosts)\b(?!: -?[\d.])", body))
        out[num.group(1)] = sorted(keys | set(re.findall(r"\n\t\t(onFractionalPriority)\b", body)))
    return out


for src, name in zip(sys.argv[1:3], ("abilities", "items")):
    table = callbacks(src)
    json.dump(table, open(os.path.join(DATA, name + ".json"), "w"), sort_keys=True, separators=(",", ":"))
    print(len(table), name)
