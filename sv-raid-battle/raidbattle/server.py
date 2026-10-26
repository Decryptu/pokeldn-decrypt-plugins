"""The battle server a host launcher drives (pokeldn docs/plugins.md, A battle server), following the
server's flow in pokeldn docs/sv_raid.md (The server's flow): 30 frames a second; on each frame the
stations' messages are read, then one job runs; on a frame with no job the per-frame machine checks the
battle timer and the boss's time triggers or steps the per-slot readers, and the first posted request
starts (a raid action first)."""
from raidbattle import messages

FPS = 30
SLOTS = (0, 1, 2, 3, 4)
PLAYERS = (0, 2, 3, 4)
BOSS_SLOT = 1
REQUEST, COMMAND, ROUND = 0x05, 0x06, 0x15
FAINTED, REVIVE, PAUSE = 0x21, 0x23, 0x47
ROUND_BODY = 0x5060                 # a round body: the 0x238-byte action block, the queue, zeros
WIN = bytes.fromhex("000001000100")
TIME_UP = bytes.fromhex("000000000200")
END_GAP = {0x25: 2, 0x49: 2}        # frames between the last answer and the next end message
REVIVE_WAIT = (5, 10, 15, 20, 25, 30)   # seconds a fainted slot waits, by its Pokemon's faint count
# a slot that was sent one of these and has not had it erased is not asked for a command (0xf6e22c)
WAIT = frozenset((5, 0xD, 0xB, 0xF, 9, 7, 0x21, 3, 0x23, 0x15, 0x17, 0x19, 0x13, 0x47, 0x1F, 0x1D))
# message pairs a reader erases, one of each a frame, once answered (0xf6e410)
PAIRS = ((0x15, 0x16), (0x23, 0x24), (0x11, 0x12), (0x13, 0x14), (0x17, 0x18), (0x19, 0x1A), (0x1B, 0x1C),
         (0x1D, 0x1E), (0x25, 0x26), (0x1F, 0x20))


class Unsupported(Exception):
    """The battle holds something this server cannot reproduce exactly; the host hands the network
    over and the console fights its own battle."""


class Timer:
    """A server timer (pokeldn docs/sv_raid.md, The battle timer): seconds run while no pause reason is
    set; made started and at once paused for reason 0."""

    def __init__(self, limit, now):
        self.limit, self.start, self.acc, self.reasons = limit, None, 0.0, {0}

    def pause(self, now, reason=0):
        if not self.reasons:
            self.acc += now - self.start
            self.start = None
        self.reasons.add(reason)

    def resume(self, now, reason=0):
        self.reasons.discard(reason)
        if not self.reasons and self.start is None:
            self.start = now

    def left(self, now, offset=0):
        """Seconds left: the limit (plus `offset` while running) less the whole seconds run."""
        if self.reasons:
            return self.limit - int(self.acc)
        return self.limit + offset - int(now - self.start) - int(self.acc)


class Job:
    """A posted request: a generator run one step a frame (a yield ends the frame); `raid` jobs start
    before every other posted one."""

    def __init__(self, gen, raid=False):
        self.gen, self.raid = gen, raid


