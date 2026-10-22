"""raidbattle/data/moves.json from Pokemon Showdown's public move data (MIT licence,
https://play.pokemonshowdown.com/data/moves.json): the fields the battle uses, keyed by move number.
The callbacks come from the server source data/moves.ts, which the client data strips.
    gen_moves.py SHOWDOWN_MOVES.json MOVES.ts"""
import json, os, re, sys

KEEP = ("name", "basePower", "type", "category", "accuracy", "priority", "critRatio", "target", "flags",
        "secondary", "secondaries", "multihit", "drain", "recoil", "self", "boosts", "status", "volatileStatus",
        "isNonstandard")
src = json.load(open(sys.argv[1]))
SERVER = {}
for body in re.split(r"\n\t[a-z0-9]+: \{(?=\n)", open(sys.argv[2]).read())[1:]:
    num = re.search(r"\n\t\tnum: (-?\d+)", body)
    if num:
        SERVER[num.group(1)] = sorted(set(re.findall(
            r"\n\t\t([A-Za-z]+Callback|on[A-Za-z]+|override[A-Za-z]+|ignore[A-Za-z]+|condition|selfSwitch|"
            r"forceSwitch|breaksProtect|willCrit|thawsTarget|hasCrashDamage|selfdestruct|ohko|damage|heal|"
            r"weather|terrain|pseudoWeather|sideCondition|slotCondition|multiaccuracy|selfBoost)\b", body)))
out = {}
for m in src.values():
    if m.get("num", 0) <= 0 or m.get("isNonstandard") in ("CAP", "Custom"):
        continue
    out[str(m["num"])] = {k: m[k] for k in KEEP if k in m}
    out[str(m["num"])]["callbacks"] = SERVER.get(str(m["num"]), ["unknown"])
path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "raidbattle", "data", "moves.json")
json.dump(out, open(path, "w"), sort_keys=True, separators=(",", ":"))
print(len(out), "moves")
