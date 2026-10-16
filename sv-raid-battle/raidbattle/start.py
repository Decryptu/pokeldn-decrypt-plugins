"""The battle-start message (0x11): its body is a command queue (pokeldn docs/sv_raid.md, The server
command queue). Each battler is sent out in id order; then the switch-in events run in speed order."""
from raidbattle import queue
from raidbattle.battlers import QUIET_ABILITIES
from raidbattle.server import Unsupported

PRESSURE, OWN_TEMPO, INNER_FOCUS, INTIMIDATE, DEFIANT, FRISK = 46, 20, 39, 22, 128, 119
BOSS = 2
ATK = 1
# a target's answer to Intimidate: Own Tempo blocks it, Defiant raises Attack 2; these are refused
INTIMIDATE_REFUSED = frozenset({12, 29, 39, 73, 113, 155, 172, 230, 275, 283})
AIR_BALLOON = 541
QUIET_ITEMS = frozenset({0, 234, 247, 270, 275})
MESSAGE_PRESSURE, MESSAGE_AIR_BALLOON = 162, 137
END = 0xFFFF0000


def message(battler, text, *params):
    """Command 0xcb: a battle message `text` about `battler`, its parameters ended by END."""
    args = (battler, text, *params, END)
    return queue.encode(0xCB, args + (0,) * (10 - len(args)))


def send_out(b):
    return b"".join([queue.encode(0x3D, (b.id - 1,)), queue.encode(0x16, (b.id - 1, 0, 0, 0)),
                     queue.encode(0x5E, (b.id, b.ability)), queue.encode(0x61, (b.id,)),
                     queue.encode(0x6B, (b.id,)), queue.encode(0x4E, (b.id,))])


def ability_event(b, body):
    """An ability's activation: 0x25 and 0xc7 open it, 0xc8 closes it."""
    return queue.encode(0x25, (b.id,)) + queue.encode(0xC7, (b.id, 0)) + body + queue.encode(0xC8, (b.id,))


def foes(b, battlers):
    return [x for i, x in sorted(battlers.items()) if (i == BOSS) != (b.id == BOSS)]


def intimidate(b, battlers, stages):
    """Intimidate: each foe in id order loses 1 Attack, through 0x0d, 0x93 and message 32."""
    out = b""
    for f in foes(b, battlers):
        if f.ability in INTIMIDATE_REFUSED:
            raise Unsupported(f"battler {f.id}'s ability {f.ability} answers Intimidate")
        if f.ability == OWN_TEMPO:
            out += ability_event(f, message(f.id, 69, f.id))
            continue
        out += queue.encode(0x0D, (f.id, ATK, 1)) + queue.encode(0x93, (f.id, ATK, 1, 0))
        out += message(b.id, 32, f.id, ATK)
        stages[f.id][ATK] -= 1
        if f.ability == DEFIANT:
            out += ability_event(f, queue.encode(0x0C, (f.id, ATK, 2)) + queue.encode(0x92, (f.id, ATK, 2, 0))
                                 + message(f.id, 18, f.id))
            stages[f.id][ATK] += 2
    return out


def frisk(b, battlers):
    """Frisk: the first foe holding an item in id order is named with message 146, each later one 752."""
    held = [f for f in foes(b, battlers) if f.item]
    if not held:
        return b""
    out = message(0, 146, b.id, held[0].id, held[0].item)
    for f in held[1:]:
        args = (0, 752, f.id, f.item, END)
        out += queue.encode(0xCA, args + (0,) * (10 - len(args)))
    return ability_event(b, out)


def switch_in(b, battlers, stages):
    out = b""
    if b.ability == FRISK:
        out += frisk(b, battlers)
    elif b.ability == INTIMIDATE:
        out += ability_event(b, intimidate(b, battlers, stages))
    elif b.ability == PRESSURE:
        out += ability_event(b, message(b.id, MESSAGE_PRESSURE, b.id))
    elif b.ability not in QUIET_ABILITIES | {OWN_TEMPO, INNER_FOCUS}:
        raise Unsupported(f"battler {b.id}'s ability {b.ability} acts on switch-in")
    if b.item == AIR_BALLOON:
        out += message(b.id, MESSAGE_AIR_BALLOON, b.id)
    elif b.item not in QUIET_ITEMS:
        raise Unsupported(f"battler {b.id}'s item {b.item} is not known at switch-in")
    return out


def body(battlers, stages=None):
    """-> the 0x11 body for {id: Battler}; `stages` ({id: [0] * 8}) gets the stat stages it sets."""
    stages = stages if stages is not None else {i: [0] * 8 for i in battlers}
    ordered = sorted(battlers.values(), key=lambda b: -b.speed)
    acting = [b for b in ordered if switch_in(b, battlers, {i: [0] * 8 for i in battlers})]
    speeds = [b.speed for b in acting]
    if len(set(speeds)) != len(speeds):
        raise Unsupported("a speed tie among switch-in events")
    out = b"".join(send_out(battlers[i]) for i in sorted(battlers))
    out += b"".join(switch_in(b, battlers, stages) for b in acting)
    return out + queue.encode(0x2B, (0,))
