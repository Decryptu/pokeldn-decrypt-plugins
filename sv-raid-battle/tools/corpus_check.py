"""Compare the plugin's messages with an oracle corpus (pokeldn scratchpad/battle/corpus).
    corpus_check.py start 'CORPUS/*.json'
Prints, per battle, equal / refused (why) / different (first differing command)."""
import collections, glob, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.environ.get("POKELDN_ROOT", os.path.join(HERE, "..", "..", "..", "pokeldn")))
from raidbattle import battlers, queue, start
from raidbattle.server import Unsupported


def server_messages(d, kind):
    return [bytes.fromhex(h) for t, io, s, h in d["events"] if io == "out" and s == 2 and bytes.fromhex(h)[0] == kind]


def check_start(d):
    want = server_messages(d, 0x11)[0][0x20:]
    got = start.body(battlers.from_records(bytes.fromhex(d["bootstrap"]), [bytes.fromhex(p) for p in d["partners"]]))
    if got == want:
        return "equal", ""
    a, b = queue.decode(got), queue.decode(want)
    i = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))
    return "different", f"at {i}: ours {a[i:i+2]} oracle {b[i:i+2]}"


def main():
    what, pattern = sys.argv[1], sys.argv[2]
    tally, why = collections.Counter(), collections.Counter()
    for f in sorted(glob.glob(pattern)):
        d = json.load(open(f))
        try:
            verdict, detail = check_start(d)
        except Unsupported as e:
            verdict, detail = "refused", str(e)
            why[str(e).split("'s ")[-1]] += 1
        tally[verdict] += 1
        if verdict == "different":
            print(os.path.basename(f), detail)
    print(dict(tally))
    for k, n in why.most_common(10):
        print(f"  refused {n}: {k}")


if __name__ == "__main__":
    main()
