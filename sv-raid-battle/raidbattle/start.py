"""The battle-start message (0x11): its body is a command queue (pokeldn docs/sv_raid.md, The server
command queue). Each battler is sent out in id order; then the switch-in events run in speed order."""
from raidbattle import queue
from raidbattle.battlers import QUIET_ABILITIES
from raidbattle.server import Unsupported

PRESSURE, OWN_TEMPO, INNER_FOCUS, INTIMIDATE, DEFIANT, FRISK = 46, 20, 39, 22, 128, 119
UNNERVE, ANTICIPATION = 127, 107
MESSAGE_UNNERVE, MESSAGE_ANTICIPATION = 679, 145
BOSS = 2
ATK = 1
# a target's answer to Intimidate: Own Tempo blocks it, Defiant raises Attack 2; these are refused
INTIMIDATE_REFUSED = frozenset({12, 29, 39, 52, 73, 86, 113, 126, 155, 172, 230, 240, 275, 283})
# switch-in abilities measured on the oracle corpus: ability -> its event
ANNOUNCED = {104: 147, 164: 167, 163: 168, 213: 446}        # Mold Breaker, Teravolt, Turboblaze, Comatose
WEATHER_LOCK, MESSAGE_WEATHER_LOCK = frozenset({13, 76}), 590   # Cloud Nine, Air Lock
# raises its own stat one stage: ability -> (stat, message, the 0x22 that follows it or None)
SELF_BOOST = {234: (1, 11, 4), 235: (2, 12, 5), 302: (1, 1063, None), 303: (4, 1064, None), 304: (2, 1065, None)}
DOWNLOAD, SUPERSWEET_SYRUP, EVASION = 88, 306, 7
# weather: ability -> (weather, message after it or None); 1 sun, 2 rain, 3 snow, 4 sand
WEATHER = {70: (1, None), 2: (2, None), 117: (3, None), 45: (4, None), 288: (1, 1041)}
# terrain: ability -> (terrain, message, its command); 2 Misty, 3 Electric, 4 Psychic
TERRAIN = {228: (2, 706, 0xCA), 226: (3, 708, 0xCA), 227: (4, 828, 0xCA), 289: (3, 1043, 0xCB)}
# quiet at switch-in in the oracle corpus, beyond battlers.QUIET_ABILITIES
QUIET_TOO = frozenset({21, 40, 73, 90, 134, 147, 179, 183, 192, 205, 209, 230, 240, 264, 275, 293, 308})
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


def ability_event(b, body, shown=0):
    """An ability's activation: 0x25 and 0xc7 open it, 0xc8 closes it; Unnerve shows its id in 0xc7."""
    return queue.encode(0x25, (b.id,)) + queue.encode(0xC7, (b.id, shown)) + body + queue.encode(0xC8, (b.id,))


def unnerve(b):
    """Unnerve runs before every speed-ordered event; message 679 names the foes' side (1 the boss's)."""
    args = (b.id, MESSAGE_UNNERVE, int(b.id != BOSS), END)
    return ability_event(b, queue.encode(0xCA, args + (0,) * (10 - len(args))), UNNERVE)


def anticipation(b, battlers, battle):
    """Anticipation shudders (message 145) when a foe knows a damaging move super effective on it, or
    a one-hit KO move (Showdown abilities.ts, anticipation)."""
    from raidbattle import rounds
    if battle is None:
        raise Unsupported("Anticipation needs the battlers' types")
    for f in foes(b, battlers):
        for m in f.moves:
            move = rounds.MOVES.get(m)
            if not m or move is None:
                continue
            if "ohko" in move["callbacks"] or (move["category"] != "Status" and battle.effectiveness(move["type"], b.id) > 1):
                return ability_event(b, message(b.id, MESSAGE_ANTICIPATION, b.id))
    return b""


def side_message(b, text):
    """Command 0xca: a message about `b` with no other parameter."""
    return queue.encode(0xCA, (b.id, text, END) + (0,) * 7)


def boost(b, stat, text, stages):
    stages[b.id][stat] += 1
    return queue.encode(0x0C, (b.id, stat, 1)) + queue.encode(0x92, (b.id, stat, 1, 0)) + message(b.id, text, b.id)


def download(b, battlers, stages):
    """Download raises Attack when the foes' Defense totals less than their Special Defense, else
    Special Attack (Showdown abilities.ts, download)."""
    fs = foes(b, battlers)
    stat = 1 if sum(f.stats[2] for f in fs) < sum(f.stats[5] for f in fs) else 3
    return ability_event(b, boost(b, stat, 10 + stat, stages))


