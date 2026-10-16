"""raidbattle/data/moves.json from Pokemon Showdown's public move data (MIT licence,
https://play.pokemonshowdown.com/data/moves.json): the fields the battle uses, keyed by move number.
    gen_moves.py SHOWDOWN_MOVES.json"""
import json, os, sys

KEEP = ("name", "basePower", "type", "category", "accuracy", "priority", "critRatio", "target", "flags",
        "secondary", "secondaries", "multihit", "drain", "recoil", "self", "boosts", "status", "volatileStatus")
src = json.load(open(sys.argv[1]))
out = {}
for m in src.values():
    if m.get("num", 0) <= 0 or m.get("isNonstandard") in ("CAP", "Custom"):
        continue
    out[str(m["num"])] = {k: m[k] for k in KEEP if k in m}
    out[str(m["num"])]["callbacks"] = sorted(k for k in m if k.startswith("on") or k.endswith("Callback"))
path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "raidbattle", "data", "moves.json")
json.dump(out, open(path, "w"), sort_keys=True, separators=(",", ":"))
print(len(out), "moves")
