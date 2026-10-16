"""The battle server a host launcher drives (pokeldn docs/plugins.md, A battle server), following the
server's flow in pokeldn docs/sv_raid.md (The server's flow): 30 frames a second; on each frame the
stations' messages are read, then one job runs; on a frame with no job the per-slot readers post
requests and the first posted one starts."""
import struct

from raidbattle import messages

FPS = 30
SLOTS = (0, 1, 2, 3, 4)
PLAYERS = (0, 2, 3, 4)
REQUEST, COMMAND, ROUND = 0x05, 0x06, 0x15
ROUND_BODY = 0x5060                 # a round body: the 0x238-byte action block, the queue, zeros
WIN = bytes.fromhex("000001000100")
END_GAP = {0x25: 2, 0x49: 2}        # frames between the last answer and the next end message


class Unsupported(Exception):
    """The battle holds something this server cannot reproduce exactly; the host hands the network
    over and the console fights its own battle."""


class Server:
    """One raid battle. `rounds(slot, command, server)` -> (the round body, action block and queue, for
    a slot's type-6 command; whether that round wins the battle), or raises Unsupported; by default the
    rounds are built (raidbattle.rounds)."""

    def __init__(self, bootstrap, partners, rounds=None, start_body=None):
        from raidbattle import battlers, start
        from raidbattle import rounds as built
        if rounds is None:
            battle = battlers.battle(bootstrap, partners)
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
        self.sent_by = {s: {} for s in SLOTS}        # kind -> step, what each slot sent
        self.unanswered = {s: set() for s in SLOTS}   # steps of rounds a slot has not answered
        self.reader = {s: "idle" for s in PLAYERS}
        self.posted = []                              # requests waiting for the executor
        self.job = None
        self.setup = "hello"
        self.over = False

    # --- the interface -----------------------------------------------------------------------

    def start(self, now):
        self.t = now
        self.posted.append(self._wild_setup())
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

    # --- frames ------------------------------------------------------------------------------

    def _send(self, kind, slots, body=b"", destination=messages.EVERY):
        self.step += 1
        message = messages.message(kind, self.step, self.round, body, destination)
        for s in slots:
            self.out[s].append(message)
        return self.step

    def _read(self):
        """-> whether a round's answer was read (that frame moves the battle)."""
        answered = False
        for slot, message in self.inbox:
            kind, step, _round, _ = messages.header(message)
            self.sent_by[slot][kind] = (step, message)
            if kind == ROUND + 1:
                self.unanswered[slot].discard(step)
                answered = True
        self.inbox = []
        return answered

    def _frame(self):
        """-> 1 when a job started on this frame or, with no job running, a reader erased a round's
        answer (the server's notice 0x46 follows it), else 0."""
        answered = self._read()
        started = False
        if self.job is None:
            started = answered                        # a reader erased an answered round
            self._readers()
            if self.posted:
                self.job, started = self.posted.pop(0), True
        if self.job is not None:
            try:
                next(self.job)
            except StopIteration:
                self.job = None
        return int(started)

    # --- jobs --------------------------------------------------------------------------------

    def _wild_setup(self):
        self._send(0x01, SLOTS)
        while not all(0x02 in self.sent_by[s] for s in SLOTS):
            yield
        self.round += 1
        self._send(0x11, SLOTS, self.start_body)
        while not all(0x12 in self.sent_by[s] for s in SLOTS):
            yield
        self.setup = "done"
        yield                                         # the battle timer starts; the job ends next frame

    def _request(self, slot):
        self.reader[slot] = "requested"
        self._send(REQUEST, (slot,), destination=slot)
        return
        yield

    def _command(self, slot, command):
        body, won = self.rounds(slot, command, self)
        self.round += 1
        step = self._send(ROUND, SLOTS, body)
        for s in SLOTS:
            self.unanswered[s].add(step)
        self.reader[slot] = "round"
        if won:
            self.over = True
            self.posted.insert(0, self._end())
        return
        yield

    def _end(self):
        """The battle won: an empty round 0x25, then 0x29, 0x49, 0x35 and 0x37, each once every slot
        answered the one before."""
        self.round += 1
        for kind, body in ((0x25, bytes(ROUND_BODY)), (0x29, WIN), (0x49, b""), (0x35, b""), (0x37, b"")):
            self._send(kind, SLOTS, body)
            if kind == 0x37:
                return
            while not all(self.sent_by[s].get(kind + 1, (0,))[0] == self.step for s in SLOTS):
                yield
            for _ in range(END_GAP.get(kind, 0)):
                yield

    def _readers(self):
        if self.setup != "done" or self.over:
            return
        for slot in PLAYERS:
            state = self.reader[slot]
            if state == "idle" and not self.unanswered[slot]:
                self.reader[slot] = "posted"
                self.posted.append(self._request(slot))
            elif state == "requested" and COMMAND in self.sent_by[slot]:
                step, command = self.sent_by[slot].pop(COMMAND)
                self.posted.append(self._command(slot, command))
                self.reader[slot] = "posted"
            elif state == "round" and not self.unanswered[slot]:
                self.reader[slot] = "idle"            # asked again on the next frame
