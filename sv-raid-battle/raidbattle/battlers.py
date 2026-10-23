"""The five battlers of a raid and what the battle needs of each, from their party records.

Battler ids: 1 our Pokemon (slot 0), 2 the boss (slot 1), 3 the console's (slot 2), 4 and 5 the
partners (slots 3 and 4). A battler sits at position id - 1."""
from dataclasses import dataclass

from pokeldn import gen9

PARTY_RECORD = 0x158
SLOT = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4}
BOSS = 2

# Abilities seen with no switch-in event in 233 battles: never announced by themselves at the start.
QUIET_ABILITIES = frozenset([52, 103, 128, 135, 143, 153, 277, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14, 15, 17, 18, 19, 24, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 37, 38, 41, 42, 43, 44, 47, 48, 49, 50, 51, 53, 54, 55, 56, 57, 58, 60, 61, 62, 63, 65, 66, 67, 68, 69, 71, 72, 74, 75, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 89, 91, 92, 93, 94, 95, 97, 98, 100, 101, 102, 105, 106, 109, 110, 114, 115, 118, 120, 121, 124, 125, 126, 130, 131, 132, 133, 137, 139, 140, 141, 142, 144, 145, 146, 148, 149, 151, 154, 155, 156, 157, 158, 159, 165, 166, 167, 168, 170, 171, 172, 173, 175, 177, 178, 180, 181, 195, 196, 198, 199, 201, 202, 203, 206, 212, 216, 218, 220, 223, 232, 241, 243, 245, 246, 247, 252, 260, 262, 265, 270, 272, 273, 274, 279, 281, 282, 291, 292, 295, 298, 299, 305])


@dataclass
class Battler:
    id: int
    species: int
    form: int
    level: int
    ability: int
    item: int
    stats: tuple            # HP Atk Def Spe SpA SpD
    hp: int
    moves: tuple
    base_ability: int = 0   # the ability it was sent out with, when Trace or Imposter replaced it
    transformed: int = 0    # the battler Imposter copied

    @property
    def speed(self):
        return self.stats[3]


def from_records(bootstrap, partners):
    """-> {battler id: Battler} from the bootstrap and the two partners' records."""
    records = {0: bootstrap[:PARTY_RECORD], 2: bootstrap[PARTY_RECORD:2 * PARTY_RECORD],
               1: bootstrap[4 * PARTY_RECORD:5 * PARTY_RECORD], 3: partners[0], 4: partners[1]}
    out = {}
    for battler, slot in SLOT.items():
        f = gen9.read(gen9.decrypt(bytes(records[slot])))
        out[battler] = Battler(battler, f["species"], f["form"], f["level"], f["ability"], f["held_item"],
                               tuple(f["stats"]), f["current_hp"], tuple(f["moves"]))
    return out


TYPE_NONE = 19
MULTITYPE, RKS_SYSTEM = 121, 225


def battle(bootstrap, partners):
    """-> a rounds.Battle at the start: the battlers, the generator seeded with the RaidPoint's randSeed
    (pokeldn docs/sv_raid.md, The battle's random numbers), each battler's types and the boss's Tera type."""
    import struct
    from pokeldn.sv import raid_encounter
    from raidbattle import rng, rounds
    b = from_records(bootstrap, partners)
    seed = struct.unpack_from("<Q", bootstrap, 5 * PARTY_RECORD + 0x3D8)[0]
    try:
        types = {i: [rounds.TYPES[t] for t in dict.fromkeys(raid_encounter.personal(x.species, x.form)[1])]
                 for i, x in b.items()}
    except KeyError as e:
        from raidbattle.server import Unsupported
        raise Unsupported(f"species {e} has no personal entry") from None
    for i, x in b.items():
        if x.ability in (MULTITYPE, RKS_SYSTEM):    # Showdown: the type follows the plate or memory held
            if {"onPlate", "onMemory"} & set(rounds.ITEMS.get(str(x.item)) or ()):
                from raidbattle.server import Unsupported
                raise Unsupported(f"battler {i} holds a type item")
            types[i] = ["Normal"]
    boss = gen9.read(gen9.decrypt(bytes(bootstrap[4 * PARTY_RECORD:5 * PARTY_RECORD])))
    tera = boss["tera_type_override"] if boss["tera_type_override"] != TYPE_NONE else boss["tera_type_original"]
    from raidbattle import start
    battle = rounds.Battle(b, rng.Random(seed), types, rounds.TYPES[tera])
    profile = struct.unpack_from("<37I", bootstrap, 5 * PARTY_RECORD + 0x4C)
    battle.hp[rounds.BOSS] = battle.full[rounds.BOSS] = b[rounds.BOSS].stats[0] * profile[0] // 100
    battle.triggers = boss_triggers(profile)
    start.body(b, battle.stages, battle)
    return battle


def boss_triggers(profile):
    """The boss's HP shares (percent) at which its action profile acts (pokeldn docs/sv_raid.md, The
    RaidPoint): the shield, each extra action with HP timing (2), the double action."""
    out = {profile[1], profile[34]}
    for i in range(6):
        action, timing, value, _move = profile[10 + 4 * i:14 + 4 * i]
        if action and timing == 2:
            out.add(value)
    return frozenset(out - {0})
