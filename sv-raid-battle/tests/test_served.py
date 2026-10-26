"""Corpus battles served by the plugin's server through pokeldn's RaidBattle and the corpus's scripted
console, its recorded moves replayed: every message the server reads and sends, at its server time, equal
to the oracle's up to the point where the plugin stops (a refusal). The battles hold faints and revives
(messages 0x21 and 0x23), the shield's pause (0x47) and raid action rounds."""
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from conftest import POKELDN, HERE

CASES = json.loads((Path(__file__).parent / "data" / "served.json").read_text())


def unpack(h, n):
    raw = bytes.fromhex(h)
    return raw + bytes(n - len(raw))


@pytest.mark.skipif(not os.path.isdir(os.path.join(POKELDN, "pokeldn")), reason="needs a pokeldn checkout")
@pytest.mark.parametrize("case", CASES, ids=[c["file"] for c in CASES])
def test_a_served_battle_equals_the_oracle(case):
    sys.path.insert(0, POKELDN)
    sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
    import battle_check as bc
    from pokeldn.sv import raid_battle as rb
    from raidbattle.server import Server, Unsupported
    n = case["sizes"]
    boot = unpack(case["bootstrap"], n["bootstrap"])
    log = []
    battle = rb.RaidBattle(lambda b, p: bc.Recorder(Server(b, p), log), boot,
                           partners=[unpack(p, n["partner"]) for p in case["partners"]])
    try:
        bc.console(battle, boot, bc.Recorded(case["moves"]))
    except Unsupported:
        pass
    got = [[round(e[0], 6), e[1], e[2], hashlib.sha1(bytes.fromhex(e[3])).hexdigest()[:16]] for e in log]
    assert got[:len(case["log"])] == case["log"]
