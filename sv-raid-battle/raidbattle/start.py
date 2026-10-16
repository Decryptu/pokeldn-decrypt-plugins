"""The battle-start message (0x11): its body is a command queue (pokeldn docs/sv_raid.md, The server
command queue). Each battler is sent out in id order; then the switch-in events run in speed order."""
from raidbattle import queue
from raidbattle.battlers import QUIET_ABILITIES
from raidbattle.server import Unsupported

PRESSURE, OWN_TEMPO, INNER_FOCUS = 46, 20, 39
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


def switch_in(b):
    out = b""
    if b.ability == PRESSURE:
        out += ability_event(b, message(b.id, MESSAGE_PRESSURE, b.id))
    elif b.ability not in QUIET_ABILITIES | {OWN_TEMPO, INNER_FOCUS}:
        raise Unsupported(f"battler {b.id}'s ability {b.ability} acts on switch-in")
    if b.item == AIR_BALLOON:
        out += message(b.id, MESSAGE_AIR_BALLOON, b.id)
    elif b.item not in QUIET_ITEMS:
        raise Unsupported(f"battler {b.id}'s item {b.item} is not known at switch-in")
    return out


def body(battlers):
    """-> the 0x11 body for {id: Battler}."""
    ordered = sorted(battlers.values(), key=lambda b: -b.speed)
    acting = [b for b in ordered if switch_in(b)]
    speeds = [b.speed for b in acting]
    if len(set(speeds)) != len(speeds):
        raise Unsupported("a speed tie among switch-in events")
    out = b"".join(send_out(battlers[i]) for i in sorted(battlers))
    out += b"".join(switch_in(b) for b in acting)
    return out + queue.encode(0x2B, (0,))
