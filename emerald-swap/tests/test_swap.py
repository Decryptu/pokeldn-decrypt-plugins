"""The patch reader against random data, the patch shipped against the header it carries, and what the
tool passes to the launcher."""
import hashlib
import os
import random
import zipfile
import zlib

import pytest

import bps
import make_patch
import swap

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_moved_changed_and_new_bytes_come_out_right():
    rng = random.Random(1)
    source = rng.randbytes(0x20000)
    target = bytearray(source[:0x8000] + source[0x10000:0x18000] + rng.randbytes(0x400) + source[0x8000:0x9000])
    target[0x123] ^= 0xFF
    patch = make_patch.encode(source, bytes(target), make_patch.diff(source, bytes(target)))
    assert len(patch) < 0x1000
    assert bps.apply(source, patch) == bytes(target)


def test_a_target_copy_repeats_its_own_output():
    """No encoder here writes one; other patchers do. "ab" then a 6-byte copy from 0 overlaps itself."""
    body = (b"BPS1" + make_patch.varint(0) + make_patch.varint(8) + make_patch.varint(0)
            + make_patch.varint((2 - 1) << 2 | bps.TARGET_READ) + b"ab"
            + make_patch.varint((6 - 1) << 2 | bps.TARGET_COPY) + make_patch.varint(0))
    body += zlib.crc32(b"").to_bytes(4, "little") + zlib.crc32(b"abababab").to_bytes(4, "little")
    assert bps.apply(b"", body + zlib.crc32(body).to_bytes(4, "little")) == b"abababab"


def test_another_rom_or_a_damaged_patch_is_refused():
    source, target = b"a" * 64, b"a" * 32 + b"b" * 32
    patch = make_patch.encode(source, target, make_patch.diff(source, target))
    with pytest.raises(bps.BadPatch, match="not the ROM"):
        bps.apply(b"c" * 64, patch)
    with pytest.raises(bps.BadPatch, match="damaged"):
        bps.apply(source, patch[:20] + b"\0" + patch[21:])


def test_the_shipped_patch_expects_retail_emerald_and_makes_the_16_mb_build():
    with open(os.path.join(HERE, "emerald_bpre.bps"), "rb") as handle:
        patch = handle.read()
    source_size, at = bps._varint(patch, 4)
    target_size, at = bps._varint(patch, at)
    assert (source_size, target_size) == (0x1000000, 0x1000000)
    assert patch[-12:-8] == (0x1F1C08FB).to_bytes(4, "little")     # the retail ROM's published CRC-32


@pytest.fixture
def folders(tmp_path, monkeypatch):
    import pokeldn.plugins as plugins
    data, library = tmp_path / "data", tmp_path / "library"
    monkeypatch.setattr(plugins, "data_folder", lambda _: data)
    monkeypatch.setattr(plugins, "library_folder", lambda _: library)
    calls = []
    monkeypatch.setattr(plugins, "run_launcher", lambda script, argv: calls.append((script, argv)) or 0)
    return data, library, calls


def test_the_stream_needs_a_backup(folders, tmp_path):
    with pytest.raises(SystemExit, match="Back up"):
        swap.main(["--step", "stream", "--emerald", str(tmp_path / "e.gba"), "--agree"])
    assert not folders[2]


def test_the_backup_lands_in_the_library(folders):
    data, library, calls = folders
    assert swap.main(["--step", "backup", "--keys", "K"]) == 0
    script, argv = calls[0]
    assert script == "bin/frlg_mg_host.py" and argv[:4] == ["--live", "--keys", "K", "--version"]
    assert argv[argv.index("--save-backup") + 1].startswith(str(library))


def test_the_stream_builds_the_rom_once_from_a_zip_and_paces_as_retail_was_measured(folders, tmp_path, monkeypatch):
    data, library, calls = folders
    library.mkdir()
    (library / "FireRed.sav").write_bytes(b"\0")
    rom = b"retail" * 64
    monkeypatch.setattr(swap, "EMERALD_SHA1", hashlib.sha1(rom).hexdigest())
    with zipfile.ZipFile(tmp_path / "e.zip", "w") as archive:
        archive.writestr("Vimm's Lair.txt", "x")
        archive.writestr("e.gba", rom)
    built = []
    import types
    monkeypatch.setitem(__import__("sys").modules, "bps", types.SimpleNamespace(
        apply=lambda source, patch: built.append(source) or b"built"))
    import pokeldn.panel
    monkeypatch.setattr(pokeldn.panel, "show", lambda *a, **k: None)
    for _ in range(2):
        assert swap.main(["--step", "stream", "--emerald", str(tmp_path / "e.zip"), "--keys", "K", "--agree"]) == 0
    assert built == [rom]
    argv = calls[0][1]
    assert argv[argv.index("--rom-base") + 1] == "none"
    assert argv[argv.index("--rom-transfer") + 1] == str(data / swap.BUILD)
    assert (data / swap.BUILD).read_bytes() == b"built"
    assert argv[-4:] == ["--block-repeat", "1", "--inter-block-gap-frames", "8"]


def test_a_rom_with_another_hash_is_refused_by_name(folders, tmp_path):
    (tmp_path / "e.gba").write_bytes(b"hack")
    with pytest.raises(SystemExit, match="USA, Europe"):
        swap.emerald_rom(str(tmp_path / "e.gba"))


def test_another_cartridge_is_refused_before_a_session(folders, tmp_path):
    (tmp_path / "f.gba").write_bytes(b"leafgreen")
    with pytest.raises(SystemExit, match="English FireRed"):
        swap.firered_base(str(tmp_path / "f.gba"), "", str(tmp_path))
