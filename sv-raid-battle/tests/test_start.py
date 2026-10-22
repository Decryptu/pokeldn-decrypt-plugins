"""The battle-start body against 62 an oracle server sent: equal, or refused; never different."""
import json
from pathlib import Path

import pytest

from conftest import POKELDN
import sys
sys.path.insert(0, POKELDN)
from raidbattle import battlers, start  # noqa: E402
from raidbattle.server import Unsupported  # noqa: E402

STARTS = json.loads((Path(__file__).parent / "data" / "starts.json").read_text())


def test_every_start_is_equal_or_refused():
    equal = 0
    for case in STARTS:
        try:
            got = start.body(battlers.from_records(bytes.fromhex(case["bootstrap"]),
                                                   [bytes.fromhex(p) for p in case["partners"]]))
        except Unsupported:
            continue
        assert got.hex() == case["start"]
        equal += 1
    assert equal >= 56
