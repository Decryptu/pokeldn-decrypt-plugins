"""Serve a corpus battle again with the plugin's server: every message the oracle read goes in at its
recorded server time, and every message the oracle sent must come out of ours by the same poll, equal.
    replay_check.py 'CORPUS/*.json' [-v]
Prints per battle: equal (messages compared), or the first difference (time, slot, kind) or refusal."""
import collections, glob, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.environ.get("POKELDN_ROOT", os.path.join(HERE, "..", "..", "..", "pokeldn")))
from raidbattle.server import Server, Unsupported
from raidbattle import messages


def replay(d):
    """-> (verdict, detail, messages compared)."""
    server = Server(bytes.fromhex(d["bootstrap"]), [bytes.fromhex(p) for p in d["partners"]])
    ours = collections.defaultdict(list)
    events = [e for e in d["events"] if e[0] != "draw"]

    def drain():
        for slot in range(5):
            ours[slot] += server.sent(slot)

    server.start(0.0)
    compared = 0
    try:
        for t, io, slot, h in events:
            if t > server.t:
                server.run(t)
            drain()
            raw = bytes.fromhex(h)
            if io == "in":
                server.receive(slot, raw)
                continue
            if not ours[slot]:
                return "different", f"{t:.2f} slot {slot}: oracle sent {raw[0]:#x} step {messages.header(raw)[1]}, ours nothing", compared
            got = ours[slot].pop(0)
            if got != raw:
                k = messages.header(raw)
                g = messages.header(got)
                return "different", f"{t:.2f} slot {slot}: oracle {raw[0]:#x} step {k[1]} round {k[2]}, ours {got[0]:#x} step {g[1]} round {g[2]}" + (" (bodies differ)" if got[0] == raw[0] else ""), compared
            compared += 1
    except Unsupported as e:
        return "refused", str(e), compared
    extra = {s: [m[0] for m in q] for s, q in ours.items() if q}
    if extra:
        return "different", f"ours sent more: {extra}", compared
    return "equal", "", compared


def main():
    tally = collections.Counter()
    verbose = "-v" in sys.argv
    for f in sorted(glob.glob(sys.argv[1])):
        try:
            v, detail, n = replay(json.load(open(f)))
        except Unsupported as e:
            v, detail, n = "refused at start", str(e), 0
        tally[v] += 1
        if verbose or v == "different":
            print(os.path.basename(f), v, n, detail)
    print(dict(tally))


if __name__ == "__main__":
    main()
