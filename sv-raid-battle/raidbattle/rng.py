"""The battle's random numbers: one xoroshiro128+ generator seeded with the raid's seed
(pokeldn docs/sv_raid.md, The battle's random numbers)."""

MASK = (1 << 64) - 1
SECOND_WORD = 0x82A2B175229D6A5B     # the state's second word at seeding


def _rotl(x, k):
    return ((x << k) | (x >> (64 - k))) & MASK


class Random:
    """xoroshiro128+ (Blackman and Vigna, 2016): a draw is s0 + s1, then the state steps."""

    def __init__(self, seed):
        self.seed = seed & MASK
        self.s0, self.s1 = self.seed, SECOND_WORD
        self.count = 0              # calls made, not redraws

    def next(self):
        s0, s1 = self.s0, self.s1
        out = (s0 + s1) & MASK
        s1 ^= s0
        self.s0 = _rotl(s0, 24) ^ s1 ^ ((s1 << 16) & MASK)
        self.s1 = _rotl(s1, 37)
        return out

    def below(self, n):
        """-> a number below n: the draw masked to the bits of n - 1, redrawn while n or more;
        n below 2 returns 0 and draws nothing."""
        if n < 2:
            return 0
        self.count += 1
        mask = (1 << (n - 1).bit_length()) - 1
        while True:
            x = self.next() & mask
            if x < n:
                return x

    def chance(self, percent):
        """-> True with `percent` in 100: the draw's low 7 bits, redrawn while 100 or more."""
        self.count += 1
        while True:
            x = self.next() & 0x7F
            if x < 100:
                return x < percent