class Server:
    """One raid battle. `rounds(slot, command, server)` -> (the round body, action block and queue, for
    a slot's type-6 command; whether that round wins the battle), or raises Unsupported; by default the
    rounds are built (raidbattle.rounds), with the boss's raid actions, faints and the battle timer."""

    def __init__(self, bootstrap, partners, rounds=None, start_body=None):
        from raidbattle import battlers, start
        from raidbattle import rounds as built
        self.battle = None
        if rounds is None:
            battle = self.battle = battlers.battle(bootstrap, partners)
            rounds = lambda slot, command, server: built.build(battle, slot, command)
            self.battlers = battle.b
            self.start_body = start_body if start_body is not None else start.body(battle.b, None, battle)
        else:
            self.battlers = battlers.from_records(bootstrap, partners)
            self.start_body = start_body if start_body is not None else start.body(self.battlers)
        self.rounds = rounds
        self.t = 0.0
        self.step = 0
        self.round = 0
        self.out = {s: [] for s in SLOTS}
        self.inbox = []
        self.sent_by = {s: {} for s in SLOTS}         # kind -> (step, message), the last each slot sent
        self.store = {s: [] for s in SLOTS}           # (kind, step) sent to each slot, not yet erased
        self.got = {s: [] for s in SLOTS}             # (kind, step) each slot sent, not yet erased
        self.reader = {s: 0 for s in SLOTS}           # 0 idle, 1 asked for a command, 2 its round sent
        self.sub = {s: 0 for s in PLAYERS}            # a player slot's fainted states (0 standing, 3, 1, 2)
        self.revive_timer = {}
        self.posted = []                              # Jobs waiting for the executor
        self.job = None
        self.setup = "hello"
        self.over = False
        self.timer = None                             # the battle timer, made on the first frame
        self.armed = True                             # the machine checks the boss's time triggers
        self.boss_list = []                           # the machine's list of raid actions [(kind, value)]
        self.timed = None                             # a 0x51 on its way into the server's own link

    # --- the interface -----------------------------------------------------------------------

    def start(self, now):
        self.t = now
        if self.battle is not None:
            self.timer = Timer(self.battle.raid.limit, now)
        self.posted.append(Job(self._wild_setup()))
        return self._frame()

    def run(self, until):
        moved, t = 0, self.t
        while True:
            self.t = t
            moved += self._frame()
            t += 1 / FPS
            if t > until:
                break
        self.t = until
        return moved

    def receive(self, slot, message):
        self.inbox.append((slot, bytes(message)))

    def sent(self, slot):
        out, self.out[slot] = self.out[slot], []
        return out

    # --- messages ----------------------------------------------------------------------------

    def _send(self, kind, slots, body=b"", destination=messages.EVERY):
        self.step += 1
        message = messages.message(kind, self.step, self.round, body, destination)
        for s in slots:
            self.out[s].append(message)
            self.store[s].append((kind, self.step))
        return self.step

    def _has(self, slot, kind):
        return any(k == kind for k, _ in self.store[slot])

    def _erase(self, slot, kind, answer):
        """The first `kind` sent to `slot` and the first `answer` it sent erased, when both are there
        (0xf6edf4). -> whether they were."""
        sent = next((e for e in self.store[slot] if e[0] == kind), None)
        got = next((e for e in self.got[slot] if e[0] == answer), None)
        if sent is None or got is None:
            return False
        self.store[slot].remove(sent)
        self.got[slot].remove(got)
        return True

    def _answered(self, slot, kind, step):
        return self.sent_by[slot].get(kind + 1, (None,))[0] == step

    def _read(self):
        for slot, message in self.inbox:
            kind, step, _round, _ = messages.header(message)
            self.sent_by[slot][kind] = (step, message)
            self.got[slot].append((kind, step))
        self.inbox = []

    # --- frames ------------------------------------------------------------------------------

    def _frame(self):
        """-> 1 when a job started on this frame or, with no job running, the machine moved the battle
        (the server's notice 0x46 follows it), else 0."""
        self._read()
        if self.timed is not None:
            self.boss_list, self.timed = self.timed, None     # the 0x51 read from the server's own link
        started = False
        if self.job is None:
            started = self._machine()
            if self.posted:
                job = next((j for j in self.posted if j.raid), self.posted[0])
                self.posted.remove(job)
                self.job, started = job, True
        if self.job is not None:
            try:
                next(self.job.gen)
            except StopIteration:
                self.job = None
        return int(bool(started))

    def _machine(self):
        """The per-frame machine (0xf6d538): the battle timer's time-up; the boss's time triggers, sent as
        0x51 into the server's own link; a list of raid actions posted; else the readers."""
        if self.setup != "done" or self.over:
            return False
        if self.timer is not None:
            offset = self.battle.timer_offset
            if self.timer.left(self.t, offset) <= 0:
                self.over = True
                self.posted.insert(0, Job(self._time_up()))
                return True
            if self.armed:
                if self.boss_list:
                    return False
                words = self.battle.raid.triggers(self.battle, self.timer.left(self.t, offset))
                if words:
                    self.timed, self.armed = words, False
                    return False
            if self.boss_list:
                self.posted.append(Job(self._raid_action(self.boss_list, machine=True), raid=True))
                self.armed = True
                return True
        return self._readers()

    # --- the readers (0xf6df44) ------------------------------------------------------------------

    def _readers(self):
        """-> whether a reader moved the battle."""
        moved = False
        for slot in SLOTS:
            moved |= self._read_slot(slot) not in (0, 5)
        return moved

    def _answers(self, slot):
        hit = False
        for kind, answer in PAIRS:
            hit |= self._erase(slot, kind, answer)
        return 6 if hit else 0

    def _read_slot(self, slot):
        if slot == BOSS_SLOT:
            return self._answers(slot)
        if self.battle is not None:
            r = self._fainted(slot)
            if r is not None:
                return r
        state = self.reader[slot]
        if state == 0:
            if any(k in WAIT for k, _ in self.store[slot]):
                return self._answers(slot)
            self.posted.append(Job(self._request(slot)))
            self.reader[slot] = 1
            return 1
        if state == 1:
            if not (self._has(slot, REQUEST) and any(k == COMMAND for k, _ in self.got[slot])):
                return 5
            _step, command = self.sent_by[slot][COMMAND]
            self._erase(slot, REQUEST, COMMAND)
            self.posted.append(Job(self._command(slot, command)))
            self.reader[slot] = 2
            return 1
        if not self._erase(slot, ROUND, ROUND + 1):
            return 5
        self.reader[slot] = 0
        return 6

    def _fainted(self, slot):
        """A player slot's fainted states (0xf6e014): -> 4 while they hold its reader, else None."""
        sub, b = self.sub[slot], slot + 1
        if sub == 0:
            if self.battle.hp[b]:
                return None
            self.posted.append(Job(self._notify(slot, FAINTED)))
            self.sub[slot] = 3
        elif sub == 3:
            if self._erase(slot, FAINTED, FAINTED + 1):
                wait = REVIVE_WAIT[min(self.battle.faints[b], len(REVIVE_WAIT)) - 1]
                self.revive_timer[slot] = Timer(wait, self.t)
                self.revive_timer[slot].resume(self.t)
                self.sub[slot] = 1
        elif sub == 1:
            if self.revive_timer[slot].left(self.t) < 1:
                self.posted.append(Job(self._revive(slot)))
                self.sub[slot] = 2
        elif sub == 2:
            if self._erase(slot, REVIVE, REVIVE + 1):
                self.sub[slot] = 0
        return 4

    # --- jobs --------------------------------------------------------------------------------

    def _wild_setup(self):
        self._send(0x01, SLOTS)
        while not all(0x02 in self.sent_by[s] for s in SLOTS):
            yield
        self.round += 1
        self._send(0x11, SLOTS, self.start_body)
        while not all(0x12 in self.sent_by[s] for s in SLOTS):
            yield
        for s in SLOTS:                               # what each slot sent and was sent, cleared
            self.store[s], self.got[s] = [], []
        self.setup = "done"
        if self.timer is not None:
            self.timer.resume(self.t)
        yield                                         # the job ends next frame

    def _request(self, slot):
        self._send(REQUEST, (slot,), destination=slot)
        return
        yield

    def _notify(self, slot, kind):
        self._send(kind, (slot,), destination=slot)
        return
        yield

    def _command(self, slot, command):
        body, won = self.rounds(slot, command, self)
        self.round += 1
        self._send(ROUND, SLOTS, body)
        self._next(won)
        return
        yield

    def _next(self, won):
        """A round's next step: the battle's end when it won; a raid action when its list holds a shield
        first (0x16e5ad0)."""
        if won:
            self.over = True
            self.posted.insert(0, Job(self._end()))
            return
        pending = self.battle.raid.pending if self.battle is not None else []
        if pending and pending[0][0] == 1:
            self.posted.append(Job(self._raid_action(list(pending), machine=False), raid=True))

    def _raid_action(self, words, machine):
        """A raid action (0x18c92a8): with a shield first, message 0x47 to every slot and the battle timer
        paused until every slot answered; then the actions as a slot-1 round, the timer resumed; then the
        round's next step, the list cleared and the 0x47 pairs erased."""
        from raidbattle import rounds
        shield = words[0][0] == 1
        if shield:
            step = self._send(PAUSE, SLOTS)
            self.timer.pause(self.t)
            yield
            while not all(self._answered(s, PAUSE, step) for s in SLOTS):
                yield
            yield
        body, won = rounds.raid_round(self.battle, words)
        self.timer.resume(self.t)
        self.round += 1
        self._send(ROUND, SLOTS, body)
        yield
        self._next(won)
        if machine:
            self.boss_list = []
        if shield:
            for s in SLOTS:
                self._erase(s, PAUSE, PAUSE + 1)

    def _revive(self, slot):
        """A fainted slot's revive (message 0x23) to every slot, built like a round."""
        from raidbattle import rounds
        body = rounds.revive(self.battle, slot)
        self.round += 1
        self._send(REVIVE, SLOTS, body)
        return
        yield

    def _end(self):
        """The battle won: an empty round 0x25, then 0x29, 0x49, 0x35 and 0x37, each once every slot
        answered the one before."""
        self.round += 1
        for kind, body in ((0x25, bytes(ROUND_BODY)), (0x29, WIN), (0x49, b""), (0x35, b""), (0x37, b"")):
            step = self._send(kind, SLOTS, body)
            if kind == 0x37:
                return
            while not all(self._answered(s, kind, step) for s in SLOTS):
                yield
            for _ in range(END_GAP.get(kind, 0)):
                yield

    def _time_up(self):
        """The battle timer ran out: 0x2b, 0x35 and 0x37, each once every slot answered the one before."""
        for kind, body in ((0x2B, TIME_UP), (0x35, b""), (0x37, b"")):
            step = self._send(kind, SLOTS, body)
            if kind == 0x37:
                return
            while not all(self._answered(s, kind, step) for s in SLOTS):
                yield
