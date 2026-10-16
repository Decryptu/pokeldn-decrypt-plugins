"""The generator's draws against the oracle's (a translation kept outside this repository, run
from a pokeldn checkout's scratchpad when present)."""
import os
import random
import sys

import pytest

from conftest import ORACLE
from raidbattle import rng


class Memory:
    """The 0x28-byte generator object, for the oracle's functions."""

    def __init__(self, seed):
        self.words = {8: seed, 0x10: rng.SECOND_WORD, 0x18: seed, 0x20: 0}

    def u64(self, at):
        return self.words[at]

    def put(self, at, _size, value):
        self.words[at] = value


@pytest.mark.skipif(not os.path.isdir(ORACLE), reason="needs pokeldn's scratchpad oracle")
def test_draws_match_the_oracle():
    sys.path.insert(0, ORACLE)
    from svbattle.engine import random as oracle
    gen = random.Random(1)
    for _ in range(300):
        seed = gen.getrandbits(64)
        ours, m = rng.Random(seed), Memory(seed)
        for _ in range(40):
            if gen.random() < 0.5:
                n = gen.choice((0, 1, 2, 3, 5, 16, 100, 101, 1 << 20, gen.getrandbits(40)))
                assert ours.below(n) == oracle.below(m, 0, n)
            else:
                p = gen.randrange(0, 101)
                assert int(ours.chance(p)) == oracle.chance(m, 0, p)
            assert (ours.s0, ours.s1, ours.count) == (m.words[8], m.words[0x10], m.words[0x20])
