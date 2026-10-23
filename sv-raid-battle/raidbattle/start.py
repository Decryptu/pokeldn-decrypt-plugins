"""The battle-start message (0x11): its body is a command queue (pokeldn docs/sv_raid.md, The server
command queue). Each battler is sent out in id order; then the switch-in events run in speed order."""
from raidbattle import queue
from raidbattle.battlers import QUIET_ABILITIES
from raidbattle.server import Unsupported

PRESSURE, OWN_TEMPO, INNER_FOCUS, INTIMIDATE, DEFIANT, FRISK = 46, 20, 39, 22, 128, 119
CONTRARY, COMPETITIVE, MIRROR_ARMOR, SPA = 126, 172, 240, 3
UNNERVE, ANTICIPATION = 127, 107
MESSAGE_UNNERVE, MESSAGE_ANTICIPATION = 679, 145
BOSS = 2
ATK = 1
# a target's answer to Intimidate: Own Tempo and Inner Focus block it, Contrary turns it into a raise,
# Defiant and Competitive raise a stat 2, Mirror Armor sends it back; these are refused
INTIMIDATE_REFUSED = frozenset({12, 29, 52, 73, 86, 113, 155, 230, 275, 283})
INTIMIDATE_ANSWERS = INTIMIDATE_REFUSED | {OWN_TEMPO, INNER_FOCUS, CONTRARY, DEFIANT, COMPETITIVE, MIRROR_ARMOR}
# a drop that only Intimidate's answers are known for
SYRUP_REFUSED = INTIMIDATE_ANSWERS
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
TRACE, IMPOSTER, MESSAGE_TRANSFORM = 36, 150, 213
# Showdown abilities.ts, flags failstrace and notrace: never copied
UNTRACEABLE = frozenset({36, 59, 121, 122, 149, 150, 161, 176, 197, 208, 209, 210, 211, 213, 222, 223, 225, 248, 256,
                         258, 266, 267, 278, 279, 281, 282, 301, 302, 303, 304, 307, 308, 309, 310})
SHIELDS_DOWN, MINIOR_CORE = 197, 7          # Minior's forms 0-6 Meteor, 7-13 Core; Meteor above half HP is quiet
QUIET_ITEMS = frozenset({0, 234, 247, 270, 275})
MESSAGE_PRESSURE, MESSAGE_AIR_BALLOON = 162, 137
END = 0xFFFF0000


def message(battler, text, *params):
    """Command 0xcb: a battle message `text` about `battler`, its parameters ended by END."""
    args = (battler, text, *params, END)
    return queue.encode(0xCB, args + (0,) * (10 - len(args)))


