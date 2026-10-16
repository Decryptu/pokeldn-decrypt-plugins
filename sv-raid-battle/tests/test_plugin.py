"""The plugin loads into pokeldn and refuses a battle it cannot reproduce."""
import os
import sys

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
        with pytest.raises(Exception, match="not reproduced"):
            raid_battle.RaidBattle(server.factory, bytes(0x800), partners=[bytes(0x158)] * 2)
    finally:
        plugins._reset()
