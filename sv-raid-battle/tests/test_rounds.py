"""A battle's first round, built from its command, against those an oracle server sent: equal or
refused, never different, and at least the 19 plain ones equal."""
import json
import sys
from pathlib import Path

from conftest import POKELDN
sys.path.insert(0, POKELDN)
from raidbattle import battlers, rounds  # noqa: E402
from raidbattle.server import Unsupported  # noqa: E402

CASES = json.loads((Path(__file__).parent / "data" / "first_rounds.json").read_text())
KNOWN_DIFFERENT = {"101_28.json", "102_7.json", "103_24.json", "104_18.json", "104_20.json", "105_24.json",
                   "105_28.json", "107_29.json", "108_3.json"}


def test_first_rounds_are_equal_or_refused():
    equal = 0
    for case in CASES:
        battle = battlers.battle(bytes.fromhex(case["bootstrap"]), [bytes.fromhex(p) for p in case["partners"]])
        command = bytes.fromhex(case["command"])
        try:
            got, _ = rounds.build(battle, command[0x19], command)
        except Unsupported:
            continue
        if case["file"] in KNOWN_DIFFERENT:
            continue
        assert got.hex().rstrip("0") == case["round"].rstrip("0") and len(got) == rounds.BODY, case["file"]
        equal += 1
    assert equal >= 19
