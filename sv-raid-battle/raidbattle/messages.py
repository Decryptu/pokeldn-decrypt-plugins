"""A battle message: a 32-byte header, then the body (pokeldn docs/sv_raid.md, The server's messages).

    +0x00 u32 type   +0x08 u64 step   +0x10 u64 round   +0x18 destination (5: every station)   +0x19 5
"""
import struct

HEADER = 0x20
EVERY = 5


def message(kind, step, round_, body=b"", destination=EVERY):
    head = bytearray(HEADER)
    struct.pack_into("<I", head, 0, kind)
    struct.pack_into("<QQBB", head, 8, step, round_, destination, EVERY)
    return bytes(head) + bytes(body)


def header(raw):
    """-> (type, step, round, destination) of a message."""
    kind, = struct.unpack_from("<I", raw, 0)
    step, round_, destination = struct.unpack_from("<QQB", raw, 8)
    return kind, step, round_, destination
