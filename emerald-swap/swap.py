#!/usr/bin/env python3
"""The Emerald swap tool: a backup, an optional Emerald save, then the stream, each through
bin/frlg_mg_host.py. Emerald comes from the player's ROM and the patch for the console's cartridge."""
import argparse
import hashlib
import os
import queue
import struct
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = "emerald-swap"
EMERALD_SHA1 = "f3ae088181bf583e55daf962a92bb46f4f1d07b7"    # Pokemon Emerald (USA, Europe)
# The cartridge each Switch title carries, by game code; the patch builds Emerald for that cartridge.
CARTRIDGES = {
    "BPRE": ("English FireRed", "baa452d0b24629dd7782cfc07a8984085dde1311"),
    "BPGE": ("English LeafGreen", "62b9fc77549dbc67032eb6cbd0ea6ad3b825690f"),
    "BPRF": ("French FireRed", "07566b82dbd2a91321698f730f6400ae4c56ddf1"),
    "BPGF": ("French LeafGreen", "9f774956dfbad7f69ddb91fb91d2c26e54408f75"),
    "BPRD": ("German FireRed", "8dd70575fae5a089598832a153723497fcabc9bc"),
    "BPGD": ("German LeafGreen", "3c229e8d0daa43a7a3d1822323d4b2f2cd70390a"),
    "BPRI": ("Italian FireRed", "923a9f8ce93e66c756cff4a325d2248a7b2f53eb"),
    "BPGI": ("Italian LeafGreen", "24a4b7084658a7aa51100d92f7540d376a27ac75"),
    "BPRS": ("Spanish FireRed", "faf64fc6cdf417fee2f1005103a5a64bd2033918"),
    "BPGS": ("Spanish LeafGreen", "0d2a0026898375895dfd7ea139ceae90324add8f"),
}
OLD_BUILDS = (
    "emerald_switch_bpre.gba",
    "emerald_switch_bpre_1_1.gba",
    *(f"emerald_switch_{code.lower()}_1_2.gba" for code in CARTRIDGES),
)
# Host cartridge &gSTWIStatus cached by the Switch wrapper at launch (holder+0x170):
# English FireRed/LeafGreen place it at 0x030030E0; the eight European builds at 0x03003030
# (gMain + 0xD60). Streamed Emerald must keep &gSTWIStatus at the host cartridge's address so
# IntrSIO32's bkpt #0x52 hook reads the live pointer during wireless sessions.
HOST_STWI_STATUS = {
    "BPRE": 0x030030E0, "BPGE": 0x030030E0,
    "BPRF": 0x03003030, "BPGF": 0x03003030,
    "BPRD": 0x03003030, "BPGD": 0x03003030,
    "BPRI": 0x03003030, "BPGI": 0x03003030,
    "BPRS": 0x03003030, "BPGS": 0x03003030,
}
EMERALD_STWI_STATUS = 0x03007988
EMERALD_STWI_REFS = 69
# On English cartridges 0x030030E0 falls inside Emerald's gCurGlyph (0x030030B0..0x03003133);
# relocate the full 0x84-byte struct to free IWRAM at 0x03007A00..0x03007A83.
EMERALD_GLYPH_BASE = 0x030030B0
EMERALD_GLYPH_SIZE = 0x84
EMERALD_GLYPH_NEW = 0x03007A00
EMERALD_GLYPH_REFS = {0x030030B0: 25, 0x030030D0: 2, 0x030030F0: 2, 0x03003110: 1}
EMERALD_CODE_END = 0x00300000
NEEDS_APP_CART = (0, 62, 0)                                   # the live blocks of every cartridge but BPRE
PACING = ("--block-repeat", "1", "--inter-block-gap-frames", "8")
NEEDS_APP = (0, 57, 1)                                        # keeps FireRed's copy on a second Emerald save
WARNING = ("Emerald lasts until the game is closed. Its saves stay on the console beside your FireRed "
           "save. On the next launch FireRed says the save file is corrupted, then loads its own copy: "
           "press A. Saving in FireRed replaces the Emerald save, so back up first: part 1 keeps both.")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step", choices=("backup", "save", "stream"), default="backup")
    parser.add_argument("--keys", default="", help="prod.keys")
    parser.add_argument("--emerald-save", default="")
    parser.add_argument("--emerald", default="")
    parser.add_argument("--firered", default="")
    parser.add_argument("--cartridge", choices=tuple(CARTRIDGES), default="BPRE")
    parser.add_argument("--agree", action="store_true", help="agree to the warning with no pop-up")
    return parser


