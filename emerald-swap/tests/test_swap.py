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


@pytest.mark.parametrize("code", sorted(swap.CARTRIDGES))
def test_the_shipped_patch_expects_retail_emerald_and_makes_the_16_mb_build(code):
    with open(os.path.join(HERE, f"emerald_{code.lower()}.bps"), "rb") as handle:
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
    monkeypatch.setattr(swap, "align_stwi_status", lambda rom, code: rom)
    import pokeldn.panel
    monkeypatch.setattr(pokeldn.panel, "show", lambda *a, **k: None)
    for _ in range(2):
        assert swap.main(["--step", "stream", "--emerald", str(tmp_path / "e.zip"), "--keys", "K", "--agree"]) == 0
    assert built == [rom]
    argv = calls[0][1]
    assert argv[argv.index("--rom-base") + 1] == "none"
    assert argv[argv.index("--rom-transfer") + 1] == str(data / swap.build_name("BPRE"))
    assert (data / swap.build_name("BPRE")).read_bytes() == b"built"
    assert argv[-4:] == ["--block-repeat", "1", "--inter-block-gap-frames", "8"]


def test_an_update_never_streams_the_old_cached_build(folders, tmp_path, monkeypatch):
    data, _, _ = folders
    data.mkdir()
    (data / swap.OLD_BUILDS[0]).write_bytes(b"old")
    rom = b"retail" * 64
    monkeypatch.setattr(swap, "EMERALD_SHA1", hashlib.sha1(rom).hexdigest())
    (tmp_path / "e.gba").write_bytes(rom)
    import types
    monkeypatch.setitem(__import__("sys").modules, "bps", types.SimpleNamespace(apply=lambda s, p: b"new"))
    monkeypatch.setattr(swap, "align_stwi_status", lambda rom, code: rom)
    assert open(swap.built_rom(str(tmp_path / "e.gba"), str(data)), "rb").read() == b"new"
    assert not (data / swap.OLD_BUILDS[0]).exists()


def test_a_second_emerald_save_needs_an_app_that_keeps_the_firered_copy(folders, tmp_path, monkeypatch):
    import pokeldn
    monkeypatch.setattr(pokeldn, "__version__", "0.57.0")
    with pytest.raises(SystemExit, match="Update pokeldn"):
        swap.main(["--step", "save", "--emerald-save", str(tmp_path / "e.sav"), "--keys", "K"])
    assert not folders[2]
    monkeypatch.setattr(pokeldn, "__version__", "0.57.1")
    assert swap.main(["--step", "save", "--emerald-save", str(tmp_path / "e.sav"), "--keys", "K"]) == 0
    assert folders[2]


def test_a_rom_with_another_hash_is_refused_by_name(folders, tmp_path):
    (tmp_path / "e.gba").write_bytes(b"hack")
    with pytest.raises(SystemExit, match="USA, Europe"):
        swap.emerald_rom(str(tmp_path / "e.gba"))


def test_another_cartridge_is_refused_before_a_session_and_named(folders, tmp_path):
    (tmp_path / "f.gba").write_bytes(bytes(0xAC) + b"BPRF" + bytes(16))
    with pytest.raises(SystemExit, match="not English FireRed.*holds French FireRed"):
        swap.firered_base(str(tmp_path / "f.gba"), "", str(tmp_path))


def test_a_cartridge_past_english_firered_needs_an_app_with_its_live_blocks(folders, tmp_path, monkeypatch):
    import pokeldn
    data, library, calls = folders
    library.mkdir()
    (library / "FireRed.sav").write_bytes(b"\0")
    monkeypatch.setattr(pokeldn, "__version__", "0.61.0")
    with pytest.raises(SystemExit, match="Update pokeldn to 0.62.0"):
        swap.main(["--step", "stream", "--emerald", str(tmp_path / "e.gba"), "--cartridge", "BPRF", "--agree"])
    assert not calls


def _synthetic_emerald_switch_rom():
    """Minimal 16 MB BPEE rev 0x0A image with exact Thumb/ARM PC-relative LDR pools for
    gCurGlyph (30 refs) and &gSTWIStatus (69 refs), plus a graphics coincidence past CODE_END."""
    import struct
    rom = bytearray(0x1000000)
    rom[0xAC:0xB0] = b"BPEE"
    rom[0xBC] = 0x0A
    cur = 0x1000
    glyph_sites = []
    for addr, count in swap.EMERALD_GLYPH_REFS.items():
        for _ in range(count):
            # Thumb: ldr r0, [pc, #0] (0x4800) at cur, literal at cur + 4
            struct.pack_into("<HHI", rom, cur, 0x4800, 0x46C0, addr)
            glyph_sites.append((cur + 4, addr))
            cur += 8
    stwi_sites = []
    for i in range(swap.EMERALD_STWI_REFS):
        if i % 2 == 0:
            struct.pack_into("<HHI", rom, cur, 0x4800, 0x46C0, swap.EMERALD_STWI_STATUS)
            stwi_sites.append(cur + 4)
            cur += 8
        else:
            # ARM: ldr r3, [pc, #0] (0xE59F3000) at cur, literal at cur + 8
            struct.pack_into("<III", rom, cur, 0xE59F3000, 0xE1A00000, swap.EMERALD_STWI_STATUS)
            stwi_sites.append(cur + 8)
            cur += 12
    # Coincidental bytes in graphics region past EMERALD_CODE_END must stay untouched
    coincidence = swap.EMERALD_CODE_END + 0x100
    struct.pack_into("<I", rom, coincidence, swap.EMERALD_STWI_STATUS)
    return bytes(rom), glyph_sites, stwi_sites, coincidence


def test_align_stwi_status_english_relocates_glyph_and_stwi():
    import struct
    rom, glyph_sites, stwi_sites, coincidence = _synthetic_emerald_switch_rom()
    patched = swap.align_stwi_status(rom, "BPGE")
    delta = swap.EMERALD_GLYPH_NEW - swap.EMERALD_GLYPH_BASE
    for off, old in glyph_sites:
        assert struct.unpack_from("<I", patched, off)[0] == old + delta
    for off in stwi_sites:
        assert struct.unpack_from("<I", patched, off)[0] == 0x030030E0
    assert struct.unpack_from("<I", patched, coincidence)[0] == swap.EMERALD_STWI_STATUS


def test_align_stwi_status_european_redirects_stwi_without_moving_glyph():
    import struct
    rom, glyph_sites, stwi_sites, coincidence = _synthetic_emerald_switch_rom()
    patched = swap.align_stwi_status(rom, "BPRF")
    for off, old in glyph_sites:
        assert struct.unpack_from("<I", patched, off)[0] == old
    for off in stwi_sites:
        assert struct.unpack_from("<I", patched, off)[0] == 0x03003030
    assert struct.unpack_from("<I", patched, coincidence)[0] == swap.EMERALD_STWI_STATUS


def test_align_stwi_status_refuses_unexpected_count_or_non_ldr_word():
    import struct
    rom, _, stwi_sites, _ = _synthetic_emerald_switch_rom()
    bad = bytearray(rom)
    struct.pack_into("<I", bad, stwi_sites[0], 0)
    with pytest.raises(ValueError, match="expected 69 refs"):
        swap.align_stwi_status(bytes(bad), "BPGE")
