import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
# a pokeldn checkout, for the tests that load the plugin and its oracle: POKELDN_ROOT or a sibling folder
POKELDN = os.environ.get("POKELDN_ROOT", os.path.join(HERE, "..", "..", "..", "pokeldn"))
ORACLE = os.path.join(POKELDN, "scratchpad", "battle", "oracle")
