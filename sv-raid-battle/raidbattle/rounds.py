"""A round (message 0x15): the acting slot's action block, then the command queue its actions produce
(pokeldn docs/sv_raid.md, A move in the round queue; Damage and draws per move). Only plain moves are
built: a single-target damaging move with no effect that changes the battle beyond its damage. Anything
else raises Unsupported."""
import json
import os
import struct

from raidbattle import queue, raid
from raidbattle.battlers import BOSS
from raidbattle.server import Unsupported

MOVES = {int(k): v for k, v in json.load(open(os.path.join(os.path.dirname(__file__), "data", "moves.json"))).items()}
TYPES = ("Normal", "Fighting", "Flying", "Poison", "Ground", "Rock", "Bug", "Ghost", "Steel", "Fire", "Water",
         "Grass", "Electric", "Psychic", "Ice", "Dragon", "Dark", "Fairy")
POSITION = {1: 0, 3: 1, 4: 2, 5: 3, BOSS: 4}
BATTLER_AT = {v: k for k, v in POSITION.items()}
BLOCK, ACTION, COUNTS, BODY = 0x70, 0x10, 0x230, 0x5060
END = 0xFFFF0000
CRIT_DRAW = {1: 24, 2: 8, 3: 2}
CRIT_GUARD = frozenset((4, 75))                 # Battle Armor, Shell Armor
_data = lambda name: json.load(open(os.path.join(os.path.dirname(__file__), "data", name)))
ABILITIES, ITEMS = _data("abilities.json"), _data("items.json")
# callbacks that cannot fire in a plain round: switching, statuses, boosts, weather, fainting
INERT = {"onStart", "onEnd", "onSwitchIn", "onSwitchOut", "onAnySwitchIn", "onDeductPP", "onSetStatus",
         "onAllySetStatus", "onTryAddVolatile", "onAllyTryAddVolatile", "onImmunity", "onTryBoost",
         "onChangeBoost", "onAfterBoost", "onAfterEachBoost", "onTryEatItem", "onFoeTryEatItem", "onEatItem",
         "onTakeItem", "onFoeTrapPokemon", "onFoeMaybeTrapPokemon", "onDragOut", "onModifyWeight",
         "onWeather", "onWeatherChange", "onAnySetWeather", "onTerrainChange", "onAllyFaint",
         "onSourceAfterFaint", "onFaint", "onUpdate", "condition"}
# abilities and items whose callbacks did not fire in any plain first round of the oracle corpus
IDLE_ABILITIES = frozenset((0, 3, 29, 33, 34, 44, 53, 77, 81, 84, 137, 141, 232, 246, 304))
IDLE_ITEMS = frozenset((234, 541))
# move callbacks that cannot fire in a plain round (Facade: a status the round never sets)
# moves whose power callback Battle.move_power builds
IDLE_MOVE_CALLBACKS = {"Facade": {"onBasePower"}, "Venoshock": {"onBasePower"}, "Electro Drift": {"onBasePower"},
                       "Collision Course": {"onBasePower"}, "Expanding Force": {"onBasePower"},
                       "Payback": {"basePowerCallback"}, "Hex": {"basePowerCallback"},
                       "Rising Voltage": {"basePowerCallback"}}
PRESSURE = 46               # a move aimed at it spends 2 PP: 0x05 (b, 0, 2)
STURDY = 5
INNER_FOCUS = 39
# Showdown abilities.ts, flag cantsuppress: kept through the players' reset
CANT_SUPPRESS = frozenset((121, 161, 176, 197, 208, 209, 210, 211, 213, 225, 241, 248, 266, 267, 278, 307))
AIR_BALLOON = 541
SHIELDS_DOWN = 197
LEVITATE = 26
ICE_SCALES = 246
FILTER, SOLID_ROCK, PRISM_ARMOR = 111, 116, 232
TANGLED_FEET, TOXIC_BOOST = 77, 137
ROCK_HEAD, MAGIC_GUARD = 69, 98
PINCH = {65: "Grass", 66: "Fire", 67: "Water", 68: "Bug"}
HUGE_POWER, PURE_POWER, ADAPTABILITY = 37, 74, 91
FOCUS_SASH = 275
RIVALRY = 79
SAND_SPIT, SMOOTH_ROCK = 245, 283
# Showdown: moves whose power, effect or accuracy sandstorm changes
# Showdown abilities.ts: onModifySpe doubling in a weather; onModifyAccuracy lowering a move's accuracy
SPEED_WEATHER = {33: "rain", 34: "sun", 146: "sand", 202: "snow"}
EVADE_WEATHER = {8: "sand", 81: "snow"}
WEATHER_HANDLED = frozenset(SPEED_WEATHER) | frozenset(EVADE_WEATHER)
SAND_IMMUNE = frozenset({8, 142, 146, 159})                     # Sand Veil, Overcoat, Sand Rush, Sand Force
SAND_MOVES = frozenset({"Weather Ball", "Solar Beam", "Solar Blade", "Shore Up", "Synthesis", "Moonlight",
                        "Morning Sun"})
TYPE_BOOSTS = _data("type_boosts.json")
CONTACT_STATUS = frozenset((9, 38, 49, 56))     # Static, Poison Point, Flame Body, Cute Charm: the target's
CUTE_CHARM = 56                                 # draws only between a male and a female
MOLD_BREAKERS = frozenset((104, 163, 164))      # Mold Breaker, Turboblaze, Teravolt: Inner Focus ignored
POISON_TOUCH = 143                              # the attacker's
CONTACT_STATUSES = {9: "par", 38: "psn", 49: "brn"}
RATTLED = 155                                   # +1 Speed, hit by a Bug, Dark or Ghost move
STALL = 100                 # moves last in its bracket; 0x51 (b, 0) in the speed pass
PRANKSTER, MYCELIUM_MIGHT = 158, 298
TARGET_CLASS = {"allAdjacent": 4, "allAdjacentFoes": 5}
# major statuses: condition id, 0xa7 code and the infliction's message (pokeldn docs/sv_raid.md, Statuses)
PAR, SLP, FRZ, BRN, PSN = 1, 2, 3, 4, 5
STATUS = {"par": (PAR, 46, 92), "slp": (SLP, 42, 103), "frz": (FRZ, 45, 97), "brn": (BRN, 44, 86),
          "psn": (PSN, 43, 79), "tox": (PSN, 43, 80)}
TOXIC_VALUE = 7801
STATUS_IMMUNE_TYPES = {PAR: {"Electric"}, BRN: {"Fire"}, FRZ: {"Ice"}, PSN: {"Poison", "Steel"}, SLP: set()}
# Showdown abilities.ts: abilities that refuse a status (refused when one would land)
STATUS_GUARDS = frozenset((7, 15, 17, 40, 41, 72, 102, 166, 175, 197, 199, 213, 257, 270, 272))
GUTS = 62
HUSTLE, THICK_FAT, STRONG_JAW, RECKLESS, TINTED_LENS = 55, 47, 173, 120, 110
SERENE_GRACE, SHIELD_DUST, COMPOUND_EYES, SKILL_LINK, STENCH = 32, 19, 14, 92, 1
# abilities that act only through a held item (a berry, an item to steal or pass on)
ITEM_ABILITIES = frozenset((82, 124, 180, 247, 291))   # Gluttony, Pickpocket, Symbiosis, Ripen, Cud Chew     # 0x8b's ninth argument; 0 for one target
EFFECTIVENESS = {0.25: 5, 0.5: 6, 1: 7, 2: 8, 4: 9}


def action_block(slot, command):
    """The 0x238-byte block: the command's (word, actor) pairs in the slot's 0x70-byte block."""
    block = bytearray(0x238)
    n = command[0x20]
    for i in range(n):
        word, actor = struct.unpack_from("<QQ", command, 0x28 + 16 * i)
        struct.pack_into("<QI", block, slot * BLOCK + ACTION * i, word, actor & 0xFFFFFFFF)
    block[COUNTS + slot] = n
    return bytes(block)


def actions(command):
    """-> [(actor battler, move, target position)] of a command's move actions."""
    out = []
    for i in range(command[0x20]):
        word, actor = struct.unpack_from("<QQ", command, 0x28 + 16 * i)
        if word & 0xF != 1:
            raise Unsupported(f"action kind {word & 0xF}")
        if word >> 25 & 1:
            raise Unsupported("a Terastallization")      # the shield's Tera percentages and the new types
        out.append((actor & 0xFFFFFFFF, (word >> 8) & 0xFFFF, (word >> 4) & 0xF))
    return out


def staged(stat, stage):
    """A stat at a stage: times (2 + stage) / 2 raised, 2 / (2 - stage) lowered."""
    return stat * (2 + stage) // 2 if stage >= 0 else stat * 2 // (2 - stage)


def modify(value, factor):
    """Showdown's chained modifier: value times factor in 4096ths, rounded half down."""
    mod = int(factor * 4096)
    return (value * mod + 2047) // 4096


