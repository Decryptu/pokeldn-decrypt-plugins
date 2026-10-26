"""Serve a corpus battle again with the plugin's server, through pokeldn's RaidBattle and the corpus's
scripted console replaying its recorded moves: the server's whole log (each message in and out, with
its server time) against the oracle's.
    battle_check.py 'CORPUS/*.json' [-v]
Prints per battle: equal (events compared), refused (why, after how many equal events), or the first
event that differs."""
import collections, glob, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.environ.get("POKELDN_ROOT", os.path.join(HERE, "..", "..", "..", "pokeldn")))
from raidbattle.server import Server, Unsupported


class Recorder:
    """The server interface, logging what goes in and comes out (the corpus's log format)."""

    def __init__(self, inner, log):
        self.inner, self.log = inner, log

    t = property(lambda self: self.inner.t)

    def start(self, now):
        return self.inner.start(now)

    def run(self, until):
        return self.inner.run(until)

    def receive(self, slot, message):
        self.log.append([self.inner.t, "in", slot, bytes(message).hex()])
        self.inner.receive(slot, message)

    def sent(self, slot):
        out = self.inner.sent(slot)
        self.log += [[self.inner.t, "out", slot, bytes(m).hex()] for m in out]
        return out


class Recorded:
    """The scripted console's move choices, in the order the corpus recorded them."""

    def __init__(self, moves):
        self.moves = list(moves)

    def choice(self, known):
        return self.moves.pop(0) if self.moves else known[0]


def console(battle, boot, rnd, until=900.0, delay=0.3):
    """The corpus's console at slot 2 (pokeldn scratchpad/battle/oracle/corpus.py)."""
    from pokeldn import gen9
    from pokeldn.sv import raid_battle as rb
    them = gen9.read(gen9.decrypt(bytes(boot[0x158:0x2B0])))["moves"]
    boss = rb.first_move(boot[4 * 0x158:5 * 0x158])
    known = [m for m in them if m] or [0]
    now, pending = 0.0, []
    battle.start(now)
    while not battle.over and now < until:
        now += 0.1
        for item in [p for p in pending if p[0] <= now]:
            pending.remove(item)
            battle.receive(2, item[1], now)
        for slot, raw in battle.poll(now):
            x, y, msg = rb.unframe(raw)
            if x != rb.SERVER:
                continue
            if msg[0] == rb.REQUEST:
                pending.append((now + delay, rb.command(msg, 2, rnd.choice(known), boss)))
            elif msg[0] & 1:
                pending.append((now + delay, rb.answer(msg, 2)))


def check(d):
    from pokeldn.sv import raid_battle as rb
    import struct
    boot = bytes.fromhex(d["bootstrap"])
    want = [e for e in d["events"] if e[0] != "draw"]
    moves = [struct.unpack_from("<Q", bytes.fromhex(h), 0x28)[0] >> 8 & 0xFFFF
             for t, io, s, h in want if io == "in" and s == 2 and h[:2] == "06"]
    log = []
    try:
        battle = rb.RaidBattle(lambda b, p: Recorder(Server(b, p), log), boot, partners=[bytes.fromhex(p) for p in d["partners"]])
        console(battle, boot, Recorded(moves))
        verdict = "equal"
    except Unsupported as e:
        verdict = f"refused ({e})"
    for i, (g, w) in enumerate(zip(log, want)):
        if g != w:
            return "different", i, f"{w[0]:.2f} {w[1]} slot {w[2]} oracle {w[3][:2]} / ours {g[0]:.2f} {g[1]} slot {g[2]} {g[3][:2]}" + (" (bodies differ)" if g[3][:2] == w[3][:2] else "")
    if verdict == "equal" and len(log) != len(want):
        return "different", min(len(log), len(want)), f"ours {len(log)} events, oracle {len(want)}"
    return verdict, min(len(log), len(want)), ""


def main():
    tally = collections.Counter()
    for f in sorted(glob.glob(sys.argv[1])):
        v, n, detail = check(json.load(open(f)))
        tally[v.split(" (")[0]] += 1
        if "-v" in sys.argv or v == "different":
            print(os.path.basename(f), v, n, detail)
    print(dict(tally))


if __name__ == "__main__":
    main()
