"""raidbattle/data/abilities.json and items.json from Pokemon Showdown's server source (MIT licence,
https://github.com/smogon/pokemon-showdown, data/abilities.ts and data/items.ts): each entry's
callback names, keyed by number; type_boosts.json the items that raise one type's base power.
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


def type_boosts(path):
    """Items whose only base-power rule is 4915/4096 on one move type: number -> type."""
    parts = re.split(r"\n\t([a-z0-9]+): \{(?=\n)", open(path).read())
    out = {}
    for body in parts[2::2]:
        num = re.search(r"\n\t\tnum: (-?\d+)", body)
        rule = re.search(r"\n\t\tonBasePower\(basePower, user, target, move\) \{\n\t\t\tif \(move\.type === '(\w+)'\) \{"
                         r"\n\t\t\t\treturn this\.chainModify\(\[4915, 4096\]\);\n\t\t\t\}\n\t\t\},", body)
        if num and rule:
            out[num.group(1)] = rule.group(1)
    return out


json.dump(type_boosts(sys.argv[2]), open(os.path.join(DATA, "type_boosts.json"), "w"), sort_keys=True,
          separators=(",", ":"))
for src, name in zip(sys.argv[1:3], ("abilities", "items")):
    table = callbacks(src)
    json.dump(table, open(os.path.join(DATA, name + ".json"), "w"), sort_keys=True, separators=(",", ":"))
    print(len(table), name)
