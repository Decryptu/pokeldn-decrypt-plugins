"""Whole battles served by the plugin's own server against what an oracle server sent: the same
bootstrap and partners and the same scripted console, every frame the console receives equal. The
frames carry their bytes with trailing zero bytes trimmed."""
import json
import os
import random
import sys
from pathlib import Path

import pytest

from conftest import POKELDN, HERE

CASES = json.loads((Path(__file__).parent / "data" / "battles.json").read_text())


def console(battle, boot, rnd, got, until=900.0, delay=0.3):
    """The console at slot 2: odd steps answered `delay` later, requests with a random known move
    (the oracle corpus's scripted console)."""
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
            got.append([round(now, 2), x, msg])
            if x != rb.SERVER:
                continue
            if msg[0] == rb.REQUEST:
                pending.append((now + delay, rb.command(msg, 2, rnd.choice(known), boss)))
            elif msg[0] & 1:
                pending.append((now + delay, rb.answer(msg, 2)))


@pytest.mark.skipif(not os.path.isdir(os.path.join(POKELDN, "pokeldn")), reason="needs a pokeldn checkout")
@pytest.mark.parametrize("case", CASES, ids=[c["file"] for c in CASES])
def test_a_whole_battle_equals_the_oracle(case):
    sys.path.insert(0, POKELDN)
    from pokeldn.sv import raid_battle as rb
    from raidbattle.server import Server
    boot = bytes.fromhex(case["bootstrap"])
    battle = rb.RaidBattle(Server, boot, partners=[bytes.fromhex(p) for p in case["partners"]])
    got = []
    console(battle, boot, random.Random(case["seed"]), got)
    want = [[t, x, bytes.fromhex(h) + bytes(n - len(h) // 2)] for t, x, h, n in case["frames"]]
    assert len(got) == len(want)
    for g, w in zip(got, want):
        assert g == w
