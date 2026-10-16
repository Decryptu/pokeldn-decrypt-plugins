"""A round (message 0x15): the acting slot's action block, then the command queue its actions produce
(pokeldn docs/sv_raid.md, A move in the round queue; Damage and draws per move). Only plain moves are
built: a single-target damaging move with no effect that changes the battle beyond its damage. Anything
else raises Unsupported."""
import json
import os
import struct

from raidbattle import queue
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
        out.append((actor & 0xFFFFFFFF, (word >> 8) & 0xFFFF, (word >> 4) & 0xF))
    return out


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
        return 1.5 if move_type in self.types[actor] else 1.0

    def damage(self, actor, target, move, roll, crit):
        a, d = self.b[actor], self.b[target]
        physical = move["category"] == "Physical"
        att = a.stats[1] if physical else a.stats[4]
        dfn = d.stats[2] if physical else d.stats[5]
        base = (2 * a.level // 5 + 2) * move["basePower"] * att // dfn // 50 + 2
        if crit:
            base = modify(base, 1.5)
        x = base * (100 - roll) // 100
        x = modify(x, self.stab(actor, move["type"]))
        e = self.effectiveness(move["type"], target)
        return int(x * e) if e >= 1 else int(x * e)


def plain(move):
    if move is None or move["category"] == "Status" or not move.get("basePower"):
        raise Unsupported("not a damaging move")
    for key in ("multihit", "drain", "recoil", "self", "secondaries"):
        if key in move:
            raise Unsupported(f"a move with {key}")
    if move["target"] != "normal" or move.get("priority", 0):
        raise Unsupported(f"target {move['target']} or priority")
    if move.get("critRatio", 1) not in CRIT_DRAW:
        raise Unsupported("crit stage")
    sec = move.get("secondary")
    if sec and set(sec) - {"chance", "status", "volatileStatus", "boosts"}:
        raise Unsupported("secondary")
    return move


def use(battle, actor, number, position, order):
    """-> the queue for one move use, and the order list gets the actor."""
    move = plain(MOVES.get(number))
    target = BATTLER_AT[position]
    r = battle.rng
    if isinstance(move["accuracy"], int) and not r.chance(move["accuracy"]):
        raise Unsupported("a miss")
    crit = r.below(CRIT_DRAW[move.get("critRatio", 1)]) == 0
    roll = r.below(16)
    if crit:
        raise Unsupported("a critical hit")
    sec = move.get("secondary")
    if sec and r.chance(sec["chance"]):
        raise Unsupported("a secondary effect")
    e = battle.effectiveness(move["type"], target)
    if e not in EFFECTIVENESS or e > 1:
        raise Unsupported(f"effectiveness {e}")
    code = EFFECTIVENESS[e]
    dmg = battle.damage(actor, target, move, roll, crit)
    if dmg >= battle.hp[target]:
        raise Unsupported("a knockout")
    battle.hp[target] -= dmg
    mtype, cat = TYPES.index(move["type"]), 1 if move["category"] == "Physical" else 2
    apos, tpos = POSITION[actor], POSITION[target]
    e5 = [7] * 5
    e5[tpos] = code
    hit = [0] * 5
    hit[tpos] = 1
    q = b""
    if actor != BOSS:
        q += queue.encode(0x05, (actor, 0, 1))
    q += queue.encode(0x07, (actor, 0))
    q += queue.encode(0xC9, (actor, 0, number, tpos, 0))
    q += queue.encode(0x7B, (number, battle.rounds, actor))
    for size in (20, 5, 5, 5, 19, 20):
        q += queue.encode_group(0xCF, bytes(size))
    q += queue.encode(0x7E, (0, *hit))
    q += queue.encode(0x7E, (1, 0, 0, 0, 0, 0))
    q += queue.encode(0x7E, (2, *e5))
    q += queue.encode(0x8B, (apos, tpos, number, mtype, 0, 0, 1, 0, 0, 0))
    q += queue.encode(0x37, (target, 2, dmg)) + queue.encode(0x37, (target, 5, 1))
    q += queue.encode(0x02, (target, actor, dmg, 3))
    q += queue.encode(0xD0, bytes([target, code]))
    if code == 7:
        q += queue.encode(0x8E, (1, 1, number))
    else:
        q += queue.encode(0x8E, (1, 3, number)) + queue.encode(0xCA, (actor, 575, END) + (0,) * 7)
    q += queue.encode(0x42, (target, actor, apos, mtype, cat, number, dmg))
    q += queue.encode(0xD1, bytes([1, 0]))
    q += queue.encode(0x2E, (2, actor - 1))
    if target == BOSS:
        q += queue.encode(0x85, (7, dmg))
    q += queue.encode(0x7C, ())
    q += queue.encode(0x08, (actor, 0))
    q += queue.encode(0x1D, (actor, tpos, mtype, 1, 0, number, number))
    q += queue.encode(0x5B, (actor, number)) * 2
    q += queue.encode(0x1E, (actor, 0))
    order.append(actor)
    return q


def build(battle, slot, command):
    """-> (the round body for `slot`'s command, whether it wins)."""
    acts = actions(command)
    for actor, number, _ in acts:
        if number in HANDLER_MOVES:
            raise Unsupported(f"move {number} registers a handler")
    speed = lambda a: battle.b[a[0]].speed
    by_id = sorted(acts, key=lambda a: a[0])
    ordered = sorted(acts, key=lambda a: -speed(a))
    if len({speed(a) for a in acts}) != len(acts):
        raise Unsupported("a speed tie")
    q = queue.encode(0xB5, (0,))
    q += b"".join(queue.encode(0x51, (a[0], 1)) for a in by_id)
    q += b"".join(queue.encode(0x51, (a[0], 1)) for a in ordered)
    order = []
    for actor, number, position in ordered:
        q += use(battle, actor, number, position, order)
    q += queue.encode(0xB2, (0,))
    q += b"".join(queue.encode(0x37, (a, 7, 1)) for a in order)
    q += queue.encode(0x75, (3, battle.rounds + 1))
    q += queue.encode(0xC5, (1,))
    q += b"".join(queue.encode(0x43, (b,)) for b in ROUND_END_ORDER(battle))
    acted = range(1, 6) if battle.rounds == 0 else sorted(order)
    q += b"".join(queue.encode(0x23, (b,)) for b in acted)
    q += queue.encode(0x2D, (0,))
    battle.rounds += 1
    body = action_block(slot, command) + struct.pack("<I", len(q)) + q
    return body + bytes(BODY - len(body)), False


def ROUND_END_ORDER(battle):
    """The battlers in speed order."""
    speeds = [battle.b[b].speed for b in battle.b]
    if len(set(speeds)) != len(speeds):
        raise Unsupported("a speed tie at the round's end")
    return sorted(battle.b, key=lambda b: -battle.b[b].speed)


HANDLER_MOVES = frozenset()
