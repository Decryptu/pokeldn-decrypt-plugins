"""Compare the plugin's messages with an oracle corpus (pokeldn scratchpad/battle/corpus).
    corpus_check.py start 'CORPUS/*.json'
Prints, per battle, equal / refused (why) / different (first differing command)."""
import collections, glob, json, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.environ.get("POKELDN_ROOT", os.path.join(HERE, "..", "..", "..", "pokeldn")))
from raidbattle import battlers, queue, start
from raidbattle.server import Unsupported


def server_messages(d, kind):
    return [bytes.fromhex(e[3]) for e in d["events"] if e[0] != "draw" and e[1] == "out" and e[2] == 2
            and bytes.fromhex(e[3])[0] == kind]


def check_start(d):
    want = server_messages(d, 0x11)[0][0x20:]
    records = bytes.fromhex(d["bootstrap"]), [bytes.fromhex(p) for p in d["partners"]]
    try:
        battle = battlers.battle(*records)
    except Unsupported:                       # a species with no personal entry: no types
        battle = None
    got = start.body(battle.b if battle else battlers.from_records(*records), None, battle)
    if got == want:
        return "equal", ""
    a, b = queue.decode(got), queue.decode(want)
    i = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))
    return "different", f"at {i}: ours {a[i:i+2]} oracle {b[i:i+2]}"


def check_round(d):
    """The battle's first round, built from its command, against the oracle's."""
    from raidbattle import rounds
    events = [e for e in d["events"] if e[0] != "draw"]
    command = next(bytes.fromhex(h) for t, io, s, h in events if io == "in" and h[:2] == "06")
    rounds_sent = server_messages(d, 0x15)
    if not rounds_sent:
        raise Unsupported("no round")
    want = rounds_sent[0][0x20:]
    battle = battlers.battle(bytes.fromhex(d["bootstrap"]), [bytes.fromhex(p) for p in d["partners"]])
    start.body(battle.b, None, battle)                      # the server refuses what its start body cannot build
    got, _ = rounds.build(battle, command[0x19], command)
    if got == want:
        return "equal", ""
    if got[:0x238] != want[:0x238]:
        i = next(i for i in range(0x238) if got[i] != want[i])
        return "different", f"action block at {i:#x}: {got[i:i+8].hex()} oracle {want[i:i+8].hex()}"
    n, m = struct.unpack_from("<I", got, 0x238)[0], struct.unpack_from("<I", want, 0x238)[0]
    a, b = queue.decode(got[0x23c:0x23c + n]), queue.decode(want[0x23c:0x23c + m])
    i = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))
    return "different", f"command {i}: ours {a[i:i+2]} oracle {b[i:i+2]}"


def raid_words(body):
    """-> [(kind, value)] of a raid action round's block (slot 1)."""
    out = []
    for i in range(body[0x231]):
        w, = struct.unpack_from("<Q", body, 0x70 + 16 * i)
        out.append(((w >> 4) & 0xFF, w >> 32))
    return out


def timed(battle, words):
    """Whether the boss's time triggers give `words` at some time left on the battle timer."""
    r = battle.raid
    return any(r.triggers(battle, lambda: left) == words for left in range(r.limit, -600, -1))


def check_rounds(d):
    """Every round of the battle, built in order (a command's round from the command, a raid action round
    from the actions the oracle queued), against the oracle's: the verdict of the first round that is not
    equal, and how many came before it. A raid action round must be what the plugin queued (a shield by
    HP) or what its time triggers give at some time left."""
    from raidbattle import rounds
    events = [e for e in d["events"] if e[0] != "draw"]
    commands = {}
    for t, io, s, h in events:
        if io == "in" and h[:2] == "06":
            commands.setdefault(bytes.fromhex(h)[0x19], []).append(bytes.fromhex(h))
    sent = [(m[0], m[0x20:]) for m in (bytes.fromhex(e[3]) for e in events if e[1] == "out" and e[2] == 2)
            if m[0] in (0x15, 0x23)]
    battle = battlers.battle(bytes.fromhex(d["bootstrap"]), [bytes.fromhex(p) for p in d["partners"]])
    start.body(battle.b, None, battle)
    rounds_done = 0
    for n, (kind, want) in enumerate(sent):
        try:
            if kind == 0x23:
                got = rounds.revive(battle, next(i for i in range(5) if want[0x230 + i]))
                if got != want:
                    a, b = (queue.decode(x[0x23c:0x23c + struct.unpack_from("<I", x, 0x238)[0]]) for x in (got, want))
                    i = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))
                    return "different", f"revive after round {rounds_done} command {i}: ours {a[i:i+2]} oracle {b[i:i+2]}"
                continue
            if want[0x231]:
                words = raid_words(want)
                queued = battle.raid.pending
                if queued and any(k == 1 for k, v in queued):
                    if words != queued:
                        return "different", f"round {rounds_done}: raid actions {words}, queued {queued}"
                elif not timed(battle, words):
                    return "different", f"round {rounds_done}: raid actions {words} at no time left"
                got, won = rounds.raid_round(battle, words)
            else:
                if battle.raid.pending and any(k == 1 for k, v in battle.raid.pending):
                    return "different", f"round {rounds_done}: a command round, queued {battle.raid.pending}"
                command = commands[next(i for i in range(5) if want[0x230 + i])].pop(0)
                got, won = rounds.build(battle, command[0x19], command)
        except Unsupported as e:
            if rounds_done == 0:
                raise
            return "partial", f"{rounds_done} of {sum(k == 0x15 for k, w in sent)}; then {e}"
        if got != want:
            if got[:0x238] != want[:0x238]:
                return "different", f"round {rounds_done} action block"
            m = struct.unpack_from("<I", want, 0x238)[0]
            a, b = queue.decode(got[0x23c:0x23c + struct.unpack_from("<I", got, 0x238)[0]]), queue.decode(want[0x23c:0x23c + m])
            i = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))
            if os.environ.get("CC_SHOW"):
                print([(hex(k), v) for k, v in a[max(0, i - 12):i + 6]], "\n", [(hex(k), v) for k, v in b[max(0, i - 12):i + 6]])
            return "different", f"round {rounds_done} command {i}: ours {a[i:i+2]} oracle {b[i:i+2]}"
        rounds_done += 1
    return "equal", f"{rounds_done} rounds"


def main():
    what, pattern = sys.argv[1], sys.argv[2]
    tally, why = collections.Counter(), collections.Counter()
    for f in sorted(glob.glob(pattern)):
        d = json.load(open(f))
        try:
            verdict, detail = {"round": check_round, "rounds": check_rounds, "start": check_start}[what](d)
        except Unsupported as e:
            verdict, detail = "refused", str(e)
            why[str(e).split("'s ")[-1] if what == "start" else str(e)] += 1
        tally[verdict] += 1
        if verdict in ("different", "partial") or what == "rounds" and verdict == "equal":
            print(os.path.basename(f), detail)
    print(dict(tally))
    for k, n in why.most_common(10):
        print(f"  refused {n}: {k}")


if __name__ == "__main__":
    main()
