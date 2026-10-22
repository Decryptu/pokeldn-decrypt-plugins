"""A battle's first round, built from its command, against those an oracle server sent: equal or
refused, never different. The cases are battles whose start body the plugin builds; records carry
their bytes with trailing zero bytes trimmed."""
import json
import sys
from pathlib import Path

from conftest import POKELDN
sys.path.insert(0, POKELDN)
from raidbattle import battlers, rounds  # noqa: E402
from raidbattle.server import Unsupported  # noqa: E402

CASES = json.loads((Path(__file__).parent / "data" / "first_rounds.json").read_text())


def unpack(h, n=None):
    raw = bytes.fromhex(h)
    return raw + bytes((n or len(raw)) - len(raw))


def test_first_rounds_are_equal_or_refused():
    equal = 0
    for case in CASES:
        n = case["sizes"]
        battle = battlers.battle(unpack(case["bootstrap"], n["bootstrap"]), [unpack(p, n["partner"]) for p in case["partners"]])
        command = unpack(case["command"], 0x100)
        try:
            got, _ = rounds.build(battle, command[0x19], command)
        except Unsupported:
            continue
        assert got == unpack(case["round"], rounds.BODY), case["file"]
        equal += 1
    assert equal >= 187
