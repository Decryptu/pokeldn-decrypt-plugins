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
IDLE_ABILITIES = frozenset((0, 3, 29, 33, 34, 44, 53, 77, 81, 84, 137, 141, 158, 232, 246, 298, 304))
IDLE_ITEMS = frozenset((234, 541))
# move callbacks that cannot fire in a plain round (Facade: a status the round never sets)
IDLE_MOVE_CALLBACKS = {"Facade": {"onBasePower"}}
KNOCKOUTS = False            # set by the spec tools while knockouts are built
PRESSURE = 46               # a move aimed at it spends 2 PP: 0x05 (b, 0, 2)
STURDY = 5
INNER_FOCUS = 39
# Showdown abilities.ts, flag cantsuppress: kept through the players' reset
CANT_SUPPRESS = frozenset((121, 161, 176, 197, 208, 209, 210, 211, 213, 225, 241, 248, 266, 267, 278, 307))
AIR_BALLOON = 541
SHIELDS_DOWN = 197
LEVITATE = 26
ROCK_HEAD, MAGIC_GUARD = 69, 98
PINCH = {65: "Grass", 66: "Fire", 67: "Water", 68: "Bug"}
HUGE_POWER, PURE_POWER, ADAPTABILITY = 37, 74, 91
FOCUS_SASH = 275
RIVALRY = 79
SAND_SPIT, SMOOTH_ROCK = 245, 283
# Showdown: moves whose power, effect or accuracy sandstorm changes
SAND_MOVES = frozenset({"Weather Ball", "Solar Beam", "Solar Blade", "Shore Up", "Synthesis", "Moonlight",
                        "Morning Sun"})