def emerald_rom(path):
    """-> the retail ROM in `path`, a .gba or a .zip holding one; SystemExit says what is wrong."""
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                names = [n for n in archive.namelist() if n.lower().endswith(".gba")]
                if len(names) != 1:
                    sys.exit("That .zip must hold exactly one .gba.")
                rom = archive.read(names[0])
        else:
            with open(path, "rb") as handle:
                rom = handle.read()
    except (OSError, zipfile.BadZipFile) as exc:
        sys.exit(f"Could not read {os.path.basename(path)}: {exc}")
    if hashlib.sha1(rom).hexdigest() != EMERALD_SHA1:
        sys.exit("This is not the Emerald the patch fits: it needs Pokemon Emerald (USA, Europe), "
                 f"SHA-1 {EMERALD_SHA1}, with no patch applied.")
    return rom


def _is_ldr_literal(rom, off):
    """True iff an ARM or Thumb PC-relative LDR before `off` loads the 32-bit word at `off`."""
    for pc in range(max(0, off - 1024), off, 2):
        h = struct.unpack_from("<H", rom, pc)[0]
        if (h & 0xF800) == 0x4800 and (((pc + 4) & ~3) + ((h & 0xFF) << 2)) == off:
            return True
    for pc in range(max(0, off - 4096), off, 4):
        w = struct.unpack_from("<I", rom, pc)[0]
        if (w & 0x0F7F0000) == 0x051F0000:
            imm = w & 0xFFF
            if pc + 8 + (imm if (w >> 23) & 1 else -imm) == off:
                return True
    return False


def align_stwi_status(rom, code):
    """Move Emerald's &gSTWIStatus to the host cartridge's cached IWRAM address so wireless
    (Mystery Gift, trade, Union Room) works after streaming without relaunching the app."""
    if len(rom) != 0x1000000 or rom[0xAC:0xB0] != b"BPEE" or rom[0xBC] != 0x0A:
        raise ValueError("expected a 16 MB Switch Emerald build (BPEE rev 0x0A)")
    target = HOST_STWI_STATUS[code]
    out = bytearray(rom)

    if EMERALD_GLYPH_BASE <= target < EMERALD_GLYPH_BASE + EMERALD_GLYPH_SIZE:
        for off in range(0, EMERALD_CODE_END, 4):
            w = struct.unpack_from("<I", rom, off)[0]
            if EMERALD_GLYPH_NEW <= w < EMERALD_GLYPH_NEW + EMERALD_GLYPH_SIZE and _is_ldr_literal(rom, off):
                raise ValueError(f"relocation target 0x{w:08X} is already referenced")
        glyph_refs = {addr: [] for addr in EMERALD_GLYPH_REFS}
        for off in range(0, EMERALD_CODE_END, 4):
            w = struct.unpack_from("<I", rom, off)[0]
            if EMERALD_GLYPH_BASE <= w < EMERALD_GLYPH_BASE + EMERALD_GLYPH_SIZE:
                if w not in glyph_refs or not _is_ldr_literal(rom, off):
                    raise ValueError(f"unexpected gCurGlyph reference 0x{w:08X} at 0x{off:06X}")
                glyph_refs[w].append(off)
        for addr, expected in EMERALD_GLYPH_REFS.items():
            if len(glyph_refs[addr]) != expected:
                raise ValueError(f"expected {expected} refs to 0x{addr:08X}, got {len(glyph_refs[addr])}")
        delta = EMERALD_GLYPH_NEW - EMERALD_GLYPH_BASE
        for addr, offsets in glyph_refs.items():
            packed = struct.pack("<I", addr + delta)
            for off in offsets:
                out[off:off + 4] = packed

    stwi_refs = []
    for off in range(0, EMERALD_CODE_END, 4):
        if struct.unpack_from("<I", rom, off)[0] == EMERALD_STWI_STATUS:
            if not _is_ldr_literal(rom, off):
                raise ValueError(f"non-LDR gSTWIStatus word at 0x{off:06X}")
            stwi_refs.append(off)
    if len(stwi_refs) != EMERALD_STWI_REFS:
        raise ValueError(f"expected {EMERALD_STWI_REFS} refs to 0x{EMERALD_STWI_STATUS:08X}, got {len(stwi_refs)}")
    packed = struct.pack("<I", target)
    for off in stwi_refs:
        out[off:off + 4] = packed
    return bytes(out)


def build_name(code):
    return f"emerald_switch_{code.lower()}_1_3.gba"            # named per patch: a cached build outlives an update


