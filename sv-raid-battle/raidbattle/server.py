"""The battle server a host launcher drives (pokeldn docs/plugins.md, A battle server)."""


class Unsupported(Exception):
    """The battle holds something this server cannot reproduce exactly; the host hands the network
    over and the console fights its own battle."""


class Server:
    """One raid battle. Until the battle start is reproduced, every battle is refused."""

    def __init__(self, bootstrap, partners):
        raise Unsupported("the battle start is not reproduced yet")

    def start(self, now):
        raise NotImplementedError

    def run(self, until):
        raise NotImplementedError

    def receive(self, slot, message):
        raise NotImplementedError

    def sent(self, slot):
        raise NotImplementedError
