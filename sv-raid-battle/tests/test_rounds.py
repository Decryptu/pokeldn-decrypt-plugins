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
    assert equal >= 256


RUNS = json.loads((Path(__file__).parent / "data" / "round_runs.json").read_text())


def test_round_runs_in_sand_are_equal():
    """Battles under a sandstorm, Sand Stream's or Sand Spit's, each round built in order from the
    console's commands up to the first the plugin refused when the fixture was made."""
    for case in RUNS:
        n = case["sizes"]
        battle = battlers.battle(unpack(case["bootstrap"], n["bootstrap"]), [unpack(p, n["partner"]) for p in case["partners"]])
        for c, want in zip(case["commands"], case["rounds"]):
            command = unpack(c, 0x100)
            got, _ = rounds.build(battle, command[0x19], command)
            assert got == unpack(want, rounds.BODY), case["file"]
        assert "sand" in battle.field, case["file"]