def built_rom(path, folder, code="BPRE"):
    """-> the patched ROM's path in `folder`, built once."""
    import bps
    target = os.path.join(folder, build_name(code))
    for old in OLD_BUILDS:
        if os.path.exists(os.path.join(folder, old)):
            os.remove(os.path.join(folder, old))
    if not os.path.exists(target):
        print("Patching your Emerald ROM.", flush=True)
        with open(os.path.join(HERE, f"emerald_{code.lower()}.bps"), "rb") as handle:
            rom = align_stwi_status(bps.apply(emerald_rom(path), handle.read()), code)
        with open(target + ".part", "wb") as handle:
            handle.write(rom)
        os.replace(target + ".part", target)
    else:
        emerald_rom(path)
    return target


def firered_base(path, keys, folder, code="BPRE"):
    """-> the path of the console's cartridge, or "none": the stream then goes with no help from it."""
    if not path:
        print("No game file: the stream takes about 5 h 30 min.", flush=True)
        return "none"
    from pokeldn.switch import cartridge
    try:
        rom = cartridge.read(path, keys)
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        sys.exit(f"Could not read {os.path.basename(path)}: {exc}")
    name, sha1 = CARTRIDGES[code]
    if hashlib.sha1(rom).hexdigest() != sha1:
        found = rom[0xAC:0xB0].decode("ascii", "replace")
        sys.exit(f"That file is not {name} from the Switch title"
                 + (f" (it holds {CARTRIDGES[found][0]}: pick that game)" if found in CARTRIDGES else "")
                 + ". Leave the file empty to go without it.")
    target = os.path.join(folder, f"{code.lower()}.gba")
    with open(target, "wb") as handle:
        handle.write(rom)
    return target


def agreed(args):
    from pokeldn import popup
    if args.agree:
        return True
    if not popup.available():
        print(WARNING)
        sys.exit("Pass --agree to go on.")
    answers, answer = queue.Queue(), []
    popup.set_dispatcher(answers.put)
    popup.confirm("Before you stream", WARNING, "Stream Emerald", "Not now", tone="warning",
                  on_agree=lambda: answer.append(True), on_disagree=lambda: answer.append(False),
                  on_dismiss=lambda: answer.append(False))
    while not answer:
        try:
            answers.get(timeout=0.5)()
        except queue.Empty:
            pass
    return answer[0]


def check_app(needs=NEEDS_APP, why="this one can write over the FireRed save"):
    import pokeldn
    if tuple(int(n) for n in pokeldn.__version__.split(".")[:3]) < needs:
        sys.exit(f"Update pokeldn to {'.'.join(map(str, needs))} first: {why}.")


def session(args, *flags):
    from pokeldn.plugins import run_launcher
    return run_launcher("bin/frlg_mg_host.py", ["--live", "--keys", args.keys, "--version", "firered", *flags])


def backup(args, library, folder):
    path = os.path.join(library, f"FireRed {time.strftime('%Y-%m-%d %H%M%S')}.sav")
    status = session(args, "--save-backup", path, "--save-resume-dir", os.path.join(folder, "partial"))
    if status == 0:
        print(f"Your FireRed save is in {path}. Keep the game open, or close it: part 3 works either way.")
    return status


def stream(args, library, folder):
    if not any(name.endswith(".sav") for name in os.listdir(library)):
        sys.exit("Back up the FireRed save first: choose part 1.")
    if args.cartridge != "BPRE":
        check_app(NEEDS_APP_CART, "this one streams only into English FireRed")
    rom = built_rom(args.emerald, folder, args.cartridge)
    base = firered_base(args.firered, args.keys, folder, args.cartridge)
    if not agreed(args):
        return 0
    status = session(args, "--rom-transfer", rom, "--rom-base", base, *PACING)
    if status == 0:
        from pokeldn import panel
        panel.show("swap", "Emerald is running", [
            "It lasts until the game is closed; a soft reset is safe.",
            "Save in the game, and keep the application open."], tone="ok")
    return status


def main(argv=None):
    args = build_parser().parse_args(argv)
    from pokeldn.plugins import data_folder, library_folder
    folder, library = data_folder(PLUGIN), library_folder(PLUGIN)
    os.makedirs(folder, exist_ok=True)
    os.makedirs(library, exist_ok=True)
    if args.step == "backup":
        return backup(args, library, folder)
    if args.step == "save":
        if not args.emerald_save:
            sys.exit("Choose the Emerald save.")
        check_app()
        return session(args, "--save-restore-emerald", args.emerald_save)
    if not args.emerald:
        sys.exit("Choose your Emerald ROM.")
    return stream(args, library, folder)


if __name__ == "__main__":
    sys.exit(main())
