"""The raid boss's action profile and the record the battle keeps of it: the shield, the six extra actions,
the double action and the time-left action, each a threshold on the boss's HP share or on the time left
(pokeldn docs/sv_raid.md, The boss's actions). Nothing here draws a random number."""

SHIELD, SHIELD_END, LOW_TIME, EXTRA, DOUBLE = 1, 2, 3, 4, 5
RESET_BOSS, RESET_PLAYERS, MOVE, DRAIN_ORB = 1, 2, 3, 4      # an extra action's kind
BY_TIME, BY_HP = 1, 2                                         # an extra action's timing


class Raid:
    """The profile (37 words at RaidPoint +0x4c) and the record: shield state, fired actions and the list
    of actions waiting to run (at most four)."""

    def __init__(self, profile, limit):
        self.coefficient = profile[0]
        (self.shield_hp, self.shield_time, _, self.shield_end, _, _,
         self.shield_percent, self.tera_same, self.tera_other) = profile[1:10]
        self.extras = [tuple(profile[10 + 4 * i:14 + 4 * i]) for i in range(6)]
        self.double_hp = profile[34]
        self.limit = limit              # the battle timer's seconds
        self.state = 0                  # the shield: 0 not raised, 1 up, 2 broken
        self.shield_from = 0            # the boss's HP when the shield went up
        self.fired = [False] * 6
        self.late = False               # the time-left action ran: no shield by time, no second one
        self.double = False             # the boss acts twice a round
        self.pending = []               # [(kind, value)] queued and not yet run
        self.stunned = set()            # client slots whose next boss reply is dropped (the shield broke)

    def share(self, battle):
        from raidbattle.battlers import BOSS
        return battle.hp[BOSS] * 100 // battle.full[BOSS]

    def triggers(self, battle, left=None):
        """-> the actions that fire now, in queue order: by HP when `left` is None, else by the time left
        (seconds) on the battle timer."""
        out = []
        push = lambda kind, value: len(out) < 4 and out.append((kind, value))
        from raidbattle.battlers import BOSS
        timed = left is not None
        by_time = lambda pct: not self.limit or left * 100 // self.limit <= pct
        if self.state:
            if not timed and self.state == 1 and self.shield_end and battle.hp[BOSS]:
                lost = max(0, self.shield_from - battle.hp[BOSS])
                if lost * 100 // battle.full[BOSS] >= self.shield_end:
                    push(SHIELD_END, 1)
        elif not self.late:
            if timed and self.shield_time and by_time(self.shield_time):
                push(SHIELD, self.limit + battle.timer_offset - left)     # the seconds run
            elif not timed and self.shield_hp and battle.hp[BOSS] and self.share(battle) <= self.shield_hp:
                push(SHIELD, 0)
        if timed and not self.late and by_time(10):
            push(LOW_TIME, 1)
        for i, (action, timing, value, move) in enumerate(self.extras):
            if not action or not timing or self.fired[i]:
                continue
            if timed:
                if timing == BY_TIME and by_time(value):
                    push(EXTRA, i)
            elif timing == BY_HP and battle.hp[BOSS] and self.share(battle) <= value:
                push(EXTRA, i)
        if not timed and not self.double and battle.hp[BOSS] and self.share(battle) <= self.double_hp:
            push(DOUBLE, 0)
        return out

    def run(self, battle, kind, value):
        """The record's event for a run action; False for an extra action that already ran."""
        from raidbattle.battlers import BOSS
        if kind == SHIELD and not self.state:
            self.state, self.shield_from = 1, battle.hp[BOSS]
        elif kind == SHIELD_END and self.state == 1:
            self.state = 2
            if value == 1:
                self.stunned = {0, 1, 2, 3, 4}  # each player's next turn goes unanswered
        elif kind == LOW_TIME:
            self.late = True
        elif kind == EXTRA:
            if self.fired[value]:
                return False
            self.fired[value] = True
        elif kind == DOUBLE:
            self.double = True
        return True

    def damage(self, dmg):
        """A hit on the shielded boss: `shield_percent` of the damage, rounded up from half (players who
        Terastallized are refused before)."""
        if self.state != 1 or not self.shield_percent:
            return dmg
        p = self.shield_percent * dmg
        return p // 100 + (p % 100 > 49)


def word(kind, value):
    """A queued action as a request block word: kind 12, the action's kind in bits 4..11, its value in
    bits 32..47."""
    return 0xC | kind << 4 | value << 32
