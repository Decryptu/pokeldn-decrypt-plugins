"""pokeldn plugin: serves a Scarlet / Violet Tera Raid battle from the host (`--raid-serve`)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from raidbattle.server import Server  # noqa: E402


def register(api):
    api.add_battle_server("sv", "clean", Server, "Tera Raid battle (clean room)")