class Battle:
    """What rounds need to remember: the battlers' HP, the generator, the round count."""

    def __init__(self, battlers, rng, types, tera):
        self.b = battlers
        self.rng = rng
        self.types = types          # battler -> its type names
        self.tera = tera            # the boss's Tera type name
        self.rounds = 0
        self.hp = {i: b.hp for i, b in battlers.items()}
        self.full = {i: b.stats[0] for i, b in battlers.items()}
        self.triggers = frozenset()                     # boss HP shares its profile acts at
        self.double = None                              # the double action's HP share (it acts at 0 too)
        self.stages = {i: [0] * 8 for i in battlers}     # stat stages by stat index (1 Atk ... 5 Spe, 6 acc, 7 eva)
        self.field = set()                              # "sun", "rain", "snow", "sand"
        self.terrain = None                             # "Grassy", "Misty", "Electric", "Psychic"
        self.terrain_left = 0                           # turn ends until the terrain ends
        self.fresh = set()                              # battlers revived since the last turn end
        self.charged = set()
        self.spent = {}                                 # battler -> PP its current move spent (0x05)                            # battlers Wind Power charged (their next Electric move)
        self.sides = {0: {}, 1: {}}                     # side (0 players, 1 boss) -> {condition: [turns left, setter]}
        self.weather_left = 0                           # turn ends until the weather ends (0x79's 5)
        self.weather_by = 0                             # the battler that set it (0x01's second argument)
        self.sand_hurt = set()                          # battlers the sandstorm has damaged
        self.switch_order = None                        # the battle start's speed sort (start.body)
        self.turns = 0                                  # rounds a player acted in (0x75)
        self.moved = set()                              # battlers whose move ran this round
        self.raid = None                                # raid.Raid: the boss's actions
        self.faints = {i: 0 for i in battlers}          # times each battler fainted (the revive's wait)
        self.timer_offset = 0                           # seconds the faints took off the battle timer
        self.listed = []                                # battlers revived since the last round (0x23 first)
        self.status = {}                                # battler -> [condition, value, source, toxic count]
        self.confused = {}                              # battler -> [turns of confusion left, who confused it]
        self.flinched = set()                           # battlers a flinch stops this round
        self.paced = {}                                 # battler -> its 0x51 value this round (Stall's 0)

    def slot(self, battler, number):
        """The move's slot in the battler's moveset (0x05, 0x07, 0x08); None for a move it does not know (a
        raid action's move: no 0x07 or 0x08)."""
        moves = self.b[battler].moves
        return moves.index(number) if number in moves else None if battler == BOSS else 0

    def speed(self, battler, raw=False):
        """The Speed the turn order reads: the stat at its stage, doubled by a weather's speed ability (Swift
        Swim, Chlorophyll, Sand Rush, Slush Rush), halved while paralysed."""
        spe = staged(self.b[battler].speed, self.stages[battler][5])
        if raw:
            return spe                                      # a sort's handler key: no Tailwind, no paralysis
        rush = SPEED_WEATHER.get(self.b[battler].ability) in self.field
        tail = TAILWIND in self.sides[int(battler == BOSS)]
        paralysed = self.status.get(battler, (0,))[0] == PAR
        if rush + tail + paralysed > 1:
            raise Unsupported("Speed modifiers chained")
        return modify(spe, 2) if rush or tail else modify(spe, 0.5) if paralysed else spe

    def grounded(self, b):
        """Showdown isGrounded, for the effects a raid can reach: not Flying, Levitate or an Air Balloon."""
        return "Flying" not in self.defending(b) and self.b[b].ability != LEVITATE and self.b[b].item != AIR_BALLOON

    def terrain_power(self, actor, target, move):
        """The terrain's onBasePower factor (Showdown conditions.ts): 1.3 for its type from a grounded user,
        a half for Dragon into a grounded target in Misty Terrain and Earthquake-likes in Grassy Terrain."""
        t = self.terrain
        if t and move["type"] == TERRAIN_TYPES[t] and t != "Misty" and self.grounded(actor):
            return 5325 / 4096
        if t == "Misty" and move["type"] == "Dragon" and self.grounded(target):
            return 0.5
        if t == "Grassy" and move["name"] in ("Earthquake", "Bulldoze") and self.grounded(target):
            return 0.5
        return 0

    def defending(self, target):
        return [self.tera] if target == BOSS else self.types[target]

    def effectiveness(self, move_type, target):
        from raidbattle.typechart import multiplier
        m = 1.0
        for t in self.defending(target):
            m *= multiplier(move_type, t)
        return m

    def stab(self, actor, move_type):
        if actor == BOSS and move_type == self.tera:
            return 2.0 if move_type in self.types[BOSS] else 1.5
        if move_type not in self.types[actor]:
            return 1.0
        return 2.0 if self.b[actor].ability == ADAPTABILITY and actor != BOSS else 1.5

    def tera_move(self, actor, move):
        """The boss is Terastallized: its moves of its Tera type (0x8b's eighth argument)."""
        return actor == BOSS and move["category"] != "Status" and move["type"] == self.tera

    def power(self, actor, move, power):
        """Gen 9: a Tera-type move of a Terastallized user hitting under 60 power after its base power
        modifiers hits at 60 (Showdown sim/battle-actions.ts, getDamage)."""
        if self.tera_move(actor, move) and power < 60 and move.get("priority", 0) <= 0 and "multihit" not in move:
            return 60
        return power

    def move_power(self, actor, target, move):
        """-> (base power, its onBasePower factor or 0) for a move whose power has its own rule (Showdown
        moves.ts): Payback doubled when the target moves no more this round, Hex on a statused target,
        Rising Voltage on a grounded target in Electric Terrain; Facade times 2 under a status other than
        sleep, Venoshock on a poisoned target, Electro Drift and Collision Course 5461/4096 when super
        effective, Expanding Force 1.5 in Psychic Terrain from a grounded user."""
        name, power = move["name"], move["basePower"]
        st = self.status.get(target, (0,))[0]
        if name == "Payback" and not any(e.actor == target and not e.done for e in self.entries):
            power *= 2
        elif name == "Hex" and st:
            power *= 2
        elif name == "Rising Voltage" and self.terrain == "Electric" and self.grounded(target):
            power *= 2
        mine = self.status.get(actor, (0,))[0]
        factor = {"Facade": 2 if mine and mine != SLP else 0, "Venoshock": 2 if st == PSN else 0,
                  "Electro Drift": 5461 / 4096 if self.effectiveness(move["type"], target) > 1 else 0,
                  "Collision Course": 5461 / 4096 if self.effectiveness(move["type"], target) > 1 else 0,
                  "Expanding Force": 1.5 if self.terrain == "Psychic" and self.grounded(actor) else 0}.get(name, 0)
        return power, factor

    def damage(self, actor, target, move, roll, crit):
        a, d = self.b[actor], self.b[target]
        physical = move["category"] == "Physical"
        # a critical hit ignores the user's lowered and the target's raised stages (Showdown getDamage)
        ast, dst = self.stages[actor][1 if physical else 3], self.stages[target][2 if physical else 4]
        if crit:
            ast, dst = max(ast, 0), min(dst, 0)
        att = staged(a.stats[1] if physical else a.stats[4], ast)
        dfn = staged(d.stats[2] if physical else d.stats[5], dst)
        if not physical and "sand" in self.field and "Rock" in self.defending(target):
            dfn = modify(dfn, 1.5)                          # Showdown conditions.ts: sandstorm's onModifySpD
        if a.ability in PINCH and move["type"] == PINCH[a.ability] and self.hp[actor] * 3 <= self.full[actor]:
            att = modify(att, 1.5)                          # Showdown: Overgrow, Blaze, Torrent, Swarm
        if a.ability in (HUGE_POWER, PURE_POWER) and physical:
            att = modify(att, 2)
        if a.ability == HUSTLE and physical:
            att = modify(att, 1.5)                          # Showdown abilities.ts: Hustle, on the stat
        if d.ability == THICK_FAT and move["type"] in ("Fire", "Ice") and a.ability not in MOLD_BREAKERS:
            att = modify(att, 0.5)
        power, own = self.move_power(actor, target, move)
        boosted = TYPE_BOOSTS.get(str(a.item)) == move["type"]
        ability_boost = {STRONG_JAW: 1.5 if "bite" in move["flags"] else 0,
                         RECKLESS: 4915 / 4096 if "recoil" in move else 0}.get(a.ability, 0)
        if boosted and ability_boost:
            raise Unsupported("an ability's power chained with a type item")
        if ability_boost:
            power = modify(power, ability_boost)            # Showdown abilities.ts: Strong Jaw, Reckless
        if boosted:
            power = modify(power, 4915 / 4096)              # Showdown items.ts: Charcoal, Spell Tag and kin
        if a.ability == RIVALRY and a.gender < 2 and d.gender < 2:
            if boosted:
                raise Unsupported("Rivalry chained with a type item")
            power = modify(power, 1.25 if a.gender == d.gender else 0.75)     # Showdown abilities.ts
        terrain = self.terrain_power(actor, target, move)
        if terrain:
            if boosted or ability_boost or a.ability == RIVALRY and a.gender < 2 and d.gender < 2:
                raise Unsupported("a terrain's power chained with another")
            power = modify(power, terrain)
        late = move["name"] in ("Electro Drift", "Collision Course")      # on the damage, after the type
        if own and not late:
            if boosted or ability_boost or terrain or a.ability == RIVALRY and a.gender < 2 and d.gender < 2:
                raise Unsupported("a move's power chained with another")
            power = modify(power, own)
        power = self.power(actor, move, power)
        base = (2 * a.level // 5 + 2) * power * att // dfn // 50 + 2
        if move["type"] in ("Fire", "Water") and self.field & {"sun", "rain"}:
            strong = ("sun" in self.field) == (move["type"] == "Fire")
            base = modify(base, 1.5 if strong else 0.5)     # Showdown conditions.ts: onWeatherModifyDamage
        if crit:
            base = modify(base, 1.5)
        x = base * (100 - roll) // 100
        x = modify(x, self.stab(actor, move["type"]))
        e = self.effectiveness(move["type"], target)
        x = int(x * e)
        if a.ability == TINTED_LENS and e < 1:
            x = modify(x, 2)                                # Showdown abilities.ts: Tinted Lens
        if physical and self.status.get(actor, (0,))[0] == BRN:
            if a.ability == GUTS or move["name"] == "Facade":
                raise Unsupported("Guts or Facade while burned")
            x = modify(x, 0.5)                              # Showdown getDamage: a burned user's physical move
        armor = e > 1 and (d.ability == PRISM_ARMOR or d.ability in (FILTER, SOLID_ROCK) and a.ability not in MOLD_BREAKERS)
        if armor:
            if own and late or d.ability == ICE_SCALES:
                raise Unsupported("an armor ability chained with another")
            x = modify(x, 0.75)                             # Showdown abilities.ts: Filter, Solid Rock, Prism Armor
        if own and late:
            if a.ability == TINTED_LENS and e < 1 or d.ability == ICE_SCALES:
                raise Unsupported("a move's damage chained with another")
            x = modify(x, own)
        if d.ability == ICE_SCALES and move["category"] == "Special" and a.ability not in MOLD_BREAKERS:
            if a.ability == TINTED_LENS and e < 1:
                raise Unsupported("Tinted Lens chained with Ice Scales")
            x = modify(x, 0.5)                              # Showdown abilities.ts: Ice Scales, onSourceModifyDamage
        return max(1, x)


def message(battler, text, *params):
    """Command 0xcb: battle message `text` about `battler`, its parameters ended by END."""
    args = (battler, text, *params, END)
    return queue.encode(0xCB, args + (0,) * (10 - len(args)))


def pp(battle, command, actor, number):
    """0x07 (before the move) or 0x08 (after it): the actor and the move's slot; none for a move outside
    the boss's moveset."""
    slot = battle.slot(actor, number)
    return b"" if slot is None else queue.encode(command, (actor, slot))


def plain(move):
    if move is None or move["category"] == "Status" or not move.get("basePower"):
        raise Unsupported("not a damaging move")
    if move.get("isNonstandard") in ("Past", "LGPE", "Gmax", "Future"):
        raise Unsupported(f"{move['name']} is not a Scarlet / Violet move")   # its game data differs
    for key in ("self", "volatileStatus", "status", "boosts"):
        if key in move:
            raise Unsupported(f"a move with {key}")
    if set(move["callbacks"]) - IDLE_MOVE_CALLBACKS.get(move["name"], set()):
        raise Unsupported(f"{move['name']}'s {move['callbacks'][0]}")
    # "any": one target, any position; a spread move hits only the commanded position in a raid
    if move["target"] not in ("normal", "any", "allAdjacent", "allAdjacentFoes"):
        raise Unsupported(f"target {move['target']}")
    if move.get("critRatio", 1) not in CRIT_DRAW:
        raise Unsupported("crit stage")
    for sec in secondaries(move):
        if set(sec) - {"chance", "status", "volatileStatus", "boosts"} or "chance" not in sec or len(sec) == 1:
            raise Unsupported("secondary")
    return move


def secondaries(move):
    return move.get("secondaries") or ([move["secondary"]] if move.get("secondary") else [])


def use(battle, actor, number, position):
    """-> the queue for one move use."""
    if (MOVES.get(number) or {}).get("category") == "Status":
        return status_use(battle, actor, number, position)
    move = plain(MOVES.get(number))
    if number in UNSEEN_MOVES:
        raise Unsupported(f"move {number} was never probed")
    target = BATTLER_AT[position]
    r = battle.rng
    if not battle.hp[target]:
        return immune(battle, actor, target, number, move, position, gone=True)
    if actor in battle.charged and move["type"] == "Electric":
        raise Unsupported("a charged battler's Electric move")
    if "sand" in battle.field and move["name"] in SAND_MOVES:
        raise Unsupported("a move the weather changes")
    if battle.effectiveness(move["type"], target) == 0:
        return immune(battle, actor, target, number, move, position)
    if move["type"] == "Ground" and battle.b[target].ability == LEVITATE:
        if battle.b[actor].ability in MOLD_BREAKERS:
            raise Unsupported("a Ground move into Levitate under Mold Breaker")
        return immune(battle, actor, target, number, move, position, levitate=True)
    if type(move["accuracy"]) is int and not r.chance(accuracy(battle, actor, move, target)):
        return immune(battle, actor, target, number, move, position, missed=True)
    hits = move.get("multihit", 1)
    if hits == [2, 5]:
        x = r.percent()                                     # 0x19d4f2c: one roll below 100, drawn under Skill Link too
        hits = 5 if battle.b[actor].ability == SKILL_LINK else 2 if x < 35 else 3 if x < 70 else 4 if x < 85 else 5
    if not isinstance(hits, int):
        raise Unsupported(f"multihit {hits}")
    e = battle.effectiveness(move["type"], target)
    if move["type"] == "Ground" and battle.b[target].item == AIR_BALLOON:
        raise Unsupported("a Ground move into an Air Balloon")
    if e not in EFFECTIVENESS:
        raise Unsupported(f"effectiveness {e}")
    code = EFFECTIVENESS[e]
    mtype, cat = TYPES.index(move["type"]), 1 if move["category"] == "Physical" else 2
    apos, tpos = POSITION[actor], POSITION[target]
    q = b""
    if actor != BOSS:
        q += queue.encode(0x05, (actor, battle.slot(actor, number), battle.spent.get(actor, 1)))
    q += pp(battle, 0x07, actor, number)
    q += queue.encode(0xC9, (actor, 0, number, tpos, 0))
    q += queue.encode(0x7B, (number, battle.rounds, actor))
    for size in (20, 5, 5, 5, 19):
        q += queue.encode_group(0xCF, bytes(size))
    total, parts = 0, []
    for i in range(hits):
        part, dmg, knockout, faint = strike(battle, actor, target, number, move, code, i, hits)
        parts.append(part)
        total += dmg
        if knockout or faint:
            break
    done = len(parts)
    for head, record, tail in parts:                        # each record carries the hits that landed
        q += queue.encode_group(0xCF, bytes(20)) + head
        q += queue.encode(0x8B, record[:9] + (done if hits > 1 else 0,)) + tail
    if hits > 1:
        if code != 7:
            q += queue.encode(0xCA, (actor, 574 if code > 7 else 575, END) + (0,) * 7)
        if move["name"] != "Dragon Darts":                  # Dragon Darts shows no hit count
            q += queue.encode(0xCA, (actor, 516, done, END) + (0,) * 6)
        if code > 7:
            q += queue.encode(0x20, (actor, 24)) * done
        q += queue.encode(0xA6, (96,))
        if knockout:
            q += message(actor, 0, target)                  # the boss's fainted message, after the hit count
    if "recoil" in move and battle.b[actor].ability != ROCK_HEAD:
        q += recoil(battle, actor, move, total, knockout or faint)
    q += queue.encode(0x2E, (2, actor - 1))
    if target == BOSS:
        q += queue.encode(0x85, (7, total))
    q += queue.encode(0x7C, ())
    q += pp(battle, 0x08, actor, number)
    q += queue.encode(0x1D, (actor, tpos, mtype, 1, 0, number, number))
    q += queue.encode(0x5B, (actor, number)) * 2
    q += queue.encode(0x1E, (actor, 0))
    return q


def accuracy(battle, actor, move, target):
    """The accuracy a move draws against: its user's accuracy stage less the target's evasion stage (times
    (3 + n) / 3 raised, 3 / (3 - n) lowered), then Hustle's 3277/4096 on a physical move, Compound Eyes' 5325/4096,
    Sand Veil's or Snow Cloak's 3277/4096 in their weather on the target."""
    acc = move["accuracy"]
    a = battle.b[actor].ability
    boost = max(-6, min(6, battle.stages[actor][6] - battle.stages[target][7]))
    if boost and ({a, battle.b[target].ability} & {51, 109, 300} or move["name"] in ("Chip Away", "Sacred Sword", "Darkest Lariat")):
        raise Unsupported("a stage beside Keen Eye, Unaware, Mind's Eye or a move ignoring evasion")
    if boost > 0:
        acc = acc * (3 + boost) // 3                        # Showdown hitStepAccuracy: the stages first
    elif boost < 0:
        acc = acc * 3 // (3 - boost)
    evades = EVADE_WEATHER.get(battle.b[target].ability) in battle.field and a not in MOLD_BREAKERS
    if evades and (a == COMPOUND_EYES or a == HUSTLE and move["category"] == "Physical"):
        raise Unsupported("an accuracy ability chained with an evasion ability")
    if a == HUSTLE and move["category"] == "Physical":
        acc = modify(acc, 3277 / 4096)
    elif a == COMPOUND_EYES:
        acc = modify(acc, 5325 / 4096)
    elif evades:
        acc = modify(acc, 3277 / 4096)
    return min(acc, 100)


def strike(battle, actor, target, number, move, code, i, hits):
    """-> ((the queue of hit i of `hits` before its 0x8b, the 0x8b's arguments, the queue after it), its
    damage, whether it knocked the boss out, a player out): the hit's flags (0x7e), record (0x8b, the hit
    index; the caller writes the hits that landed), damage, messages, record (0x42), its effects and 0xd1."""
    r = battle.rng
    multi = hits > 1
    if multi and (secondaries(move) or "drain" in move or battle.b[target].ability in CONTACT_STATUS
                  or battle.b[actor].ability == POISON_TOUCH and "contact" in move["flags"]
                  or battle.b[target].item == AIR_BALLOON or battle.b[target].ability in (RATTLED, SAND_SPIT)):
        raise Unsupported("a multi-hit move with an effect")
    # Battle Armor and Shell Armor (Showdown onCriticalHit false): no critical-hit draw
    crit = battle.b[target].ability not in CRIT_GUARD and r.below(CRIT_DRAW[move.get("critRatio", 1)]) == 0
    roll = r.below(16)
    dmg = battle.damage(actor, target, move, roll, crit)
    if target == BOSS:
        dmg = battle.raid.damage(dmg)
    if dmg >= battle.hp[target] == battle.full[target] and (battle.b[target].ability == STURDY or
                                                           battle.b[target].item == FOCUS_SASH):
        raise Unsupported("Sturdy or Focus Sash")
    dmg = min(dmg, battle.hp[target])
    if battle.b[target].ability == SHIELDS_DOWN and 2 * (battle.hp[target] - dmg) <= battle.full[target]:
        raise Unsupported("Shields Down at half HP")
    knockout = target == BOSS and dmg == battle.hp[target]
    faint = target != BOSS and dmg == battle.hp[target]
    if faint and (battle.b[target].item == AIR_BALLOON or battle.b[target].ability in (RATTLED, SAND_SPIT)):
        raise Unsupported("a knockout beside an item or ability that answers the hit")
    if knockout or faint:
        r.chance(0)                                         # drawn by every hit that knocks a battler out
    drops = b""
    secs = secondaries(move)
    if battle.b[actor].ability == STENCH and not any(x.get("volatileStatus") == "flinch" for x in secs):
        secs = [{"chance": 10, "volatileStatus": "flinch"}] + secs     # drawn before the move's own
    if battle.b[target].ability == SHIELD_DUST and battle.b[actor].ability not in MOLD_BREAKERS:
        secs = []
    if battle.b[actor].ability == SERENE_GRACE:
        secs = [dict(x, chance=x["chance"] * 2) for x in secs]
    for sec in secs if not knockout else ():               # a knocked-out boss draws none
        guarded = battle.b[target].ability == INNER_FOCUS and battle.b[actor].ability not in MOLD_BREAKERS
        if sec.get("volatileStatus") == "flinch" and (target == BOSS or guarded):
            continue                                        # the boss, or Inner Focus, cannot flinch: no draw
        if faint and set(sec) == {"chance", "boosts"}:
            continue                                        # a stat drop on a fainted player: no draw
        if faint and "status" in sec and sec["status"] == "slp":
            raise Unsupported("a sleep secondary on a fainted player")
        turns = 0
        if sec.get("volatileStatus") == "confusion":
            turns = 2 + r.duration(4)                       # the duration, drawn before the chance
        elif sec.get("status") == "slp":
            turns = 2 + r.duration(3)
        if r.chance(sec["chance"]) and not faint:          # a fainted player draws a flinch or confusion
            if sec.get("volatileStatus") == "flinch":
                if target not in battle.moved:
                    battle.flinched.add(target)             # stops its move this round
                continue                                    # a target that already moved: nothing shows
            if "status" in sec and set(sec) == {"chance", "status"} and not knockout:
                drops += inflict(battle, actor, target, sec["status"], turns)
                continue
            if sec.get("volatileStatus") == "confusion" and set(sec) == {"chance", "volatileStatus"} and not knockout:
                drops += confuse(battle, actor, target, turns)
                continue
            if set(sec) != {"chance", "boosts"} or knockout:
                raise Unsupported("a secondary effect")
            drops += stat_drop(battle, actor, target, sec["boosts"])
    contact = b""
    attract = battle.b[target].ability != CUTE_CHARM or battle.b[actor].gender + battle.b[target].gender == 1
    if "contact" in move["flags"] and not knockout and (battle.b[target].ability in CONTACT_STATUS and attract or
                                                        battle.b[actor].ability == POISON_TOUCH):
        if r.chance(30):                                    # Showdown: randomChance(3, 10) on contact, after the secondaries
            if battle.b[actor].ability == POISON_TOUCH or battle.b[target].ability == CUTE_CHARM:
                raise Unsupported("a contact ability's status")
            landed = inflict(battle, target, actor, CONTACT_STATUSES[battle.b[target].ability])
            if landed:                                      # inside the target's ability activation
                contact = queue.encode(0x25, (target,)) + queue.encode(0xC7, (target, 0)) + landed + queue.encode(0xC8, (target,))
    battle.hp[target] -= dmg
    mtype, cat = TYPES.index(move["type"]), 1 if move["category"] == "Physical" else 2
    apos, tpos = POSITION[actor], POSITION[target]
    e5 = [7] * 5
    e5[tpos] = code
    hit = [0] * 5
    hit[tpos] = 1
    head = queue.encode(0x7E, (0, *hit))
    head += queue.encode(0x7E, (1, *[int(crit) * h for h in hit]))
    head += queue.encode(0x7E, (2, *e5))
    doubled = int(move["name"] == "Rising Voltage" and battle.move_power(actor, target, move)[0] != move["basePower"])
    record = (apos, tpos, number, mtype, doubled, i, 1, int(battle.tera_move(actor, move)), TARGET_CLASS.get(move["target"], 0), 0)
    q = b""
    if crit:
        q += queue.encode(0x37, (actor, 0, 1))
    q += queue.encode(0x37, (target, 2, dmg)) + queue.encode(0x37, (target, 5, 1))
    q += queue.encode(0x02, (target, actor, dmg, 3))
    q += queue.encode(0xD0, bytes([target, code]))
    if code == 7:
        q += queue.encode(0x8E, (1, 1, number))
    else:
        weak = code > 7
        q += queue.encode(0x8E, (1, 2 if weak else 3, number))
        if not multi:
            q += queue.encode(0xCA, (actor, 574 if weak else 575, END) + (0,) * 7)
    if code > 7 and not multi:
        q += queue.encode(0x20, (actor, 24))
    if crit:
        q += queue.encode(0xA7, (tpos, 131)) + queue.encode(0x20, (actor, 26))
    q += queue.encode(0x42, (target, actor, apos, mtype, cat, number, dmg))
    if battle.b[target].ability == SAND_SPIT:
        if knockout or drops or battle.b[target].item in (AIR_BALLOON, SMOOTH_ROCK) or battle.b[target].ability == RATTLED:
            raise Unsupported("Sand Spit beside another effect")
        q += sand_spit(battle, target)
    if battle.b[target].item == AIR_BALLOON and not (target == BOSS and knockout):
        if drops:
            raise Unsupported("an Air Balloon popped with a stat drop")
        battle.b[target].item = 0                           # popped: message 138, then the item leaves
        q += message(target, 138, target) + queue.encode(0x1E, (target, 15)) + queue.encode(0x26, (target, 0))
        q += queue.encode(0x4F, (target, 0)) + queue.encode(0x62, (target,))
    if battle.b[target].ability == RATTLED and move["type"] in ("Bug", "Dark", "Ghost") and not knockout:
        if drops or battle.stages[target][5] == 6:
            raise Unsupported("Rattled with a stat drop or at +6")
        battle.stages[target][5] += 1
        q += queue.encode(0x25, (target,)) + queue.encode(0xC7, (target, 0)) + queue.encode(0x0C, (target, 5, 1))
        q += queue.encode(0x92, (target, 5, 1, 0)) + message(target, 15, target) + queue.encode(0xC8, (target,))
    q += drops + contact
    if "drain" in move:
        n, d = move["drain"]
        heal = int(dmg * n / d + 0.5)                       # the commands carry it uncapped
        if battle.hp[actor] < battle.full[actor] and heal > 0:
            battle.hp[actor] = min(battle.full[actor], battle.hp[actor] + heal)
            q += queue.encode(0xA7, (POSITION[actor], 51)) + queue.encode(0x03, (actor, heal))
            q += queue.encode(0x9A, (actor, heal)) + message(actor, 290, target)
    if knockout:
        q += boss_down(battle, actor, number, quiet=multi)
    elif faint:
        q += player_down(battle, target, actor, number, quiet=multi)
    q += queue.encode(0xD1, bytes([1, 0]))
    if move["type"] == "Fire" and battle.hp[target] and battle.status.get(target, (0,))[0] == FRZ:
        del battle.status[target]                           # a Fire hit thaws its target
        q += queue.encode(0x14, (target,)) + queue.encode(0x90, (target, 0)) + message(target, 99, target)
    return (head, record, q), dmg, knockout, faint


def sand_spit(battle, b):
    """Sand Spit (Showdown abilities.ts): hit by a damaging move, it starts a sandstorm for 5 turns, with
    the start weather's commands and no message."""
    if battle.field & {"sun", "rain", "snow", "sand"}:
        raise Unsupported("Sand Spit with a weather up")
    if any(WEATHER_ABILITIES.get(x.ability, set()) & {"sand"} for x in battle.b.values() if x.ability not in WEATHER_HANDLED):
        raise Unsupported("an ability reads the weather")
    battle.field.add("sand")
    battle.weather_left, battle.weather_by = WEATHER_TURNS, b
    q = queue.encode(0x6A, (0,)) + queue.encode(0x69, (0, 4)) + queue.encode(0x79, (4, 5, 0, b, 0))
    q += queue.encode(0x88, (4, b, 0))
    return queue.encode(0x25, (b,)) + queue.encode(0xC7, (b, 0)) + q + queue.encode(0xC8, (b,))


def recoil(battle, actor, move, dmg, knockout):
    """Recoil: damage times the move's fraction, rounded half up, at least 1; 0x01 (A, A, r, 4),
    0x9a (A, -r), message 127, 0x37 (A, 4, r)."""
    n, d = move["recoil"]
    r = max(1, int(dmg * n / d + 0.5))
    if knockout or r >= battle.hp[actor] or battle.b[actor].ability == MAGIC_GUARD:
        raise Unsupported("recoil that faints, after a knockout, or under Rock Head or Magic Guard")
    battle.hp[actor] -= r
    q = queue.encode(0x01, (actor, actor, r, 4)) + queue.encode(0x9A, (actor, -r & 0xFFFFFFFF))
    return q + message(actor, 127, actor) + queue.encode(0x37, (actor, 4, r))


def immune(battle, actor, target, number, move, position, missed=False, floor=False, levitate=False, gone=False):
    """A damaging move the target's types are immune to (no draw), or one that missed: five zero groups,
    message 72 and 0x52 (A, 3), or message 73 and 0x52 (A, 1); a stat-dropping move into stats all at -6
    (`floor`, no draw): message 60 alone; a Ground move into Levitate (no draw): message 72 about the target
    inside its ability's activation, 0x25 (T), 0xc7 (T, 0) ... 0xc8 (T); a target fainted since the move was
    aimed (`gone`): 0xca (A, 567) and no 0x08."""
    mtype = TYPES.index(move["type"])
    q = b""
    if actor != BOSS:
        q += queue.encode(0x05, (actor, battle.slot(actor, number), battle.spent.get(actor, 1)))
    q += pp(battle, 0x07, actor, number) + queue.encode(0xC9, (actor, 0, number, position, 1))
    q += queue.encode(0x7B, (number, battle.rounds, actor))
    for size in (20, 5, 5, 5, 19):
        q += queue.encode_group(0xCF, bytes(size))
    if gone:
        q += queue.encode(0xCA, (actor, 567, END) + (0,) * 7)
    elif floor:
        q += message(actor, 60, target)
    elif levitate:
        q += queue.encode(0x25, (target,)) + queue.encode(0xC7, (target, 0)) + message(target, 72, target)
        q += queue.encode(0xC8, (target,)) + queue.encode(0x52, (actor, 3))
    else:
        q += message(actor, 73 if missed else 72, target) + queue.encode(0x52, (actor, 1 if missed else 3))
    q += pp(battle, 0x08, actor, number)
    q += queue.encode(0x52, (actor, 0)) + queue.encode(0x1D, (actor, position, mtype, 0, 0, number, number))
    q += queue.encode(0x5B, (actor, number)) * 2 + queue.encode(0x1E, (actor, 0))
    return q


RAISE_TEXT, DROP_TEXT = {1: 10, 2: 17, 3: 24}, {1: 31, 2: 38}    # + stat: the stat change's message


WEATHER_MOVES = {"Sunny Day": ("sun", 1), "Rain Dance": ("rain", 2), "Snowscape": ("snow", 3), "Sandstorm": ("sand", 4)}


def status_move(battle, move):
    """A status move whose only effect is stat stages on its user or one target, a major status on one
    target, or a weather."""
    if move.get("isNonstandard") in ("Past", "LGPE", "Gmax", "Future"):
        raise Unsupported(f"{move['name']} is not a Scarlet / Violet move")
    if move["name"] in WEATHER_MOVES and move["callbacks"] == ["weather"]:
        return move
    if move["name"].split()[0] in TERRAINS and move["callbacks"] == ["condition", "terrain"]:
        return move
    if move["name"] == "Tailwind":
        return move
    if move.get("status") in STATUS and not any(k in move for k in ("self", "volatileStatus", "boosts",
                                                                      "secondary", "secondaries")):
        if set(move["callbacks"]) - {"ignoreImmunity"} or move["target"] != "normal":
            raise Unsupported(f"{move['name']}'s {(move['callbacks'] or [move['target']])[0]}")
        return move
    if not move.get("boosts") or any(k in move for k in ("self", "volatileStatus", "status", "secondary",
                                                          "secondaries", "multihit")):
        raise Unsupported(f"not a damaging move: {move['name']}")
    if set(move["callbacks"]) - ({"onModifyMove"} if move["name"] == "Growth" else set()):
        raise Unsupported(f"{move['name']}'s {move['callbacks'][0]}")
    if move["name"] == "Growth" and battle.field & {"sun"}:
        raise Unsupported("Growth in the sun")
    if move["target"] not in ("self", "normal", "any", "allAdjacentFoes"):
        raise Unsupported(f"target {move['target']}")
    return move


# Showdown conditions.ts: a terrain's boosted type; its 0x32 / 0xaa code and start and end messages
TERRAIN_TYPES = {"Grassy": "Grass", "Misty": "Fairy", "Electric": "Electric", "Psychic": "Psychic"}
TERRAINS = {"Grassy": (1, 704, 705), "Misty": (2, 706, 707), "Electric": (3, 708, 709), "Psychic": (4, 828, 829)}
TERRAIN_TURNS = 5
# abilities and items that read the terrain: Grass Pelt, Surge Surfer, Mimicry, Quark Drive, Hadron Engine;
# the four seeds and Terrain Extender
TERRAIN_READERS = frozenset({179, 207, 250, 282, 289})
TERRAIN_ITEMS = frozenset({881, 882, 883, 884, 896})


def terrain_start(battle, name, b):
    """A terrain raised by battler b: 0x32 (t, 0, 42, b), 0x6a (8), 0xb2 (0), 0xaa (t), 0x69 (8, t), then
    its start message (0xca) about b."""
    if battle.terrain:
        raise Unsupported("a terrain over a terrain")
    if any(x.ability in TERRAIN_READERS or x.item in TERRAIN_ITEMS for x in battle.b.values()):
        raise Unsupported("an ability or item reads the terrain")
    t, text, _ = TERRAINS[name]
    battle.terrain, battle.terrain_left = name, TERRAIN_TURNS
    q = queue.encode(0x32, (t, 0, 42, b)) + queue.encode(0x6A, (8,)) + queue.encode(0xB2, (0,))
    q += queue.encode(0xAA, (t,)) + queue.encode(0x69, (8, t))
    return q + queue.encode(0xCA, (b, text, END) + (0,) * 7)


def terrain_end(battle):
    """A terrain's fifth turn end, between 0x44 (8) and 0x44 (9): 0x34 (8), 0x6a (8), its end message
    about battler 0, 0x32 (0, 0, 1, 0), 0x6a (8), 0xb2 (0), 0xaa (0), 0x69 (8, 0)."""
    if not battle.terrain:
        return b""
    battle.terrain_left -= 1
    if battle.terrain_left:
        return b""
    if battle.terrain == "Misty":
        raise Unsupported("Misty Terrain ends")         # its end message is not in the corpus
    text = TERRAINS[battle.terrain][2]
    battle.terrain = None
    q = queue.encode(0x34, (8,)) + queue.encode(0x6A, (8,)) + queue.encode(0xCA, (0, text, END) + (0,) * 7)
    q += queue.encode(0x32, (0, 0, 1, 0)) + queue.encode(0x6A, (8,)) + queue.encode(0xB2, (0,))
    return q + queue.encode(0xAA, (0,)) + queue.encode(0x69, (8, 0))


TAILWIND = 4                # a side condition's id in 0x4a, 0x4c, 0x4b, 0x66
SIDE_TURNS = {TAILWIND: 4}
SIDE_TEXT = {TAILWIND: (643, 645)}      # start, end


WIND_RIDER, WIND_POWER = 274, 277


def side_start(battle, b, cond):
    """A side condition raised by battler b on its side: 0x4a and 0x65 (side, cond, 0, 34, b), 0xca (b, start
    text, side)."""
    side = int(b == BOSS)
    mine = [i for i in sorted(battle.b) if int(i == BOSS) == side and battle.hp[i]]
    if cond == TAILWIND and any(battle.b[i].ability == WIND_RIDER for i in mine):
        raise Unsupported("Tailwind beside Wind Rider")
    if cond in battle.sides[side]:
        raise Unsupported("a side condition already up")
    battle.sides[side][cond] = [SIDE_TURNS[cond], b]
    q = queue.encode(0x4A, (side, cond, 0, 34, b)) + queue.encode(0x65, (side, cond, 0, 34, b))
    q += queue.encode(0xCA, (b, SIDE_TEXT[cond][0], side, END) + (0,) * 6)
    for i in mine if cond == TAILWIND else ():
        if battle.b[i].ability == WIND_POWER:               # charged by its side's Tailwind: condition 20
            battle.charged.add(i)
            q += queue.encode(0x25, (i,)) + queue.encode(0xC7, (i, 0)) + message(i, 1024, i, 366)
            q += queue.encode(0xC8, (i,)) + queue.encode(0x1E, (i, 20)) + queue.encode(0x7D, (20, i, 0, 0))
    return q


def side_end(battle):
    """At a turn's end, after the residual kinds: 0x4c (side, cond) for each side condition up; at its last
    turn 0x4b and 0x66 (side, cond) and 0xca (the battler that raised it, end text, side)."""
    up = [(side, cond) for side in (0, 1) for cond in battle.sides[side]]
    if len(up) > 1:
        raise Unsupported("two side conditions at a turn's end")
    q = b""
    for side, cond in up:
        c = battle.sides[side][cond]
        q += queue.encode(0x4C, (side, cond))
        c[0] -= 1
        if not c[0]:
            del battle.sides[side][cond]
            q += queue.encode(0x4B, (side, cond)) + queue.encode(0x66, (side, cond))
            q += queue.encode(0xCA, (c[1], SIDE_TEXT[cond][1], side, END) + (0,) * 6)
    return q


def weather_start(battle, name, w, b):
    """A weather raised by battler b: 0x6a (0), 0x69 (0, w), 0x79 (w, 5, 0, b, 0), 0x88 (w, b, 0)."""
    if battle.field & {"sun", "rain", "snow", "sand"}:
        raise Unsupported("a weather over another")
    if any(WEATHER_ABILITIES.get(x.ability, set()) & {name} for x in battle.b.values() if x.ability not in WEATHER_HANDLED):
        raise Unsupported("an ability reads the weather")
    if battle.b[b].item in (SMOOTH_ROCK, 284, 285, 259):         # Smooth Rock, Heat Rock, Damp Rock, Icy Rock
        raise Unsupported("a weather rock")
    battle.field.add(name)
    battle.weather_left, battle.weather_by = WEATHER_TURNS, b
    q = queue.encode(0x6A, (0,)) + queue.encode(0x69, (0, w)) + queue.encode(0x79, (w, 5, 0, b, 0))
    return q + queue.encode(0x88, (w, b, 0))


def weather_use(battle, actor, number, position, move):
    """A weather or terrain move: no draw, one zero group, the hit record with the field class (10), the
    weather or terrain."""
    apos = POSITION[actor]
    q = b""
    if actor != BOSS:
        q += queue.encode(0x05, (actor, battle.slot(actor, number), battle.spent.get(actor, 1)))
    q += pp(battle, 0x07, actor, number)
    q += queue.encode(0xC9, (actor, 0, number, position, 0))
    q += queue.encode(0x7B, (number, battle.rounds, actor))
    q += queue.encode_group(0xCF, bytes(20))
    q += queue.encode(0x7E, (0, 0, 0, 0, 0, 0)) + queue.encode(0x7E, (1, 0, 0, 0, 0, 0))
    q += queue.encode(0x7E, (2, 7, 7, 7, 7, 7))
    side = move["name"] == "Tailwind"
    q += queue.encode(0x8B, (apos, 10 if side else position, number, TYPES.index(move["type"]), 0, 0, 0, 0, 12 if side else 10, 0))
    if side:
        q += side_start(battle, actor, TAILWIND)
    elif move["name"] in WEATHER_MOVES:
        q += weather_start(battle, *WEATHER_MOVES[move["name"]], actor)
    else:
        q += terrain_start(battle, move["name"].split()[0], actor)
    q += queue.encode(0x7C, ())
    q += pp(battle, 0x08, actor, number)
    q += queue.encode(0x1D, (actor, position, TYPES.index(move["type"]), 1, 0, number, number))
    q += queue.encode(0x5B, (actor, number)) * 2
    q += queue.encode(0x1E, (actor, 0))
    return q


def raise_stats(battle, b, boosts):
    """A move's raise of its user's stages: 0x0c, 0x92, then message RAISE_TEXT + stat per stat."""
    x = battle.b[b]
    if set(ABILITIES.get(str(x.ability), ["unknown"])) & BOOST_ANSWERS or x.item not in (0, *IDLE_ITEMS) and \
            set(ITEMS.get(str(x.item), ["unknown"])) & (BOOST_ANSWERS | {"onUpdate"}):
        raise Unsupported(f"battler {b}'s ability {x.ability} or item {x.item} answers a stat raise")
    q = b""
    for key, n in ordered(boosts):
        stat = STATS[key]
        if n not in RAISE_TEXT or battle.stages[b][stat] + n > 6:
            raise Unsupported("a stat raise past +6 or of more than 3 stages")
        battle.stages[b][stat] += n
        q += queue.encode(0x0C, (b, stat, n)) + queue.encode(0x92, (b, stat, n, 0)) + message(b, RAISE_TEXT[n] + stat, b)
    return q


def shielded(battle, actor, number, position, move):
    """A status move into the shielded boss fails before it runs (120 of 120 stat-drop and status moves in
    the corpora): 0xc9 (A, 0, M, P, 1), 0xca (A, 567, A), 0x52 (A, 0), 0x1d with no hit, 0x5b twice, 0x1e."""
    q = b""
    if actor != BOSS:
        q += queue.encode(0x05, (actor, battle.slot(actor, number), battle.spent.get(actor, 1)))
    q += pp(battle, 0x07, actor, number) + queue.encode(0xC9, (actor, 0, number, position, 1))
    q += queue.encode(0xCA, (actor, 567, actor, END) + (0,) * 6) + queue.encode(0x52, (actor, 0))
    q += queue.encode(0x1D, (actor, position, TYPES.index(move["type"]), 0, 0, number, number))
    return q + queue.encode(0x5B, (actor, number)) * 2 + queue.encode(0x1E, (actor, 0))


def status_use(battle, actor, number, position):
    """-> the queue for a stat-stage status move: one zero group, no hit, the hit record with the
    move's target class, the stat changes."""
    move = status_move(battle, MOVES[number])
    if number in UNSEEN_MOVES:
        raise Unsupported(f"move {number} was never probed")
    if move["name"] in WEATHER_MOVES or move["name"].split()[0] in TERRAINS or move["name"] == "Tailwind":
        return weather_use(battle, actor, number, position, move)
    own = move["target"] == "self"
    target = actor if own else BATTLER_AT[position]
    if not own and (actor == BOSS) == (target == BOSS):
        raise Unsupported("a stat move on an ally")
    if move.get("status"):
        cond = STATUS[move["status"]][0]
        if battle.status.get(target) or STATUS_IMMUNE_TYPES[cond] & set(battle.defending(target)) or \
                battle.effectiveness(move["type"], target) == 0 and move["name"] == "Thunder Wave":
            raise Unsupported("a status move that fails")
    if not own and "powder" in move["flags"] and "Grass" in battle.defending(target):
        raise Unsupported("a powder move on a Grass type")
    if not own and battle.b[actor].ability == PRANKSTER and "Dark" in battle.defending(target):
        raise Unsupported("Prankster's move on a Dark type")
    if not own and target == BOSS and battle.raid.state == 1:
        return shielded(battle, actor, number, position, move)
    if not own and not move.get("status") and all(battle.stages[target][STATS[k]] == -6 for k in move["boosts"]):
        if any(d >= 0 for d in move["boosts"].values()):
            raise Unsupported("a raise on a foe")
        stat_drop(battle, actor, target, {})                    # what answers a drop still refuses
        return immune(battle, actor, target, number, move, position, floor=True)
    r = battle.rng
    if type(move["accuracy"]) is int:
        if not r.chance(accuracy(battle, actor, move, target) if not own else move["accuracy"]):
            raise Unsupported("a miss")
    apos, tpos = POSITION[actor], POSITION[target]
    q = b""
    if actor != BOSS:
        q += queue.encode(0x05, (actor, battle.slot(actor, number), battle.spent.get(actor, 1)))
    q += pp(battle, 0x07, actor, number)
    q += queue.encode(0xC9, (actor, 0, number, position, 0))
    q += queue.encode(0x7B, (number, battle.rounds, actor))
    q += queue.encode_group(0xCF, bytes(20))
    q += queue.encode(0x7E, (0, 0, 0, 0, 0, 0)) + queue.encode(0x7E, (1, 0, 0, 0, 0, 0))
    q += queue.encode(0x7E, (2, 7, 7, 7, 7, 7))
    q += queue.encode(0x8B, (apos, tpos, number, TYPES.index(move["type"]), 0, 0, 0, 0,
                             7 if own else TARGET_CLASS.get(move["target"], 0), 0))
    if move.get("status"):
        turns = 2 + r.duration(3) if move["status"] == "slp" else 0
        q += inflict(battle, actor, target, move["status"], turns)
    elif own:
        q += raise_stats(battle, actor, move["boosts"])
    else:
        q += stat_drop(battle, actor, target, move["boosts"])
    q += queue.encode(0x7C, ())
    q += pp(battle, 0x08, actor, number)
    q += queue.encode(0x1D, (actor, position, TYPES.index(move["type"]), 1, 0, number, number))
    q += queue.encode(0x5B, (actor, number)) * 2
    q += queue.encode(0x1E, (actor, 0))
    return q


STATS = {"atk": 1, "def": 2, "spa": 3, "spd": 4, "spe": 5, "accuracy": 6, "evasion": 7}
def ordered(boosts):
    """A move's stat changes in the order the game applies them: moves.json sorts them by name, the game keeps
    Showdown's source order, which is the stat order but for Shift Gear's (Speed, then Attack)."""
    keys = tuple(sorted(boosts, key=STATS.get))
    if keys == ("atk", "spe") and boosts == {"atk": 1, "spe": 2}:
        keys = ("spe", "atk")                               # Shift Gear: Speed first (Showdown's order)
    elif len(keys) == 5 and len(set(boosts.values())) > 1:
        raise Unsupported("Shell Smash's stat order")
    return [(k, boosts[k]) for k in keys]
BOOST_ANSWERS = {"onTryBoost", "onChangeBoost", "onAfterBoost", "onAfterEachBoost", "onFoeAfterBoost"}
# Showdown abilities.ts: onTryBoost that blocks only Intimidate, or guards one stat
INTIMIDATE_ONLY = frozenset({12, 20, 39, 113, 275})        # Oblivious, Own Tempo, Inner Focus, Scrappy, Guard Dog
STAT_GUARD = {51: 6, 52: 1, 145: 2}                         # Keen Eye, Hyper Cutter, Big Pecks


def stat_drop(battle, actor, target, boosts):
    """A secondary's stat drop on the target: 0x0d and 0x93 (target, stat, stages), then message 31 +
    stat for one stage, 38 + stat for two, from the attacker."""
    b = battle.b[target]
    item = set() if b.item in (0, *IDLE_ITEMS) else set(ITEMS.get(str(b.item), ["unknown"]))
    ability = set() if b.ability in INTIMIDATE_ONLY | set(STAT_GUARD) else set(ABILITIES.get(str(b.ability), ["unknown"]))
    if ability & BOOST_ANSWERS or item & (BOOST_ANSWERS | {"onUpdate"}):
        raise Unsupported(f"battler {target}'s ability {b.ability} or item {b.item} answers a stat drop")
    q = b""
    for key, delta in ordered(boosts):
        stat, n = STATS[key], -delta
        if STAT_GUARD.get(b.ability) == stat:
            raise Unsupported(f"battler {target}'s ability {b.ability} guards stat {stat}")
        if n not in (1, 2) or battle.stages[target][stat] - n < -6:
            raise Unsupported("a stat drop past -6 or not 1 or 2 stages")
        battle.stages[target][stat] -= n
        q += queue.encode(0x0D, (target, stat, n)) + queue.encode(0x93, (target, stat, n, 0))
        q += message(actor, (31 if n == 1 else 38) + stat, target, stat)
    return q


def inflict(battle, actor, target, name, turns=0):
    """A major status landing: 0x13 (T, condition, 0, value, A), 0x90 (T, condition), 0xa7 (T's position,
    code), the message from the user; nothing on a target already statused or immune by its types."""
    cond, code, text = STATUS[name]
    if battle.status.get(target) or STATUS_IMMUNE_TYPES[cond] & set(battle.defending(target)):
        return b""
    if battle.b[target].ability in STATUS_GUARDS:
        raise Unsupported(f"battler {target}'s ability {battle.b[target].ability} against a status")
    if name == "frz" and "sun" in battle.field:
        raise Unsupported("a freeze in the sun")
    if (battle.terrain == "Misty" or battle.terrain == "Electric" and name == "slp") and battle.grounded(target):
        raise Unsupported("a status the terrain blocks")
    value = TOXIC_VALUE if name == "tox" else turns << 3 | 2 if name == "slp" else 1
    battle.status[target] = [cond, value, actor, 0, turns, name == "tox"]
    q = queue.encode(0x13, (target, cond, 0, value, actor)) + queue.encode(0x90, (target, cond))
    return q + queue.encode(0xA7, (POSITION[target], code)) + message(actor, text, target)


def confuse(battle, actor, target, turns):
    """Confusion landing: 0x13 (T, 6, 0, turns << 3 | 2, A), 0xa7 (T's position, 47), message 116."""
    if target in battle.confused:
        return b""
    if battle.b[target].ability == 20 and battle.b[actor].ability not in MOLD_BREAKERS:
        return b""                                          # Own Tempo: a secondary's confusion fails silently
    if battle.terrain == "Misty" and battle.grounded(target):
        raise Unsupported("confusion in Misty Terrain")
    battle.confused[target] = [turns, actor]
    q = queue.encode(0x13, (target, 6, 0, turns << 3 | 2, actor))
    return q + queue.encode(0xA7, (POSITION[target], 47)) + message(actor, 116, target)


def stopped(battle, actor, number, text, code=None, handler_pair=True):
    """A move its user's status stops: the status's message (and 0xa7), 0x52 (A, 0), 0x1d with no hit, the
    two 0x5b and 0x1e."""
    move = MOVES.get(number) or {"type": "Normal"}
    q = message(actor, text, actor)
    if code is not None:
        q += queue.encode(0xA7, (POSITION[actor], code))
    q += queue.encode(0x52, (actor, 0))
    return q


def no_pp(battle, e):
    """Whether a player's move has no PP left (it fails with message 578); else its PP are spent: 2 against
    a target with Pressure."""
    b = battle.b[e.actor]
    battle.spent.pop(e.actor, None)
    if e.move not in b.moves:
        return False
    i = b.moves.index(e.move)
    if not b.pp[i]:
        return True
    target = BATTLER_AT.get(e.position)
    own = (MOVES.get(e.move) or {}).get("target") in ("self", "allySide", "all")
    cost = 2 if target and not own and battle.b[target].ability == PRESSURE else 1
    battle.spent[e.actor] = min(cost, b.pp[i])             # 0x05 shows what was spent: 1 from a last PP
    b.pp[i] -= battle.spent[e.actor]
    return False


def before_move(battle, e):
    """-> (the queue of what stops or precedes a move, whether the move goes on): a flinch, freeze (thawing
    on chance(20)), sleep, full paralysis (chance(25))."""
    actor = e.actor
    st = battle.status.get(actor)
    r = battle.rng
    if actor in battle.flinched:
        return message(actor, 122, actor) + queue.encode(0x52, (actor, 0)), False, "flinch"
    if st and st[0] in (FRZ, SLP):
        if st[0] == FRZ:
            woke, text = r.chance(20), 99                   # thawed
        else:
            st[4] -= 1
            woke, text = st[4] <= 0, 105                    # woke up
        if not woke:
            return stopped(battle, actor, e.move, 98 if st[0] == FRZ else 104, 45 if st[0] == FRZ else 42), False, "status"
        del battle.status[actor]
        q = queue.encode(0x14, (actor,)) + queue.encode(0x90, (actor, 0)) + message(actor, text, actor)
        pre, goes, why = before_move(battle, e)
        return q + pre, goes, why
    pre = b""
    if actor in battle.confused:
        pre, goes = confusion(battle, actor)
        if not goes:
            return pre, False, "confusion"
    if st and st[0] == PAR and r.chance(25):
        if pre:
            raise Unsupported("a confused battler fully paralysed")
        return stopped(battle, actor, e.move, 93, 46), False, "status"
    return pre, True, None


def confusion(battle, actor):
    """Confusion before a move (Showdown conditions.ts): its turns run down, at 0 it ends with 0x15 (A, 6)
    and message 118 and the move goes on; else 0xa7 (A's position, 47), message 117 and chance(33) to hit
    itself: a 40-power typeless physical hit at its stat stages, roll below(16), shown as 0x91 (A), 0x01 (A,
    the battler that confused it, damage, 2), 0x9a (A, -damage), 0xca (A, 576, A), 0x52 (A, 0)."""
    c, r = battle.confused[actor], battle.rng
    c[0] -= 1
    if c[0] <= 0:
        del battle.confused[actor]
        return queue.encode(0x15, (actor, 6)) + message(actor, 118, actor), True
    q = queue.encode(0xA7, (POSITION[actor], 47)) + message(actor, 117, actor)
    if not r.chance(33):
        return q, True
    if actor == BOSS and battle.raid.state == 1:
        raise Unsupported("the shielded boss hitting itself")
    b = battle.b[actor]
    att, dfn = staged(b.stats[1], battle.stages[actor][1]), staged(b.stats[2], battle.stages[actor][2])
    base = ((2 * b.level // 5 + 2) * 40 * att // dfn // 50 + 2) & 0xFFFF
    dmg = max(1, base * (100 - r.below(16)) // 100)
    if dmg >= battle.hp[actor]:
        raise Unsupported("a confused battler knocking itself out")
    battle.hp[actor] -= dmg
    q += queue.encode(0x91, (actor,)) + queue.encode(0x01, (actor, c[1], dmg, 2))
    q += queue.encode(0x9A, (actor, -dmg & 0xFFFFFFFF)) + queue.encode(0xCA, (actor, 576, actor, END) + (0,) * 6)
    return q + queue.encode(0x52, (actor, 0)), False


def boss_down(battle, actor, number, quiet=False):
    """The boss knocked out, after the hit's record: the battle is won. 0x09 carries the knocking move's
    slot in its user's moveset (382 of 383 oracle knockouts)."""
    q = queue.encode(0x49, (BOSS, actor, number)) + queue.encode(0x09, (actor, battle.slot(actor, number) or 0))
    q += queue.encode(0x37, (BOSS, 1, 1)) + (b"" if quiet else message(BOSS, 0, BOSS)) + queue.encode(0x94, (BOSS, 0))
    q += queue.encode(0x37, (BOSS, 8, 1))
    q += b"".join(queue.encode(c, (BOSS,)) for c in (0x5F, 0x62, 0x6C, 0x5D))
    q += b"".join(queue.encode(0x41, (b, BOSS)) for b in sorted(battle.b) if b != BOSS and battle.hp[b])
    q += b"".join(queue.encode(0x33, (BOSS, k)) for k in range(14) if k != 8 or battle.terrain)
    return q + queue.encode(0x80, (BOSS,)) + queue.encode(0x29, (BOSS,)) + queue.encode(0x38, (actor,))


PENALIZED = frozenset((1, 3))       # the host's and the console's Pokemon: a faint costs battle time


def player_down(battle, victim, actor, number, quiet=False):
    """A player's Pokemon knocked out, after the hit's record: as the boss's knockout with the victim's id
    (inside a multi-hit move without the fainted message), 0x41 (b, V) for each battler still standing, no
    0x80, and for the host's or the console's Pokemon
    0x81 (-n), n seconds off the battle timer: the time limit times 0.125 times the players' mean level over
    the boss's (339 of 339 oracle battles; float32, truncated)."""
    battle.hp[victim] = 0
    battle.faints[victim] += 1
    battle.status.pop(victim, None)                         # a faint clears its status
    battle.confused.pop(victim, None)
    battle.charged.discard(victim)
    for e in battle.entries:
        if e.actor == victim:
            e.done = True                                   # its actions are marked run
    q = queue.encode(0x49, (victim, actor, number)) + queue.encode(0x09, (actor, battle.slot(actor, number) or 0))
    q += queue.encode(0x37, (victim, 1, 1)) + (b"" if quiet else message(victim, 0, victim)) + queue.encode(0x94, (victim, 0))
    q += queue.encode(0x37, (victim, 8, 1))
    q += b"".join(queue.encode(c, (victim,)) for c in (0x5F, 0x62, 0x6C, 0x5D))
    q += b"".join(queue.encode(0x41, (b, victim)) for b in sorted(battle.b) if battle.hp[b])
    q += b"".join(queue.encode(0x33, (victim, k)) for k in range(14) if k != 8 or battle.terrain)
    q += queue.encode(0x29, (victim,))
    if victim in PENALIZED:
        n = faint_penalty(battle)
        battle.timer_offset -= n
        q += queue.encode(0x81, (-n & 0xFFFF,))
    return q + queue.encode(0x38, (actor,))


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def faint_penalty(battle):
    """Seconds a player's faint takes off the battle timer."""
    players = [battle.b[b].level for b in battle.b if b != BOSS]
    ratio = f32(f32(f32(sum(players)) / f32(len(players))) / f32(battle.b[BOSS].level))
    return int(f32(ratio * f32(f32(battle.raid.limit) * f32(0.125))))


_never = lambda battle, b, out, inc, every: False
_aimed = lambda *types: lambda battle, b, out, inc, every: any(m["type"] in types for m in inc)
_aimed_any = lambda *types: lambda battle, b, out, inc, every: any(m["type"] in types for m in every)
_using = lambda *types: lambda battle, b, out, inc, every: any(m["type"] in types for m in out)
_contact = lambda battle, b, out, inc, every: any("contact" in m["flags"] for m in inc)
_pinch = lambda t: lambda battle, b, out, inc, every: battle.hp[b.id] * 3 <= battle.full[b.id] and \
    any(m["type"] == t for m in out)
# Showdown abilities.ts: what each ability's callbacks need before they act; with no status, weather,
# confusion, flinch or critical hit in a plain round, many never do. (battle, b, its moves, moves aimed
# at it, every move) -> whether they can act.
WHEN = {
    4: _never, 75: _never,                                          # Battle Armor, Shell Armor: no crit
    5: _never,                                                      # Sturdy: use() refuses its knockout
    8: _never, 94: _never,                                          # Sand Veil, Solar Power: weather
    12: _never, 20: _never,                                         # Oblivious, Own Tempo: attraction, confusion
    28: _never, 30: _never, 61: _never, 62: _never, 63: _never, 93: _never, 95: _never, 131: _never,  # status
    51: _never,                                                     # Keen Eye: use() refuses evasion stages
    80: _never, 83: _never,                                         # Steadfast, Anger Point: flinch, crit
    104: _never, 163: _never, 164: _never,                          # mold breakers: a target ability refuses
    9: _contact, 24: _contact, 27: _contact, 38: _contact, 49: _contact, 56: _contact, 124: _contact,
    160: _contact,
    10: _aimed("Electric"), 78: _aimed("Electric"), 11: _aimed("Water"), 18: _aimed("Fire"),
    85: _aimed("Fire"), 47: _aimed("Fire", "Ice"), 87: _aimed("Water", "Fire"), 157: _aimed("Grass"),
    155: _aimed("Bug", "Dark", "Ghost"), 31: _aimed_any("Electric"), 114: _aimed_any("Water"),
    277: lambda battle, b, out, inc, every: any("wind" in m["flags"] for m in inc),
    274: lambda battle, b, out, inc, every: any("wind" in m["flags"] for m in inc),
    19: lambda battle, b, out, inc, every: any(secondaries(m) for m in inc),
    125: lambda battle, b, out, inc, every: any(secondaries(m) for m in out),
    55: lambda battle, b, out, inc, every: any(m["category"] == "Physical" for m in out),
    91: lambda battle, b, out, inc, every: any(battle.stab(b.id, m["type"]) > 1 for m in out),
    101: lambda battle, b, out, inc, every: any(m["basePower"] <= 60 for m in out),
    143: lambda battle, b, out, inc, every: any("contact" in m["flags"] for m in out),
    177: _using("Flying"),
    109: None, 132: None, 140: None,                                # Unaware, Friend Guard, Telepathy: callbacks()
}


def callbacks(b, battle=None, acts=()):
    """The live callbacks of a battler's ability and held item, less those measured idle in plain rounds
    and those whose condition (WHEN) the round's moves do not meet."""
    live = set() if b.ability in IDLE_ABILITIES else set(ABILITIES.get(str(b.ability), ["unknown"])) - INERT
    if b.ability in WHEN and battle is not None:
        move = lambda n: MOVES.get(n) or {"type": "", "flags": {}, "category": "", "basePower": 0}
        out = [move(n) for a, n, p in acts if a == b.id]
        inc = [move(n) for a, n, p in acts if BATTLER_AT.get(p) == b.id]
        allies = [a for a, n, p in acts if BATTLER_AT.get(p) == b.id and (a == BOSS) == (b.id == BOSS)]
        if b.ability == 140:                                        # Telepathy: an ally's move
            live = live if allies else set()
        elif b.ability == 109:                                      # Unaware: a stat stage in play
            ids = {a for a, n, p in acts} | {BATTLER_AT.get(p) for a, n, p in acts}
            live = live if any(any(battle.stages[i][1:5]) for i in ids if i in battle.stages) else set()
        elif b.ability == 132:                                      # Friend Guard: an ally is hit
            hit = {BATTLER_AT.get(p) for a, n, p in acts} - {b.id, None}
            live = live if any((i == BOSS) == (b.id == BOSS) for i in hit) else set()
        elif not WHEN[b.ability](battle, b, out, inc, [move(n) for a, n, p in acts]):
            live = set()
    if b.ability in (STALL, MYCELIUM_MIGHT):
        live.discard("onFractionalPriority")            # order_key and the 0x51 pass apply them
    if b.ability in (FILTER, SOLID_ROCK):
        live.discard("onSourceModifyDamage")            # Battle.damage applies them
    if b.ability == TANGLED_FEET and b.id in getattr(battle, "confused", {}):
        live.add("onModifyAccuracy")                    # confused, it is harder to hit
    if b.ability == TOXIC_BOOST and battle is not None and battle.status.get(b.id, (0,))[0] == PSN:
        live.add("onBasePower")
    if b.ability == MYCELIUM_MIGHT and not any(a == b.id and (MOVES.get(n) or {}).get("category") == "Status"
                                               for a, n, p in acts):
        live.discard("onModifyMove")                    # it ignores abilities for its status moves only
    if b.ability == PRANKSTER:
        live.discard("onModifyPriority")
    if b.ability in PINCH or b.ability in (HUGE_POWER, PURE_POWER):
        live -= {"onModifyAtk", "onModifySpA"}             # Battle.damage applies them
    if b.ability == ADAPTABILITY and b.id != BOSS:
        live.discard("onModifySTAB")
    if b.ability == RIVALRY:
        live.discard("onBasePower")                     # Battle.damage applies it
    if b.ability in (HUSTLE, COMPOUND_EYES):
        live -= {"onModifyAtk", "onSourceModifyAccuracy"}   # Battle.damage and accuracy() apply them
    if b.ability in (THICK_FAT,):
        live -= {"onSourceModifyAtk", "onSourceModifySpA"}
    if b.ability in (STRONG_JAW, RECKLESS):
        live.discard("onBasePower")
    if b.ability == TINTED_LENS:
        live.discard("onModifyDamage")
    if b.ability in (SERENE_GRACE, STENCH, SKILL_LINK):
        live.discard("onModifyMove")
    if b.ability == SHIELD_DUST:
        live.discard("onModifySecondaries")
    if b.ability == ROCK_HEAD:
        live.discard("onDamage")                        # use() leaves out the recoil
    if b.ability in ITEM_ABILITIES and battle is not None and not any(x.item for x in battle.b.values()):
        live = set()                                    # no item anywhere: nothing to eat, steal or pass
    if b.ability in CONTACT_STATUS or b.ability in (RATTLED, SAND_SPIT):
        live.discard("onDamagingHit")                   # use() draws it
    if b.ability == POISON_TOUCH:
        live.discard("onSourceDamagingHit")
    if b.item and b.item not in IDLE_ITEMS:
        item = set(ITEMS.get(str(b.item), ["unknown"]))
        if str(b.item) in TYPE_BOOSTS:
            item.discard("onBasePower")                     # Battle.damage applies it
        if b.item == FOCUS_SASH:
            item.discard("onDamage")                        # use() refuses the hit it would survive
        live |= item - INERT | item & {"onUpdate"}       # a berry eats on its update
    return live


class Entry:
    """A row of the round's action list: a commanded move, a raid action, the stat reset an extra action
    leaves, or the move an extra action uses (pokeldn docs/sv_raid.md, The boss's actions)."""
    MOVE, RAID, RESET, RAID_MOVE = "move", "raid", "reset", "raid move"

    def __init__(self, actor, kind, move=0, position=0, sub=0, value=0):
        self.actor, self.kind, self.move, self.position, self.sub, self.value = actor, kind, move, position, sub, value
        self.done = False

    def moving(self):
        return self.kind in (Entry.MOVE, Entry.RAID_MOVE)


def order_key(battle, e):
    """The action's order key: its class (4 a raid action, 2 a reset, 1 a move), the move's priority, the
    battler's 0x51 value this round (0 for Stall; 1 in the round's first sort, before the 0x51 pass sets it),
    then Speed (pokeldn docs/sv_raid.md, Speed ties)."""
    if e.moving():
        return 1, priority(battle, e.actor, e.move), battle.paced.get(e.actor, 1), battle.speed(e.actor)
    return 4 if e.kind == Entry.RAID else 2, 0, True, battle.speed(e.actor)


def priority(battle, actor, number):
    """A move's priority bracket: Prankster raises a status move's by 1."""
    move = MOVES.get(number) or {}
    prio = move.get("priority", 0)
    return prio + 1 if battle.b[actor].ability == PRANKSTER and move.get("category") == "Status" else prio


def paced(battle, actor, number):
    """The 0x51 value: 0 for Stall, and for Mycelium Might's status moves (last in their bracket)."""
    if battle.b[actor].ability == STALL:
        return 0
    return int(not (battle.b[actor].ability == MYCELIUM_MIGHT and (MOVES.get(number) or {}).get("category") == "Status"))


def sort(battle, entries):
    """One sort of the action list: each move's key computed in list order (a handler move's 0x5a and 0x5b),
    then the exchange sort with its tie draws."""
    q = b"".join(handler(battle, (e.actor, e.move), 0) for e in entries if e.moving())
    entries[:] = speed_order(battle, entries, lambda e: order_key(battle, e))
    return q


def run_actions(battle, entries):
    """The round's actions in order: the round start's 0x51 by battler id and three sorts (the first's
    order in the 0x51 pass), then the first action not yet run, again and again, re-sorted after each
    (pokeldn docs/sv_raid.md, Speed ties). After each, the boss's HP triggers (raid_turn)."""
    battle.moved = set()
    battle.flinched = set()
    battle.paced = {}                                       # each round's first sort: 1 for every move
    battle.entries = entries
    battle.raid.pending = []
    q = queue.encode(0xB5, (0,))
    q += b"".join(queue.encode(0x51, (b, 1)) for b in sorted({e.actor for e in entries}))
    q += unanswered(battle, entries)
    q += sort(battle, entries)
    for e in entries:
        if e.kind == Entry.MOVE:
            battle.paced[e.actor] = paced(battle, e.actor, e.move)
            q += queue.encode(0x51, (e.actor, battle.paced[e.actor]))
    q += sort(battle, entries) + sort(battle, entries)
    while True:
        e = next((e for e in entries if not e.done), None)
        if e is None:
            break
        e.done = True
        if not battle.hp[e.actor]:
            continue                                        # a fainted battler's action does nothing
        q += run(battle, e, entries)
        if not battle.hp[BOSS]:
            break                                           # the boss is down: nobody else moves
        raid_turn(battle, entries)
        if all(e.done for e in entries):
            break
        q += sort(battle, entries)
    return q


def unanswered(battle, entries):
    """After the shield breaks, the boss's next move against each player's client slot is dropped: its
    actions are marked run and 0x85 (6, slot) shows it."""
    from raidbattle.battlers import SLOT
    q = b""
    for e in entries:
        if e.actor == BOSS and e.kind == Entry.MOVE and not e.done:
            cls = SLOT.get(BATTLER_AT.get(e.position), 0)
            if cls in battle.raid.stunned:
                battle.raid.stunned.discard(cls)
                for x in entries:
                    if x.actor == BOSS:
                        x.done = True
                q += queue.encode(0x85, (6, cls))
    return q


def run(battle, e, entries):
    """-> the queue for one action of the list; the round's first move first computes every move's key
    again (a handler move's 0x5a and 0x5b)."""
    q = b""
    if e.moving() and not battle.moved:
        q += b"".join(handler(battle, (x.actor, x.move), 0) for x in entries if x.moving())
    if e.moving():
        battle.moved.add(e.actor)
    if e.kind == Entry.MOVE:
        q += handler(battle, (e.actor, e.move), 0x72000, last=False)
        if e.actor != BOSS and (MOVES.get(e.move) or {}).get("isNonstandard") in ("Past", "LGPE"):
            if e.move not in PAST_KNOWN:
                raise Unsupported(f"move {e.move}, not in the game, with no handler known")
            q += queue.encode(0xCA, (e.actor, 567, e.actor, END) + (0,) * 6) + queue.encode(0x52, (e.actor, 0))
            return q + queue.encode(0x5B, (e.actor, e.move)) * 2 + queue.encode(0x1E, (e.actor, 0))   # not in the game
        empty = e.actor != BOSS and e.move in battle.b[e.actor].moves and \
            not battle.b[e.actor].pp[battle.b[e.actor].moves.index(e.move)]
        if empty and (e.actor in battle.flinched or e.actor in battle.confused or
                      battle.status.get(e.actor, (0,))[0] in (FRZ, SLP)):
            raise Unsupported("a move with no PP left from a flinched, confused, frozen or sleeping battler")
        pre, goes, why = (b"", True, None) if empty else before_move(battle, e)   # no PP: before paralysis
        if goes and e.actor != BOSS and no_pp(battle, e):
            q += pre + queue.encode(0xC9, (e.actor, 0, e.move, 10, 1))
            q += queue.encode(0xCA, (e.actor, 578, e.actor, END) + (0,) * 6) + queue.encode(0x52, (e.actor, 0))
            return q + queue.encode(0x5B, (e.actor, e.move)) * 2 + queue.encode(0x1E, (e.actor, 0))
        if not goes:
            move = MOVES.get(e.move) or {"type": "Normal"}
            tail = queue.encode(0x5B, (e.actor, e.move)) * 2 + queue.encode(0x1E, (e.actor, 0))
            if why in ("status", "confusion") and e.actor == BOSS:       # only the boss's stopped move shows 0x1d
                tail = queue.encode(0x1D, (e.actor, e.position, TYPES.index(move["type"]), 0, 0, e.move, e.move)) + tail
            return q + pre + tail
        return q + pre + use(battle, e.actor, e.move, e.position)
    if e.kind == Entry.RAID:
        return raid_action(battle, e, entries)
    if e.kind == Entry.RESET:
        return reset(battle, e.value)
    if battle.status.get(e.actor, (0,))[0] == PAR:
        raise Unsupported("a paralysed boss's raid move")
    pre, goes = confusion(battle, e.actor) if e.actor in battle.confused else (b"", True)
    used = handler(battle, (e.actor, e.move), 0x72000, last=False) + pre
    if goes:
        used += use(battle, e.actor, e.move, e.position)
    else:                                                   # it hit itself: the move's end with no hit
        move = MOVES.get(e.move) or {"type": "Normal"}
        used += queue.encode(0x1D, (e.actor, e.position, TYPES.index(move["type"]), 0, 0, e.move, e.move))
        used += queue.encode(0x5B, (e.actor, e.move)) * 2 + queue.encode(0x1E, (e.actor, 0))
    end = queue.encode(0x1E, (e.actor, 0))
    return q + queue.encode(0xC1, (9, 0)) + used[:-len(end)] + queue.encode(0xC1, (9, 1)) + end


def raid_turn(battle, entries):
    """After an action, while the boss stands: an empty list of waiting raid actions is filled from the HP
    triggers; without a shield among them they join this round's actions."""
    r = battle.raid
    if r.pending or not battle.hp[BOSS]:
        return
    r.pending = r.triggers(battle)
    moves = [(k, v) for k, v in r.pending if k == raid.EXTRA and r.extras[v][0] == raid.MOVE]
    if moves and battle.status.get(BOSS, (0,))[0] == SLP:
        raise Unsupported("a sleeping boss's move action")
    if moves and battle.status.get(BOSS, (0,))[0] == FRZ:     # a frozen boss holds its move actions back
        r.pending = [x for x in r.pending if x not in moves]
    if r.pending and all(k != raid.SHIELD for k, v in r.pending):
        entries += [Entry(BOSS, Entry.RAID, sub=k, value=v) for k, v in r.pending]


def raid_action(battle, e, entries):
    """A raid action: 0x85 (kind, x) and 0xc1 (kind, y), then its effect; an extra action that already ran
    shows nothing."""
    r = battle.raid
    if not r.run(battle, e.sub, e.value):
        return b""
    if e.sub == raid.EXTRA:
        action, _timing, _value, move = r.extras[e.value]
        q = queue.encode(0x85, (raid.EXTRA, e.value)) + queue.encode(0xC1, (raid.EXTRA, action))
        if action in (raid.RESET_BOSS, raid.RESET_PLAYERS):
            entries.append(Entry(BOSS, Entry.RESET, value=action))
        elif action == raid.MOVE:
            entries.append(Entry(BOSS, Entry.RAID_MOVE, move=move, position=raid_target(battle, move)))
        else:
            raise Unsupported(f"raid action {action}")
        return q
    if e.sub == raid.DOUBLE:
        raise Unsupported("the double action")
    x = 0 if e.sub == raid.LOW_TIME else e.value
    q = queue.encode(0x85, (e.sub, x)) + queue.encode(0xC1, (e.sub, x))
    if e.sub == raid.SHIELD and battle.status.get(BOSS):
        del battle.status[BOSS]                             # the shield cures the boss's status
        q += queue.encode(0x14, (BOSS,)) + queue.encode(0x90, (BOSS, 0))
    if e.sub == raid.SHIELD and battle.confused.pop(BOSS, None):
        q += queue.encode(0x15, (BOSS, 6))                  # and its confusion
    return q


def reset(battle, action):
    """An extra action's reset: the boss's stat changes (0x0f, then 0xc2 (3, 2, 2)), or the standing
    players' stat changes (0x10 each) and abilities (condition 16 by 0x13 (b, 16, 0, b << 26 | 12, 2) for each
    whose ability can be suppressed), then 0xc2 (60, 2, 0)."""
    if action == raid.RESET_BOSS:
        if any(n > 0 for n in battle.stages[BOSS]):
            raise Unsupported("the boss's raised stats reset")
        battle.stages[BOSS] = [0] * 8
        q = queue.encode(0x0F, (BOSS,))
        if battle.status.pop(BOSS, None):
            q += queue.encode(0x14, (BOSS,)) + queue.encode(0x90, (BOSS, 0))   # its status cured too
        return q + queue.encode(0xC2, (3, 2, 2))
    standing = [b for b in sorted(battle.b) if b != BOSS and battle.hp[b]]
    suppressed = [b for b in standing if battle.b[b].ability not in CANT_SUPPRESS]
    if any(battle.b[b].suppressed for b in suppressed):
        raise Unsupported("an ability suppressed twice")
    for b in standing:
        battle.stages[b] = [0] * 8
    for b in suppressed:
        battle.b[b].suppressed, battle.b[b].ability = battle.b[b].ability, 0
    q = b"".join(queue.encode(0x10, (b,)) for b in standing)
    q += b"".join(queue.encode(0x13, (b, 16, 0, b << 26 | 12, 2)) for b in suppressed)
    return q + queue.encode(0xC2, (60, 2, 0))


def raid_target(battle, number):
    """The position an extra action's move aims at: none (10) for a field move, the boss (4) for its own,
    else a standing player drawn by below(n) over them in position order."""
    move = MOVES.get(number) or {}
    target = move.get("target")
    if target in ("all", "allySide", "foeSide", "allies"):
        return 10
    if target in ("self", "adjacentAllyOrSelf"):
        return POSITION[BOSS]
    if target not in ("normal", "any", "randomNormal"):
        raise Unsupported(f"an extra action's move aimed at {target}")
    standing = [b for b in sorted(POSITION, key=POSITION.get) if b != BOSS and battle.hp[b]]
    if not standing:
        raise Unsupported("an extra action's move with no player standing")
    return POSITION[standing[battle.rng.below(len(standing))]]


def standing(battle):
    """The battlers still standing, in id order: what the round end's speed sorts take (0x1144704)."""
    return [b for b in sorted(battle.b) if battle.hp[b]]


def round_end(battle, entries, acted, won, counted):
    """The round's end: three battler sorts (eight at a turn's end), 0xb2, 0x37 per action, the turn
    counter 0x75 when a player acted, the turn's end every fourth such round, 0xc5, 0x43 in the second
    sort's order, 0x23 for each battler revived since the last round then each that acted, 0x2d."""
    n = (battle.turns + 1) % TURN if counted else None
    # a round ends with three battler sorts, the second the 0x43 order; a turn's end with eight, the
    # fourth its residual order, the seventh, after the turn's end, the 0x43 order (a Speed Boost there
    # already counts)
    ends = [speed_order(battle, standing(battle), battle.speed) for _ in range(3 if won or n != 0 else 5)]
    if won and len({battle.speed(b) for b in battle.b}) != len(battle.b):
        raise Unsupported("a speed tie in the winning round")
    q = b""
    if not won:
        q += queue.encode(0xB2, (0,))
        q += b"".join(queue.encode(0x37, (e.actor, 7, 1)) for e in entries)
        if counted:
            q += queue.encode(0x75, (3, n))
        if n == 0:
            q += turn_end(battle, ends[3])                  # the fourth sort, ties and all
            ends += [speed_order(battle, standing(battle), battle.speed) for _ in range(3)]
        q += queue.encode(0xC5, (1,))
    q += b"".join(queue.encode(0x43, (b,)) for b in ends[1 if won or n != 0 else 6] if battle.hp[b])
    acted = battle.listed + [b for b in acted if b not in battle.listed]
    battle.listed = []
    q += b"".join(queue.encode(0x23, (b,)) for b in acted)
    q += queue.encode(0x2D, (0,))
    if counted:
        battle.turns += 1
    battle.rounds += 1
    return q


def build(battle, slot, command):
    """-> (the round body for `slot`'s command, whether it wins)."""
    acts = actions(command)
    if any(b.transformed for b in battle.b.values()):
        raise Unsupported("a transformed battler")       # its copied stats, moves and types are not built
    if battle.raid.double:
        raise Unsupported("the boss acting twice")
    weather_check(battle, acts)
    involved = {a[0] for a in acts} | {BATTLER_AT[a[2]] for a in acts if a[2] in BATTLER_AT}
    for b in battle.b.values():
        live = callbacks(b, battle, acts)
        if b.id not in involved:
            live = {k for k in live if k == "onResidual" or k.startswith("onAny")}
        if live:
            raise Unsupported(f"battler {b.id}'s ability {b.ability} or item {b.item}: {sorted(live)[0]}")
    key = lambda a: (priority(battle, a[0], a[1]), paced(battle, a[0], a[1]), battle.speed(a[0]))
    if len({key(a) for a in acts}) != len(acts) and any(a[1] in HANDLER_MOVES for a in acts):
        raise Unsupported("a speed tie with a handler move")
    entries = [Entry(a, Entry.MOVE, move=n, position=p) for a, n, p in acts]
    q = run_actions(battle, entries)
    won = not battle.hp[BOSS]
    acted = range(1, 6) if battle.rounds == 0 else sorted({a[0] for a in acts})
    q += round_end(battle, entries, acted, won, True)
    body = action_block(slot, command) + struct.pack("<I", len(q)) + q
    return body + bytes(BODY - len(body)), won


def raid_round(battle, words):
    """-> (the body of a raid action round for the queued actions `words` [(kind, value)], whether it wins):
    the actions in slot 1's block (pokeldn docs/sv_raid.md, The boss's actions)."""
    if battle.raid.double:
        raise Unsupported("the boss acting twice")
    entries = [Entry(BOSS, Entry.RAID, sub=k, value=v) for k, v in words]
    block = bytearray(0x238)
    for i, (k, v) in enumerate(words):
        struct.pack_into("<QI", block, BLOCK + ACTION * i, raid.word(k, v), BOSS)
    block[COUNTS + 1] = len(words)
    q = run_actions(battle, entries)
    won = not battle.hp[BOSS]
    q += round_end(battle, entries, [BOSS], won, False)
    body = bytes(block) + struct.pack("<I", len(q)) + q
    return body + bytes(BODY - len(body)), won


# abilities that read the weather (Showdown abilities.ts) -> the weathers they read; Orichalcum Pulse is
# refused by its own onModifyAtk when it attacks
WEATHER_ABILITIES = {33: {"rain"}, 44: {"rain"}, 93: {"rain"}, 34: {"sun"}, 94: {"sun"}, 102: {"sun"},
                     281: {"sun"}, 202: {"snow"}, 81: {"snow"}, 115: {"snow"}, 248: {"snow"},
                     87: {"sun", "rain"}, 59: {"sun", "rain", "snow"}, 122: {"sun"},
                     142: {"sun", "rain", "snow", "sand"}, 8: {"sand"}, 146: {"sand"}, 159: {"sand"}}
WEATHER_TURNS = 5


def weather_check(battle, acts):
    """Sun, rain or snow leave a round unchanged when no move of the round is boosted by it, no battler
    reads it; sand also raises a Rock type's Special Defense (Battle.damage); terrain_check refuses what a
    terrain changes and nothing here builds."""
    if battle.terrain:
        terrain_check(battle, acts)
    if not battle.field:
        return
    if any(WEATHER_ABILITIES.get(b.ability, set()) & battle.field for b in battle.b.values() if b.ability not in WEATHER_HANDLED):
        raise Unsupported("an ability reads the weather")
    for actor, number, position in acts:
        move = MOVES.get(number) or {"type": "", "category": ""}
        target = BATTLER_AT.get(position)
        if "snow" in battle.field and move["category"] == "Physical" and target and \
                "Ice" in battle.defending(target):
            raise Unsupported("an Ice-type target in snow")


def terrain_check(battle, acts):
    """Refuses what a terrain changes and nothing here builds: Grassy Terrain's heal, Psychic Terrain
    stopping a priority move."""
    if battle.terrain == "Grassy":
        raise Unsupported("Grassy Terrain")
    if any(x.ability in TERRAIN_READERS or x.item in TERRAIN_ITEMS for x in battle.b.values()):
        raise Unsupported("an ability or item reads the terrain")
    for actor, number, position in acts:
        target = BATTLER_AT.get(position)
        if battle.terrain == "Psychic" and priority(battle, actor, number) > 0 and target is not None and \
                (target == BOSS) != (actor == BOSS) and battle.grounded(target):
            raise Unsupported("a priority move into Psychic Terrain")


TURN = 4                    # a turn ends every fourth command round
# the end-of-turn residual kinds, in the order 0x19 runs them
RESIDUALS = (36, 21, 18, 5, 4, 9, 10, 8, 46, 43, 48, 11, 12, 23, 13, 31, 33, 15, 19, 29, 30, 38, 37, 39, 40, 41,
             24, 45, 14, 20, 1, 2, 3, 7, 6, 16, 17, 22, 25, 26, 27, 28, 32, 34, 35)
LEFTOVERS = 234
UNNERVE_ID = 127
MOODY = 141                 # idle in a round, acts at a turn's end
SPEED_BOOST = 3


def turn_end(battle, order):
    """A turn's end with nothing to resolve: 0xc5 (0), 0x50 (0), 0x19 (b, kind) for each residual kind
    over the battlers in `order` (speed order), 0x44 (1 to 13)."""
    for b in battle.b.values():
        live = callbacks(b, battle) & {"onResidual"}
        if live and residual_idle(battle, b):
            live = set()
        if battle.hp[b.id] and battle.status.get(b.id) and battle.status[b.id][0] not in (BRN, PSN, PAR, FRZ, SLP):
            raise Unsupported(f"battler {b.id}'s status at the turn's end")
        if b.ability == MOODY and battle.hp[b.id]:
            raise Unsupported("Moody at the turn's end")
        if live:
            raise Unsupported(f"battler {b.id}'s residual at the turn's end: ability {b.ability} item {b.item}")
    q = queue.encode(0xC5, (0,)) + queue.encode(0x50, (0,)) + weather_end(battle)
    if "sand" in battle.field:
        q += sandstorm(battle, order)
    q += leftovers(battle, order)
    for k in RESIDUALS:
        for b in order:
            if battle.hp[b]:
                q += queue.encode(0x19, (b, k)) + residual(battle, b, k)
    q += side_end(battle)
    q += b"".join(queue.encode(0x44, (k,)) for k in range(1, 9)) + terrain_end(battle)
    q += b"".join(queue.encode(0x44, (k,)) for k in range(9, 14))
    fresh, battle.fresh = battle.fresh, set()
    for b in order:
        if battle.hp[b] and battle.b[b].ability == SPEED_BOOST and b not in fresh:      # Showdown: activeTurns
            if battle.stages[b][5] == 6:
                raise Unsupported("Speed Boost at +6")
            battle.stages[b][5] += 1                        # Speed Boost: +1 Speed after the turn's end
            q += queue.encode(0x25, (b,)) + queue.encode(0xC7, (b, 0)) + queue.encode(0x0C, (b, 5, 1))
            q += queue.encode(0x92, (b, 5, 1, 0)) + message(b, 15, b) + queue.encode(0xC8, (b,))
    return q


def leftovers(battle, order):
    """Leftovers at a turn's end, before the residual kinds, in speed order: a sixteenth of the record HP,
    at least 1, to a holder below its maximum: a 5-byte zero group, 0x9b (b, 0), a 3-byte zero group, 0xa7
    (b's position, 51), 0x03 (b, heal), 0x9a (b, heal), 0xcb (b, 295, b, 234)."""
    q = b""
    for b in order:
        if battle.b[b].item != LEFTOVERS or not battle.hp[b] or battle.hp[b] >= battle.full[b]:
            continue
        if battle.b[b].ability in (UNNERVE_ID, 82, 247):                    # Unnerve, Gluttony, Ripen
            raise Unsupported(f"battler {b}'s ability beside its Leftovers")
        heal = max(1, battle.b[b].stats[0] // 16)           # shown whole, though the HP stops at the maximum
        battle.hp[b] = min(battle.full[b], battle.hp[b] + heal)
        q += queue.encode_group(0xCF, bytes(5)) + queue.encode(0x9B, (b, 0)) + queue.encode_group(0xCF, bytes(3))
        q += queue.encode(0xA7, (POSITION[b], 51)) + queue.encode(0x03, (b, heal)) + queue.encode(0x9A, (b, heal))
        q += message(b, 295, b, LEFTOVERS)
    return q


def residual_idle(battle, b):
    """Whether an ability's onResidual does nothing and draws nothing this turn end (Showdown abilities.ts):
    Shed Skin and Hydration (in rain) with no status, Healer with no statused ally (the boss has none)."""
    if b.ability == 61:                                     # Shed Skin: chance(33) only while statused
        return not battle.status.get(b.id)
    if b.ability == 93:                                     # Hydration
        return "rain" not in battle.field or not battle.status.get(b.id)
    if b.ability == 131:                                    # Healer: its allies' statuses
        return b.id == BOSS or not any(battle.status.get(i) for i in battle.b if i not in (b.id, BOSS))
    return False


def residual(battle, b, kind):
    """A status's damage at a turn's end, after its kind's 0x19: a burn (kind 4) a sixteenth of the maximum
    HP, a poison (kind 5) an eighth, a bad poison n sixteenths on its n-th turn end: 0xa7 (position, code),
    0x01 (b, the battler that inflicted it, damage, 39 or 38), 0x9a (b, -damage), message 88 or 82."""
    st = battle.status.get(b)
    if not st or (kind, st[0]) not in ((4, BRN), (5, PSN)):
        return b""
    full = battle.b[b].stats[0]                             # the boss's record HP, not its pool
    if st[0] == BRN:
        dmg, code, how, text = max(1, full // 16), 44, 39, 88
    elif st[5]:
        st[3] += 1
        dmg, code, how, text = max(1, full // 16) * st[3], 43, 38, 82
    else:
        dmg, code, how, text = max(1, full // 8), 43, 38, 82
    if battle.b[b].ability in (MAGIC_GUARD, 90):                # Magic Guard, Poison Heal
        raise Unsupported(f"battler {b}'s ability {battle.b[b].ability} against a status's damage")
    if dmg >= battle.hp[b]:
        raise Unsupported("a knockout at a turn's end")
    if b == BOSS and boss_trigger(battle, dmg):
        raise Unsupported("a boss HP trigger at a turn's end")
    battle.hp[b] -= dmg
    q = queue.encode(0xA7, (POSITION[b], code)) + queue.encode(0x01, (b, st[2], dmg, how))
    return q + queue.encode(0x9A, (b, -dmg & 0xFFFFFFFF)) + message(b, text, b)


SAFETY_GOGGLES = 650
WEATHER_CODES = {name: w for name, w in WEATHER_MOVES.values()}


def weather_end(battle):
    """A weather's fifth turn end, counting the turn it rose in: 0x99 (w), 0x54, 0x6a (0), before any
    weather damage, which then does not come."""
    up = battle.field & set(WEATHER_CODES)
    if not up:
        return b""
    battle.weather_left -= 1
    if battle.weather_left:
        return b""
    battle.field -= up
    return queue.encode(0x99, (WEATHER_CODES[up.pop()],)) + queue.encode(0x54, ()) + queue.encode(0x6A, (0,))


def sandstorm(battle, order):
    """Sandstorm's damage at a turn's end (Showdown conditions.ts): a sixteenth of the maximum HP, at
    least 1, to each battler in speed order that is not Rock, Ground or Steel; message 133, 0xa7, 0x01 (b, the
    battler that raised the sandstorm, damage, 1), 0x9a."""
    q = b""
    for i in order:
        b = battle.b[i]
        if not battle.hp[i] or set(battle.defending(i)) & {"Rock", "Ground", "Steel"} or b.item == SAFETY_GOGGLES:
            continue
        if b.ability in SAND_IMMUNE:
            continue
        if b.ability in (MAGIC_GUARD, SHIELDS_DOWN) or b.ability in PINCH:
            raise Unsupported(f"battler {i}'s ability {b.ability} in the sandstorm")
        dmg = max(1, b.stats[0] // 16)
        if dmg >= battle.hp[i]:
            raise Unsupported("a knockout")
        if i == BOSS:
            if boss_trigger(battle, dmg):
                raise Unsupported("a boss HP trigger")
        battle.hp[i] -= dmg
        battle.sand_hurt.add(i)
        q += message(i, 133, i) + queue.encode(0xA7, (POSITION[i], 14)) + queue.encode(0x01, (i, battle.weather_by, dmg, 1))
        q += queue.encode(0x9A, (i, -dmg & 0xFFFFFFFF))
    return q


def handler(battle, act, base, last=True):
    """0x5a (b, M, base + speed) and, after a pass, 0x5b (b, M), for a move that registers a handler."""
    actor, number = act[0], act[1]
    if number not in HANDLER_MOVES:
        return b""
    if base:                                                # the run's key: priority + 7, then the 0x51 value
        base = (priority(battle, actor, number) + 7) << 16 | battle.paced.get(actor, 1) << 13
    # a sort's key reads the stat at its stage; the run's key the Speed with Tailwind and paralysis
    q = queue.encode(0x5A, (actor, number, base + battle.speed(actor, raw=not base)))
    return q + queue.encode(0x5B, (actor, number)) if last else q


def boss_trigger(battle, loss):
    """Whether losing `loss` HP outside an action (the sandstorm) fires one of the boss's HP triggers."""
    battle.hp[BOSS] -= loss
    try:
        return bool(battle.raid.triggers(battle))
    finally:
        battle.hp[BOSS] += loss


def speed_order(battle, items, key):
    """-> `items` as the game's speed sort leaves them: each against every later one, the later moved ahead
    when its key is greater; on equal keys below(2), 1 moves it ahead (pokeldn docs/sv_raid.md, Speed ties)."""
    out = list(items)
    for i in range(len(out) - 1):
        for j in range(i + 1, len(out)):
            a, b = key(out[j]), key(out[i])
            if a > b or a == b and battle.rng.below(2):
                out[i], out[j] = out[j], out[i]
    return out


_probe = _data("handler_moves.json")
HANDLER_MOVES, UNSEEN_MOVES = frozenset(_probe["handler"]), frozenset(_probe["unseen"])
# a move not in Scarlet / Violet (never probed) whose handler the corpus showed: with 0x5a, or used with none
HANDLER_MOVES |= frozenset(_probe["past_handler"])
PAST_KNOWN = HANDLER_MOVES | frozenset(_probe["past_plain"])


REVIVE_ABILITIES = frozenset((46, 104, 163, 164, 213, 119, 107, 127))   # announced again as at the start


def revive(battle, slot):
    """-> the body of message 0x23 for `slot`, whose Pokemon fainted: slot's block holds one action of kind 8;
    the queue restores its HP (0x03, message 1), sends it back in as at the battle's start with the round
    count in 0x16, then 0x98 (slot, 0, 0, 1), 0x20 (b, 18) and its switch-in ability."""
    from raidbattle import start
    from raidbattle.battlers import SLOT
    b = next(i for i, s_ in SLOT.items() if s_ == slot)
    x = battle.b[b]
    if battle.hp[b]:
        raise Unsupported(f"battler {b} revived standing")
    if x.ability not in REVIVE_ABILITIES | start.QUIET_ABILITIES | start.QUIET_TOO | {start.OWN_TEMPO, start.INNER_FOCUS}:
        raise Unsupported(f"battler {b}'s ability {x.ability} on its revive")
    if x.item not in start.QUIET_ITEMS:
        raise Unsupported(f"battler {b}'s item {x.item} on its revive")
    battle.hp[b] = battle.full[b]
    battle.stages[b] = [0] * 8
    battle.fresh.add(b)
    if b not in battle.listed:
        battle.listed.append(b)
    pos = slot
    q = queue.encode(0x03, (b, battle.hp[b])) + message(0, 1, b)
    q += queue.encode(0x3D, (pos,)) + queue.encode(0x16, (pos, 0, 0, battle.rounds))
    q += queue.encode(0x5E, (b, x.ability)) + queue.encode(0x61, (b,)) + queue.encode(0x6B, (b,)) + queue.encode(0x4E, (b,))
    q += queue.encode(0x98, (pos, 0, 0, 1)) + queue.encode(0x20, (b, 18))
    if x.ability == start.UNNERVE:
        q += start.unnerve(x)
    elif x.ability in REVIVE_ABILITIES:
        q += start.ability_in(x, battle.b, battle.stages, battle)
    block = bytearray(0x238)
    struct.pack_into("<Q", block, slot * BLOCK, 8)
    block[COUNTS + slot] = 1
    body = bytes(block) + struct.pack("<I", len(q)) + q
    return body + bytes(BODY - len(body))
