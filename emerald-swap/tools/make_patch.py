#!/usr/bin/env python3
"""Writes the BPS patch from retail Emerald to the Switch build pokeldn's tools/rse produces, and
checks it with the plugin's own reader.

    python tools/make_patch.py RETAIL.gba BUILD.gba emerald_bpre.bps

SourceRead where bytes stay put, SourceCopy from an 8-byte hash of the source for what moved,
TargetRead for what is new.
"""
import os
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bps  # noqa: E402

KEY = 8
MIN_COPY = 16


def varint(value):
    out = bytearray()
    while True:
        low = value & 0x7F
        value >>= 7
        if value == 0:
            out.append(0x80 | low)
            return bytes(out)
        out.append(low)
        value -= 1


def index(source):
    table = {}
    for at in range(0, len(source) - KEY, 4):
        table.setdefault(source[at:at + KEY], []).append(at)
    return {key: spots[:32] for key, spots in table.items()}


def match_length(a, i, b, j, limit):
    n = 0
    while n < limit and a[i + n] == b[j + n]:
        n += 1
    return n


def diff(source, target):
    table, ops, at, literal = index(source), [], 0, bytearray()
    size = len(target)

    def flush():
        if literal:
            ops.append((bps.TARGET_READ, bytes(literal)))
            literal.clear()

    while at < size:
        same = 0
        if at < len(source):
            same = match_length(source, at, target, at, min(size, len(source)) - at)
        if same >= MIN_COPY:
            flush()
            ops.append((bps.SOURCE_READ, same))
            at += same
            continue
        best, spot = 0, 0
        for start in table.get(target[at:at + KEY], ()):
            n = match_length(source, start, target, at, min(len(source) - start, size - at))
            if n > best:
                best, spot = n, start
        if best >= MIN_COPY:
            flush()
            ops.append((bps.SOURCE_COPY, best, spot))
            at += best
            continue
        literal.append(target[at])
        at += 1
    flush()
    return ops


def encode(source, target, ops):
    out = bytearray(b"BPS1" + varint(len(source)) + varint(len(target)) + varint(0))
    relative = 0
    for op in ops:
        if op[0] == bps.SOURCE_READ:
            out += varint((op[1] - 1) << 2 | bps.SOURCE_READ)
        elif op[0] == bps.TARGET_READ:
            out += varint((len(op[1]) - 1) << 2 | bps.TARGET_READ) + op[1]
        else:
            delta = op[2] - relative
            out += varint((op[1] - 1) << 2 | bps.SOURCE_COPY) + varint(abs(delta) << 1 | (delta < 0))
            relative = op[2] + op[1]
    out += zlib.crc32(source).to_bytes(4, "little") + zlib.crc32(target).to_bytes(4, "little")
    out += zlib.crc32(bytes(out)).to_bytes(4, "little")
    return bytes(out)


def main():
    source, target = (open(path, "rb").read() for path in sys.argv[1:3])
    ops = diff(source, target)
    patch = encode(source, target, ops)
    assert bps.apply(source, patch) == target
    with open(sys.argv[3], "wb") as handle:
        handle.write(patch)
    new = sum(len(op[1]) for op in ops if op[0] == bps.TARGET_READ)
    print(f"{len(patch)} bytes, {len(ops)} operations, {new} new bytes")


if __name__ == "__main__":
    main()