def send_out(b):
    return b"".join([queue.encode(0x3D, (b.id - 1,)), queue.encode(0x16, (b.id - 1, 0, 0, 0)),
                     queue.encode(0x5E, (b.id, b.base_ability or b.ability)), queue.encode(0x61, (b.id,)),
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
        if f.ability in SYRUP_REFUSED:
            raise Unsupported(f"battler {f.id}'s ability {f.ability} answers Supersweet Syrup")
        out += queue.encode(0x0D, (f.id, EVASION, 1)) + queue.encode(0x93, (f.id, EVASION, 1, 0))
        out += message(b.id, 38, f.id, EVASION)
        stages[f.id][EVASION] -= 1
    return ability_event(b, out) + queue.encode(0x22, (b.id, 8))


WEATHER_NAMES = {1: "sun", 2: "rain", 3: "snow", 4: "sand"}
PROTOSYNTHESIS, QUARK_DRIVE = 281, 282


def weather(b, field):
    w, text = WEATHER[b.ability]
    field.add(WEATHER_NAMES[w])
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


def lower_attack(source, target, stages):
    stages[target.id][ATK] -= 1
    return queue.encode(0x0D, (target.id, ATK, 1)) + queue.encode(0x93, (target.id, ATK, 1, 0)) + \
        message(source.id, 32, target.id, ATK)


def raise_stat(b, stat, n, text, stages, source=None):
    stages[b.id][stat] += n
    return queue.encode(0x0C, (b.id, stat, n)) + queue.encode(0x92, (b.id, stat, n, 0)) + \
        message((source or b).id, text, b.id)


def intimidate(b, battlers, stages):
    """Intimidate: each foe in id order loses 1 Attack, through 0x0d, 0x93 and message 32. A foe's
    answer (Showdown abilities.ts) runs at once, inside the Intimidate event."""
    out = b""
    for f in foes(b, battlers):
        if f.ability in INTIMIDATE_REFUSED:
            raise Unsupported(f"battler {f.id}'s ability {f.ability} answers Intimidate")
        if f.ability in (OWN_TEMPO, INNER_FOCUS):
            out += ability_event(f, message(f.id, 69, f.id))
        elif f.ability == CONTRARY:
            out += raise_stat(f, ATK, 1, 11, stages, source=b)
        elif f.ability == MIRROR_ARMOR:
            if b.ability != INTIMIDATE or any(x.ability == MIRROR_ARMOR for x in foes(f, battlers)):
                raise Unsupported(f"battler {f.id}'s Mirror Armor sends Intimidate back")
            out += ability_event(f, lower_attack(f, b, stages))
        else:
            out += lower_attack(b, f, stages)
            if f.ability == DEFIANT:
                out += ability_event(f, raise_stat(f, ATK, 2, 18, stages))
            elif f.ability == COMPETITIVE:
                out += ability_event(f, raise_stat(f, SPA, 2, 20, stages))
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


def trace(battlers, battle):
    """Trace copies a foe's ability once, before the switch-in events: a player's the boss's, the boss's
    one of the players it can copy, picked by below(N) in id order (Showdown abilities.ts, trace). Only an
    ability quiet at switch-in is copied."""
    for b in sorted(battlers.values(), key=lambda b: b.id):
        if b.ability != TRACE or b.base_ability:
            continue
        players = [battlers[i] for i in sorted(battlers) if i != BOSS and battlers[i].ability not in UNTRACEABLE]
        if b.id != BOSS:
            source = battlers[BOSS]
        elif battle is None:
            raise Unsupported("the boss's Trace needs the battle's generator")
        elif not players:
            continue
        else:
            source = players[battle.rng.below(len(players))]
        if source.ability not in QUIET_ABILITIES | QUIET_TOO | {OWN_TEMPO, INNER_FOCUS} or source.ability in UNTRACEABLE:
            raise Unsupported(f"battler {b.id}'s Trace copies ability {source.ability}")
        b.base_ability, b.ability, b.traced_from = TRACE, source.ability, source.id


def traced(b):
    """Trace's event: 0x89 names it, message 128 the source, 0x24 and 0x5e set the copied ability."""
    a = b.ability
    body = queue.encode(0x89, (b.id, TRACE, a)) + message(b.id, 128, b.traced_from, a) + queue.encode(0x5F, (b.id,))
    body += queue.encode(0x24, (b.id, a)) + queue.encode(0x5E, (b.id, a)) + queue.encode(0xC8, (b.id,))
    return ability_event(b, body, a)


def imposter(battlers):
    """The boss's Imposter transforms it into battler 1, measured on the oracle corpus (9 battles of 9),
    before the switch-in events; the copied ability then acts as its own."""
    b, source = battlers[BOSS], battlers[1]
    if b.ability != IMPOSTER or b.base_ability:
        return
    if source.ability in UNTRACEABLE or source.base_ability:
        raise Unsupported(f"battler {b.id}'s Imposter copies ability {source.ability}")
    b.base_ability, b.ability, b.transformed = IMPOSTER, source.ability, source.id


def transformed(b):
    """Imposter's event: 0x59 names the copied battler, 0x5e sets its ability, message 213."""
    body = queue.encode(0x59, (b.id, b.transformed)) + queue.encode(0x5D, (b.id,)) + queue.encode(0x5F, (b.id,))
    body += queue.encode(0x5E, (b.id, b.ability)) + queue.encode(0xAF, (b.id, b.transformed))
    return ability_event(b, body + message(b.id, MESSAGE_TRANSFORM, b.id, b.transformed))


def switch_in(b, battlers, stages, battle=None):
    out = b""
    if b.base_ability == TRACE:
        out += traced(b)
    elif b.base_ability == IMPOSTER:
        out += transformed(b) + ability_in(b, battlers, stages, battle)
    else:
        out += ability_in(b, battlers, stages, battle)
    if b.item == AIR_BALLOON:
        out += message(b.id, MESSAGE_AIR_BALLOON, b.id)
    elif b.item not in QUIET_ITEMS:
        raise Unsupported(f"battler {b.id}'s item {b.item} is not known at switch-in")
    return out


def ability_in(b, battlers, stages, battle):
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
    elif b.ability == SHIELDS_DOWN:
        if b.form >= MINIOR_CORE or 2 * b.hp <= b.stats[0]:
            raise Unsupported(f"battler {b.id}'s Shields Down changes its form")   # Core form: its stats change
    elif b.ability not in QUIET_ABILITIES | QUIET_TOO | {OWN_TEMPO, INNER_FOCUS}:
        raise Unsupported(f"battler {b.id}'s ability {b.ability} acts on switch-in")
    return out


def body(battlers, stages=None, battle=None):
    """-> the 0x11 body for {id: Battler}; `stages` ({id: [0] * 8}) gets the stat stages it sets;
    `battle` (rounds.Battle) gives the types Anticipation reads."""
    stages = stages if stages is not None else {i: [0] * 8 for i in battlers}
    if battle is not None:                                  # sorted before Trace draws, and once: the body is built twice
        from raidbattle.rounds import speed_order
        if battle.switch_order is None:
            battle.switch_order = speed_order(battle, sorted(battlers), lambda i: battlers[i].speed)
        ordered = [battlers[i] for i in battle.switch_order]
    else:
        ordered = sorted(battlers.values(), key=lambda b: -b.speed)
    trace(battlers, battle)
    imposter(battlers)
    acting = [b for b in ordered if switch_in(b, battlers, {i: [0] * 8 for i in battlers}, battle)]
    if battle is None and len({b.speed for b in acting}) != len(acting):
        raise Unsupported("a speed tie among switch-in events without the battle's generator")
    out = b"".join(send_out(battlers[i]) for i in sorted(battlers))
    if sum(b.ability in WEATHER or b.ability in TERRAIN or b.ability in WEATHER_LOCK for b in acting) > 1:
        raise Unsupported("more than one weather or terrain ability")
    abilities = {b.ability for b in battlers.values()}
    if PROTOSYNTHESIS in abilities and any(WEATHER.get(b.ability, (0,))[0] == 1 for b in acting) or \
            QUARK_DRIVE in abilities and any(TERRAIN.get(b.ability, (0,))[0] == 3 for b in acting):
        raise Unsupported("Protosynthesis or Quark Drive in its weather or terrain")
    unnerving = [b for b in ordered if b.ability == UNNERVE]
    if len(unnerving) > 1:
        raise Unsupported("more than one Unnerve")
    out += b"".join(unnerve(b) for b in unnerving)
    out += b"".join(switch_in(b, battlers, stages, battle) for b in acting)
    return out + queue.encode(0x2B, (0,))
