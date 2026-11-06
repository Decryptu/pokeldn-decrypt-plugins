"""BPS patches, the format ROM patchers read: https://www.romhacking.net/documents/746/ """
import zlib

SOURCE_READ, TARGET_READ, SOURCE_COPY, TARGET_COPY = range(4)


class BadPatch(ValueError):
    pass


def _varint(data, at):
    value, shift = 0, 1
    while True:
        byte = data[at]
        at += 1
        value += (byte & 0x7F) * shift
        if byte & 0x80:
            return value, at
        shift <<= 7
        value += shift


def apply(source, patch):
    """-> the target of `patch` over `source`; BadPatch when a checksum disagrees."""
    if patch[:4] != b"BPS1" or len(patch) < 16:
        raise BadPatch("this is not a BPS patch")
    if zlib.crc32(patch[:-4]) != int.from_bytes(patch[-4:], "little"):
        raise BadPatch("the patch file is damaged")
    if zlib.crc32(source) != int.from_bytes(patch[-12:-8], "little"):
        raise BadPatch("this is not the ROM the patch was made from")
    source_size, at = _varint(patch, 4)
    target_size, at = _varint(patch, at)
    length, at = _varint(patch, at)
    at += length
    if source_size != len(source):
        raise BadPatch("this is not the ROM the patch was made from")
    end = len(patch) - 12
    out, source_at, target_at = bytearray(target_size), 0, 0
    written = 0
    while at < end:
        word, at = _varint(patch, at)
        action, count = word & 3, (word >> 2) + 1
        if action == SOURCE_READ:
            out[written:written + count] = source[written:written + count]
        elif action == TARGET_READ:
            out[written:written + count] = patch[at:at + count]
            at += count
        else:
            offset, at = _varint(patch, at)
            delta = (-1 if offset & 1 else 1) * (offset >> 1)
            if action == SOURCE_COPY:
                source_at += delta
                out[written:written + count] = source[source_at:source_at + count]
                source_at += count
            else:
                target_at += delta
                for k in range(count):       # overlaps its own output
                    out[written + k] = out[target_at + k]
                target_at += count
        written += count
    target = bytes(out)
    if written != target_size or zlib.crc32(target) != int.from_bytes(patch[-8:-4], "little"):
        raise BadPatch("the patched ROM did not come out right")
    return target