TYPE_BOOSTS = _data("type_boosts.json")
CONTACT_STATUS = frozenset((9, 38, 49, 56))     # Static, Poison Point, Flame Body, Cute Charm: the target's
CUTE_CHARM = 56                                 # draws only between a male and a female
MOLD_BREAKERS = frozenset((104, 163, 164))      # Mold Breaker, Turboblaze, Teravolt: Inner Focus ignored
POISON_TOUCH = 143                              # the attacker's
RATTLED = 155                                   # +1 Speed, hit by a Bug, Dark or Ghost move
STALL = 100                 # moves last in its bracket; 0x51 (b, 0) in the speed pass
TARGET_CLASS = {"allAdjacent": 4, "allAdjacentFoes": 5}     # 0x8b's ninth argument; 0 for one target
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
        self.field = set()                              # "sun", "rain", "snow", "sand", "terrain"
        self.weather_set = 0                            # the round the weather was set in
        self.sand_hurt = set()                          # battlers the sandstorm has damaged
        self.switch_order = None                        # the battle start's speed sort (start.body)
        self.turns = 0                                  # rounds a player acted in (0x75)
        self.moved = set()                              # battlers whose move ran this round
        self.raid = None                                # raid.Raid: the boss's actions

    def slot(self, battler, number):
        """The move's slot in the battler's moveset (0x05, 0x07, 0x08); None for a move it does not know (a
        raid action's move: no 0x07 or 0x08)."""
        moves = self.b[battler].moves
        return moves.index(number) if number in moves else None if battler == BOSS else 0

    def speed(self, battler):
        """The Speed the turn order reads: the stat at its stage."""
        return staged(self.b[battler].speed, self.stages[battler][5])

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

    def damage(self, actor, target, move, roll, crit):
        a, d = self.b[actor], self.b[target]
        physical = move["category"] == "Physical"
        att = staged(a.stats[1], self.stages[actor][1]) if physical else staged(a.stats[4], self.stages[actor][3])
        dfn = staged(d.stats[2], self.stages[target][2]) if physical else staged(d.stats[5], self.stages[target][4])
        if not physical and "sand" in self.field and "Rock" in self.defending(target):
            dfn = modify(dfn, 1.5)                          # Showdown conditions.ts: sandstorm's onModifySpD
        if a.ability in PINCH and move["type"] == PINCH[a.ability] and self.hp[actor] * 3 <= self.full[actor]:
            att = modify(att, 1.5)                          # Showdown: Overgrow, Blaze, Torrent, Swarm
        if a.ability in (HUGE_POWER, PURE_POWER) and physical:
            att = modify(att, 2)
        power = move["basePower"]
        boosted = TYPE_BOOSTS.get(str(a.item)) == move["type"]
        if boosted:
            power = modify(power, 4915 / 4096)              # Showdown items.ts: Charcoal, Spell Tag and kin
        if a.ability == RIVALRY and a.gender < 2 and d.gender < 2:
            if boosted:
                raise Unsupported("Rivalry chained with a type item")
            power = modify(power, 1.25 if a.gender == d.gender else 0.75)     # Showdown abilities.ts
        power = self.power(actor, move, power)
        base = (2 * a.level // 5 + 2) * power * att // dfn // 50 + 2
        if crit:
            base = modify(base, 1.5)
        x = base * (100 - roll) // 100
        x = modify(x, self.stab(actor, move["type"]))
        e = self.effectiveness(move["type"], target)
        return int(x * e) if e >= 1 else int(x * e)


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
    for key in ("multihit", "self", "volatileStatus", "status", "boosts"):
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
    if actor != BOSS and (MOVES.get(number) or {}).get("isNonstandard") == "Unobtainable":
        raise Unsupported(f"move {number} is not a player's in Scarlet / Violet")   # the Torques: NPC moves
    if (MOVES.get(number) or {}).get("category") == "Status":
        return status_use(battle, actor, number, position)
    move = plain(MOVES.get(number))
    if number in UNSEEN_MOVES:
        raise Unsupported(f"move {number} was never probed")
    target = BATTLER_AT[position]
    r = battle.rng
    if "sand" in battle.field and move["name"] in SAND_MOVES:
        raise Unsupported("a move the weather changes")
    if move["type"] == "Ground" and battle.b[target].ability == LEVITATE:
        raise Unsupported("a Ground move into Levitate")
    if battle.effectiveness(move["type"], target) == 0:
        return immune(battle, actor, target, number, move, position)
    if type(move["accuracy"]) is int and (battle.stages[actor][6] or battle.stages[target][7]):
        raise Unsupported("an accuracy or evasion stage")
    if type(move["accuracy"]) is int and not r.chance(move["accuracy"]):
        raise Unsupported("a miss")
    # Battle Armor and Shell Armor (Showdown onCriticalHit false): no critical-hit draw
    crit = battle.b[target].ability not in CRIT_GUARD and r.below(CRIT_DRAW[move.get("critRatio", 1)]) == 0
    roll = r.below(16)
    if crit:
        raise Unsupported("a critical hit")
    e = battle.effectiveness(move["type"], target)
    if move["type"] == "Ground" and battle.b[target].item == AIR_BALLOON:
        raise Unsupported("a Ground move into an Air Balloon")
    if e not in EFFECTIVENESS:
        raise Unsupported(f"effectiveness {e}")
    code = EFFECTIVENESS[e]
    dmg = battle.damage(actor, target, move, roll, crit)
    if target == BOSS:
        dmg = battle.raid.damage(dmg)
    if dmg >= battle.hp[target] and target != BOSS and not KNOCKOUTS:
        raise Unsupported("a knockout")
    if dmg >= battle.hp[target] == battle.full[target] and (battle.b[target].ability == STURDY or
                                                           battle.b[target].item == FOCUS_SASH):
        raise Unsupported("Sturdy or Focus Sash")
    dmg = min(dmg, battle.hp[target])
    if battle.b[target].ability == SHIELDS_DOWN and 2 * (battle.hp[target] - dmg) <= battle.full[target]:
        raise Unsupported("Shields Down at half HP")
    knockout = target == BOSS and dmg == battle.hp[target]
    if knockout:
        r.chance(0)                                         # drawn by every hit that knocks the boss out
    drops = b""
    for sec in secondaries(move) if not knockout else ():  # a knocked-out boss draws no secondary
        guarded = battle.b[target].ability == INNER_FOCUS and battle.b[actor].ability not in MOLD_BREAKERS
        if sec.get("volatileStatus") == "flinch" and (target == BOSS or guarded):
            continue                                        # the boss, or Inner Focus, cannot flinch: no draw
        if sec.get("volatileStatus") == "confusion":
            r.skip()                                        # one step before the chance (oracle draw replay)
        if r.chance(sec["chance"]):
            if sec.get("volatileStatus") == "flinch" and target in battle.moved and not knockout:
                continue                                    # a target that already moved: nothing shows
            if set(sec) != {"chance", "boosts"} or knockout:
                raise Unsupported("a secondary effect")
            drops += stat_drop(battle, actor, target, sec["boosts"])
    attract = battle.b[target].ability != CUTE_CHARM or battle.b[actor].gender + battle.b[target].gender == 1
    if "contact" in move["flags"] and not knockout and (battle.b[target].ability in CONTACT_STATUS and attract or
                                                        battle.b[actor].ability == POISON_TOUCH):
        if r.chance(30):                                    # Showdown: randomChance(3, 10) on contact, after the secondaries
            raise Unsupported("a contact ability's status")
    battle.hp[target] -= dmg
    mtype, cat = TYPES.index(move["type"]), 1 if move["category"] == "Physical" else 2
    apos, tpos = POSITION[actor], POSITION[target]
    e5 = [7] * 5
    e5[tpos] = code
    hit = [0] * 5
    hit[tpos] = 1
    q = b""
    if actor != BOSS:
        q += queue.encode(0x05, (actor, battle.slot(actor, number), 2 if battle.b[target].ability == PRESSURE else 1))
    q += pp(battle, 0x07, actor, number)
    q += queue.encode(0xC9, (actor, 0, number, tpos, 0))
    q += queue.encode(0x7B, (number, battle.rounds, actor))
    for size in (20, 5, 5, 5, 19, 20):
        q += queue.encode_group(0xCF, bytes(size))
    q += queue.encode(0x7E, (0, *hit))
    q += queue.encode(0x7E, (1, 0, 0, 0, 0, 0))
    q += queue.encode(0x7E, (2, *e5))
    q += queue.encode(0x8B, (apos, tpos, number, mtype, 0, 0, 1, int(battle.tera_move(actor, move)),
                             TARGET_CLASS.get(move["target"], 0), 0))
    q += queue.encode(0x37, (target, 2, dmg)) + queue.encode(0x37, (target, 5, 1))
    q += queue.encode(0x02, (target, actor, dmg, 3))
    q += queue.encode(0xD0, bytes([target, code]))
    if code == 7:
        q += queue.encode(0x8E, (1, 1, number))
    else:
        weak = code > 7
        q += queue.encode(0x8E, (1, 2 if weak else 3, number))
        q += queue.encode(0xCA, (actor, 574 if weak else 575, END) + (0,) * 7)
    if code > 7:
        q += queue.encode(0x20, (actor, 24))
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
    q += drops
    if "drain" in move:
        n, d = move["drain"]
        heal = int(dmg * n / d + 0.5)                       # the commands carry it uncapped
        if battle.hp[actor] < battle.full[actor] and heal > 0:
            battle.hp[actor] = min(battle.full[actor], battle.hp[actor] + heal)
            q += queue.encode(0xA7, (POSITION[actor], 51)) + queue.encode(0x03, (actor, heal))
            q += queue.encode(0x9A, (actor, heal)) + message(actor, 290, target)
    if knockout:
        q += boss_down(battle, actor, number)
    q += queue.encode(0xD1, bytes([1, 0]))
    if "recoil" in move:
        q += recoil(battle, actor, move, dmg, knockout)
    q += queue.encode(0x2E, (2, actor - 1))
    if target == BOSS:
        q += queue.encode(0x85, (7, dmg))
    q += queue.encode(0x7C, ())
    q += pp(battle, 0x08, actor, number)
    q += queue.encode(0x1D, (actor, tpos, mtype, 1, 0, number, number))
    q += queue.encode(0x5B, (actor, number)) * 2
    q += queue.encode(0x1E, (actor, 0))
    return q


def sand_spit(battle, b):
    """Sand Spit (Showdown abilities.ts): hit by a damaging move, it starts a sandstorm for 5 turns, with
    the start weather's commands and no message."""
    if battle.field & {"sun", "rain", "snow", "sand"}:
        raise Unsupported("Sand Spit with a weather up")
    if any(WEATHER_ABILITIES.get(x.ability, set()) & {"sand"} for x in battle.b.values()):
        raise Unsupported("an ability reads the weather")
    battle.field.add("sand")
    battle.weather_set = battle.rounds
    q = queue.encode(0x6A, (0,)) + queue.encode(0x69, (0, 4)) + queue.encode(0x79, (4, 5, 0, b, 0))
    q += queue.encode(0x88, (4, b, 0))
    return queue.encode(0x25, (b,)) + queue.encode(0xC7, (b, 0)) + q + queue.encode(0xC8, (b,))


def recoil(battle, actor, move, dmg, knockout):
    """Recoil: damage times the move's fraction, rounded half up, at least 1; 0x01 (A, A, r, 4),
    0x9a (A, -r), message 127, 0x37 (A, 4, r)."""
    n, d = move["recoil"]
    r = max(1, int(dmg * n / d + 0.5))
    if knockout or r >= battle.hp[actor] or battle.b[actor].ability in (ROCK_HEAD, MAGIC_GUARD):
        raise Unsupported("recoil that faints, after a knockout, or under Rock Head or Magic Guard")
    battle.hp[actor] -= r
    q = queue.encode(0x01, (actor, actor, r, 4)) + queue.encode(0x9A, (actor, -r & 0xFFFFFFFF))
    return q + message(actor, 127, actor) + queue.encode(0x37, (actor, 4, r))


def immune(battle, actor, target, number, move, position):
    """A damaging move the target's types are immune to: no draw; five zero groups, message 72."""
    mtype = TYPES.index(move["type"])
    q = b""
    if actor != BOSS:
        q += queue.encode(0x05, (actor, battle.slot(actor, number), 2 if battle.b[target].ability == PRESSURE else 1))
    q += pp(battle, 0x07, actor, number) + queue.encode(0xC9, (actor, 0, number, position, 1))
    q += queue.encode(0x7B, (number, battle.rounds, actor))
    for size in (20, 5, 5, 5, 19):
        q += queue.encode_group(0xCF, bytes(size))
    q += message(actor, 72, target) + queue.encode(0x52, (actor, 3)) + pp(battle, 0x08, actor, number)
    q += queue.encode(0x52, (actor, 0)) + queue.encode(0x1D, (actor, position, mtype, 0, 0, number, number))
    q += queue.encode(0x5B, (actor, number)) * 2 + queue.encode(0x1E, (actor, 0))
    return q


RAISE_TEXT, DROP_TEXT = {1: 10, 2: 17, 3: 24}, {1: 31, 2: 38}    # + stat: the stat change's message


def status_move(battle, move):
    """A status move whose only effect is stat stages, on its user or one target."""
    if move.get("isNonstandard") in ("Past", "LGPE", "Gmax", "Future"):
        raise Unsupported(f"{move['name']} is not a Scarlet / Violet move")
    if not move.get("boosts") or any(k in move for k in ("self", "volatileStatus", "status", "secondary",
                                                          "secondaries", "multihit")):
        raise Unsupported("not a damaging move")
    if set(move["callbacks"]) - ({"onModifyMove"} if move["name"] == "Growth" else set()):
        raise Unsupported(f"{move['name']}'s {move['callbacks'][0]}")
    if move["name"] == "Growth" and battle.field & {"sun"}:
        raise Unsupported("Growth in the sun")
    if move["target"] not in ("self", "normal", "any", "allAdjacentFoes"):
        raise Unsupported(f"target {move['target']}")
    return move


def raise_stats(battle, b, boosts):
    """A move's raise of its user's stages: 0x0c, 0x92, then message RAISE_TEXT + stat per stat."""
    x = battle.b[b]
    if set(ABILITIES.get(str(x.ability), ["unknown"])) & BOOST_ANSWERS or x.item not in (0, *IDLE_ITEMS) and \
            set(ITEMS.get(str(x.item), ["unknown"])) & (BOOST_ANSWERS | {"onUpdate"}):
        raise Unsupported(f"battler {b}'s ability {x.ability} or item {x.item} answers a stat raise")
    q = b""
    for key, n in boosts.items():
        stat = STATS[key]
        if n not in RAISE_TEXT or battle.stages[b][stat] + n > 6:
            raise Unsupported("a stat raise past +6 or of more than 3 stages")
        battle.stages[b][stat] += n
        q += queue.encode(0x0C, (b, stat, n)) + queue.encode(0x92, (b, stat, n, 0)) + message(b, RAISE_TEXT[n] + stat, b)
    return q


def status_use(battle, actor, number, position):
    """-> the queue for a stat-stage status move: one zero group, no hit, the hit record with the
    move's target class, the stat changes."""
    move = status_move(battle, MOVES[number])
    if number in UNSEEN_MOVES:
        raise Unsupported(f"move {number} was never probed")
    own = move["target"] == "self"
    target = actor if own else BATTLER_AT[position]
    if not own and (actor == BOSS) == (target == BOSS):
        raise Unsupported("a stat move on an ally")
    if not own and "powder" in move["flags"] and "Grass" in battle.defending(target):
        raise Unsupported("a powder move on a Grass type")
    r = battle.rng
    if type(move["accuracy"]) is int:
        if battle.stages[actor][6] or battle.stages[target][7]:
            raise Unsupported("an accuracy or evasion stage")
        if not r.chance(move["accuracy"]):
            raise Unsupported("a miss")
    apos, tpos = POSITION[actor], POSITION[target]
    q = b""
    if actor != BOSS:
        q += queue.encode(0x05, (actor, battle.slot(actor, number), 2 if not own and battle.b[target].ability == PRESSURE else 1))
    q += pp(battle, 0x07, actor, number)
    q += queue.encode(0xC9, (actor, 0, number, position, 0))
    q += queue.encode(0x7B, (number, battle.rounds, actor))
    q += queue.encode_group(0xCF, bytes(20))
    q += queue.encode(0x7E, (0, 0, 0, 0, 0, 0)) + queue.encode(0x7E, (1, 0, 0, 0, 0, 0))
    q += queue.encode(0x7E, (2, 7, 7, 7, 7, 7))
    q += queue.encode(0x8B, (apos, tpos, number, TYPES.index(move["type"]), 0, 0, 0, 0,
                             7 if own else TARGET_CLASS.get(move["target"], 0), 0))
    if own:
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
    for key, delta in boosts.items():
        stat, n = STATS[key], -delta
        if STAT_GUARD.get(b.ability) == stat:
            raise Unsupported(f"battler {target}'s ability {b.ability} guards stat {stat}")
        if n not in (1, 2) or battle.stages[target][stat] - n < -6:
            raise Unsupported("a stat drop past -6 or not 1 or 2 stages")
        battle.stages[target][stat] -= n
        q += queue.encode(0x0D, (target, stat, n)) + queue.encode(0x93, (target, stat, n, 0))
        q += message(actor, (31 if n == 1 else 38) + stat, target, stat)
    return q


def boss_down(battle, actor, number):
    """The boss knocked out, after the hit's record: the battle is won. 0x09 carries the knocking move's
    slot in its user's moveset (382 of 383 oracle knockouts)."""
    q = queue.encode(0x49, (BOSS, actor, number)) + queue.encode(0x09, (actor, battle.slot(actor, number) or 0))
    q += queue.encode(0x37, (BOSS, 1, 1)) + message(BOSS, 0, BOSS) + queue.encode(0x94, (BOSS, 0))
    q += queue.encode(0x37, (BOSS, 8, 1))
    q += b"".join(queue.encode(c, (BOSS,)) for c in (0x5F, 0x62, 0x6C, 0x5D))
    q += b"".join(queue.encode(0x41, (b, BOSS)) for b in sorted(battle.b) if b != BOSS)
    q += b"".join(queue.encode(0x33, (BOSS, k)) for k in range(14) if k != 8)
    return q + queue.encode(0x80, (BOSS,)) + queue.encode(0x29, (BOSS,)) + queue.encode(0x38, (actor,))


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
    if b.ability == STALL:
        live.discard("onFractionalPriority")
    if b.ability in PINCH or b.ability in (HUGE_POWER, PURE_POWER):
        live -= {"onModifyAtk", "onModifySpA"}             # Battle.damage applies them
    if b.ability == ADAPTABILITY and b.id != BOSS:
        live.discard("onModifySTAB")
    if b.ability == RIVALRY:
        live.discard("onBasePower")                     # Battle.damage applies it
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
    """The action's order key: its class (4 a raid action, 2 a reset, 1 a move), the move's priority, not
    Stall, then Speed (pokeldn docs/sv_raid.md, Speed ties)."""
    if e.moving():
        return 1, (MOVES.get(e.move) or {}).get("priority", 0), battle.b[e.actor].ability != STALL, battle.speed(e.actor)
    return 4 if e.kind == Entry.RAID else 2, 0, True, battle.speed(e.actor)


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
    battle.raid.pending = []
    q = queue.encode(0xB5, (0,))
    q += b"".join(queue.encode(0x51, (b, 1)) for b in sorted({e.actor for e in entries}))
    q += sort(battle, entries)
    q += b"".join(queue.encode(0x51, (e.actor, int(battle.b[e.actor].ability != STALL)))
                  for e in entries if e.kind == Entry.MOVE)
    q += sort(battle, entries) + sort(battle, entries)
    while True:
        e = next((e for e in entries if not e.done), None)
        if e is None:
            break
        e.done = True
        q += run(battle, e, entries)
        if not battle.hp[BOSS]:
            break                                           # the boss is down: nobody else moves
        raid_turn(battle, entries)
        if all(e.done for e in entries):
            break
        q += sort(battle, entries)
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
        return q + handler(battle, (e.actor, e.move), 0x72000, last=False) + use(battle, e.actor, e.move, e.position)
    if e.kind == Entry.RAID:
        return raid_action(battle, e, entries)
    if e.kind == Entry.RESET:
        return reset(battle, e.value)
    target = raid_target(battle, e.move)
    used = handler(battle, (e.actor, e.move), 0x72000, last=False) + use(battle, e.actor, e.move, target)
    end = queue.encode(0x1E, (e.actor, 0))
    return q + queue.encode(0xC1, (9, 0)) + used[:-len(end)] + queue.encode(0xC1, (9, 1)) + end


def raid_turn(battle, entries):
    """After an action, while the boss stands: an empty list of waiting raid actions is filled from the HP
    triggers; without a shield among them they join this round's actions."""
    r = battle.raid
    if r.pending or not battle.hp[BOSS]:
        return
    r.pending = r.triggers(battle)
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
            entries.append(Entry(BOSS, Entry.RAID_MOVE, move=move))
        else:
            raise Unsupported(f"raid action {action}")
        return q
    if e.sub == raid.DOUBLE:
        raise Unsupported("the double action")
    x = 0 if e.sub == raid.LOW_TIME else e.value
    return queue.encode(0x85, (e.sub, x)) + queue.encode(0xC1, (e.sub, x))


def reset(battle, action):
    """An extra action's reset: the boss's stat changes (0x0f, then 0xc2 (3, 2, 2)), or the standing
    players' stat changes (0x10 each) and abilities (condition 16 by 0x13 (b, 16, 0, b << 26 | 12, 2) for each
    whose ability can be suppressed), then 0xc2 (60, 2, 0)."""
    if action == raid.RESET_BOSS:
        if any(n > 0 for n in battle.stages[BOSS]):
            raise Unsupported("the boss's raised stats reset")
        battle.stages[BOSS] = [0] * 8
        return queue.encode(0x0F, (BOSS,)) + queue.encode(0xC2, (3, 2, 2))
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
    """The position an extra action's move aims at: none (10) for a field move, the boss (4) for its own."""
    move = MOVES.get(number) or {}
    target = move.get("target")
    if target in ("all", "allySide", "foeSide", "allies"):
        return 10
    if target in ("self", "adjacentAllyOrSelf"):
        return POSITION[BOSS]
    raise Unsupported(f"an extra action's move aimed at a player ({target})")


def round_end(battle, entries, acted, won, counted):
    """The round's end: three battler sorts (eight at a turn's end), 0xb2, 0x37 per action, the turn
    counter 0x75 when a player acted, the turn's end every fourth such round, 0xc5, 0x43 in the second
    sort's order, 0x23 for each battler that acted, 0x2d."""
    n = (battle.turns + 1) % TURN if counted else None
    # a round ends with three battler sorts, the second the 0x43 order; a turn's end with eight, the
    # fourth or fifth its residual order (no tie told them apart), the seventh the 0x43 order
    ends = [speed_order(battle, sorted(battle.b), battle.speed) for _ in range(3 if won or n != 0 else 8)]
    if won and len({battle.speed(b) for b in battle.b}) != len(battle.b):
        raise Unsupported("a speed tie in the winning round")
    q = b""
    if not won:
        q += queue.encode(0xB2, (0,))
        q += b"".join(queue.encode(0x37, (e.actor, 7, 1)) for e in entries)
        if counted:
            q += queue.encode(0x75, (3, n))
        if n == 0:
            if ends[3] != ends[4] or "sand" in battle.field and len({tuple(e) for e in ends[1:6]}) > 1:
                raise Unsupported("a speed tie at a turn's end")
            q += turn_end(battle, ends[3])
        q += queue.encode(0xC5, (1,))
    q += b"".join(queue.encode(0x43, (b,)) for b in ends[1 if won or n != 0 else 6] if battle.hp[b])
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
    key = lambda a: ((MOVES.get(a[1]) or {}).get("priority", 0), battle.b[a[0]].ability != STALL, battle.speed(a[0]))
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
    battle.raid.pending = []
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
    reads it and it does not end in this round; sand also raises a Rock type's Special Defense
    (Battle.damage); terrain is refused."""
    field = battle.field - {"sun", "rain", "snow", "sand"}
    if field:
        raise Unsupported(f"{sorted(field)[0]} on the field")
    if not battle.field:
        return
    if battle.rounds - battle.weather_set + 1 >= WEATHER_TURNS:
        raise Unsupported("the weather ends")
    if any(WEATHER_ABILITIES.get(b.ability, set()) & battle.field for b in battle.b.values()):
        raise Unsupported("an ability reads the weather")
    for actor, number, position in acts:
        move = MOVES.get(number) or {"type": "", "category": ""}
        if move["type"] in ("Fire", "Water") and battle.field & {"sun", "rain"}:
            raise Unsupported("a move the weather changes")
        target = BATTLER_AT.get(position)
        if "snow" in battle.field and move["category"] == "Physical" and target and \
                "Ice" in battle.defending(target):
            raise Unsupported("an Ice-type target in snow")


TURN = 4                    # a turn ends every fourth command round
# the end-of-turn residual kinds, in the order 0x19 runs them
RESIDUALS = (36, 21, 18, 5, 4, 9, 10, 8, 46, 43, 48, 11, 12, 23, 13, 31, 33, 15, 19, 29, 30, 38, 37, 39, 40, 41,
             24, 45, 14, 20, 1, 2, 3, 7, 6, 16, 17, 22, 25, 26, 27, 28, 32, 34, 35)
LEFTOVERS = 234


def turn_end(battle, order):
    """A turn's end with nothing to resolve: 0xc5 (0), 0x50 (0), 0x19 (b, kind) for each residual kind
    over the battlers in `order` (speed order), 0x44 (1 to 13)."""
    for b in battle.b.values():
        if b.item == LEFTOVERS and battle.hp[b.id] < battle.full[b.id]:
            raise Unsupported("Leftovers at the turn's end")
        live = callbacks(b) & {"onResidual"}
        if live or battle.field - {"sand"}:
            raise Unsupported(f"battler {b.id}'s residual at the turn's end")
    q = queue.encode(0xC5, (0,)) + queue.encode(0x50, (0,))
    if "sand" in battle.field:
        q += sandstorm(battle, order)
    q += b"".join(queue.encode(0x19, (b, k)) for k in RESIDUALS for b in order if battle.hp[b])
    return q + b"".join(queue.encode(0x44, (k,)) for k in range(1, 14))


SAFETY_GOGGLES = 650


def sandstorm(battle, order):
    """Sandstorm's damage at a turn's end (Showdown conditions.ts): a sixteenth of the maximum HP, at
    least 1, to each battler in speed order that is not Rock, Ground or Steel; message 133, 0xa7, 0x01, 0x9a."""
    q = b""
    for i in order:
        b = battle.b[i]
        if not battle.hp[i] or set(battle.defending(i)) & {"Rock", "Ground", "Steel"} or b.item == SAFETY_GOGGLES:
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
        q += message(i, 133, i) + queue.encode(0xA7, (POSITION[i], 14)) + queue.encode(0x01, (i, 5, dmg, 1))
        q += queue.encode(0x9A, (i, -dmg & 0xFFFFFFFF))
    return q


def handler(battle, act, base, last=True):
    """0x5a (b, M, base + speed) and, after a pass, 0x5b (b, M), for a move that registers a handler."""
    actor, number = act[0], act[1]
    if number not in HANDLER_MOVES:
        return b""
    q = queue.encode(0x5A, (actor, number, base + battle.speed(actor)))
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
