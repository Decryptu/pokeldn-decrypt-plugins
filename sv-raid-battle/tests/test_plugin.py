"""The plugin loads into pokeldn and serves a battle it builds."""
import json
import os
import sys
from pathlib import Path

import pytest

from conftest import POKELDN, HERE


@pytest.mark.skipif(not os.path.isdir(os.path.join(POKELDN, "pokeldn")), reason="needs a pokeldn checkout")
def test_pokeldn_finds_the_battle_server(monkeypatch):
    sys.path.insert(0, POKELDN)
    from pokeldn import plugins
    from pokeldn.sv import raid_battle
    monkeypatch.setenv("POKELDN_PLUGINS", os.path.dirname(HERE))
    monkeypatch.setattr(plugins, "_guard", lambda wanted: None)
    plugins._reset()
    try:
        server = plugins.battle_server("sv", "clean")
        assert server is not None and server.plugin == "sv-raid-battle"
        case = json.loads((Path(__file__).parent / "data" / "battles.json").read_text())[0]
        battle = raid_battle.RaidBattle(server.factory, bytes.fromhex(case["bootstrap"]),
                                        partners=[bytes.fromhex(p) for p in case["partners"]])
        battle.start(0.0)
        assert battle.poll(0.1)
    finally:
        plugins._reset()