def syrup(b, battlers, stages):
    """Supersweet Syrup: message 1066, then each foe in id order loses 1 evasion (message 38); 0x22 (b, 8)."""
    out = message(b.id, 1066, b.id)
    for f in foes(b, battlers):
        if f.ability in INTIMIDATE_REFUSED | {OWN_TEMPO, DEFIANT}:
            raise Unsupported(f"battler {f.id}'s ability {f.ability} answers Supersweet Syrup")
        out += queue.encode(0x0D, (f.id, EVASION, 1)) + queue.encode(0x93, (f.id, EVASION, 1, 0))
        out += message(b.id, 38, f.id, EVASION)
        stages[f.id][EVASION] -= 1
    return ability_event(b, out) + queue.encode(0x22, (b.id, 8))


def weather(b, field):
    w, text = WEATHER[b.ability]
    field.add("weather")
    out = queue.encode(0x6A, (0,)) + queue.encode(0x69, (0, w)) + queue.encode(0x79, (w, 5, 0, b.id, 0))
    out += queue.encode(0x88, (w, b.id, 0))
    return ability_event(b, out + (message(b.id, text, b.id) if text else b""))


def terrain(b, field):
    t, text, command = TERRAIN[b.ability]
    field.add("terrain")
    out = queue.encode(0x32, (t, 0, 42, b.id)) + queue.encode(0x6A, (8,)) + queue.encode(0xB2, (0,))
    out += queue.encode(0xAA, (t,)) + queue.encode(0x69, (8, t))
    out += side_message(b, text) if command == 0xCA else message(b.id, text, b.id)
    return ability_event(b, out)


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


def switch_in(b, battlers, stages, battle=None):
    out = b""
    field = battle.field if battle is not None else set()
    if b.ability == ANTICIPATION:
        out += anticipation(b, battlers, battle)
    elif b.ability == UNNERVE:
        pass
    elif b.ability == FRISK:
        out += frisk(b, battlers)
    elif b.ability == INTIMIDATE:
        out += ability_event(b, intimidate(b, battlers, stages))
    elif b.ability == PRESSURE:
        out += ability_event(b, message(b.id, MESSAGE_PRESSURE, b.id))
    elif b.ability in ANNOUNCED:
        out += ability_event(b, message(b.id, ANNOUNCED[b.ability], b.id))
    elif b.ability in WEATHER_LOCK:
        out += ability_event(b, side_message(b, MESSAGE_WEATHER_LOCK))
    elif b.ability in SELF_BOOST:
        stat, text, after = SELF_BOOST[b.ability]
        out += ability_event(b, boost(b, stat, text, stages))
        out += queue.encode(0x22, (b.id, after)) if after else b""
    elif b.ability == DOWNLOAD:
        out += download(b, battlers, stages)
    elif b.ability == SUPERSWEET_SYRUP:
        out += syrup(b, battlers, stages)
    elif b.ability in WEATHER:
        out += weather(b, field)
    elif b.ability in TERRAIN:
        out += terrain(b, field)
    elif b.ability not in QUIET_ABILITIES | QUIET_TOO | {OWN_TEMPO, INNER_FOCUS}:
        raise Unsupported(f"battler {b.id}'s ability {b.ability} acts on switch-in")
    if b.item == AIR_BALLOON:
        out += message(b.id, MESSAGE_AIR_BALLOON, b.id)
    elif b.item not in QUIET_ITEMS:
        raise Unsupported(f"battler {b.id}'s item {b.item} is not known at switch-in")
    return out


def body(battlers, stages=None, battle=None):
    """-> the 0x11 body for {id: Battler}; `stages` ({id: [0] * 8}) gets the stat stages it sets;
    `battle` (rounds.Battle) gives the types Anticipation reads."""
    stages = stages if stages is not None else {i: [0] * 8 for i in battlers}
    ordered = sorted(battlers.values(), key=lambda b: -b.speed)
    acting = [b for b in ordered if switch_in(b, battlers, {i: [0] * 8 for i in battlers}, battle)]
    speeds = [b.speed for b in acting]
    if len(set(speeds)) != len(speeds):
        raise Unsupported("a speed tie among switch-in events")
    out = b"".join(send_out(battlers[i]) for i in sorted(battlers))
    if sum(b.ability in WEATHER or b.ability in TERRAIN or b.ability in WEATHER_LOCK for b in acting) > 1:
        raise Unsupported("more than one weather or terrain ability")
    unnerving = [b for b in ordered if b.ability == UNNERVE]
    if len(unnerving) > 1:
        raise Unsupported("more than one Unnerve")
    out += b"".join(unnerve(b) for b in unnerving)
    out += b"".join(switch_in(b, battlers, stages, battle) for b in acting)
    return out + queue.encode(0x2B, (0,))
