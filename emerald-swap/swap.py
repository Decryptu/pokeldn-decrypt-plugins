#!/usr/bin/env python3
"""The Emerald swap tool: a backup, an optional Emerald save, then the stream, each through
bin/frlg_mg_host.py. Emerald comes from the player's ROM and emerald_bpre.bps."""
import argparse
import hashlib
import os
import queue
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = "emerald-swap"
EMERALD_SHA1 = "f3ae088181bf583e55daf962a92bb46f4f1d07b7"    # Pokemon Emerald (USA, Europe)
FIRERED_SHA1 = "baa452d0b24629dd7782cfc07a8984085dde1311"    # FireRed_e.gba in the Switch title
BUILD = "emerald_switch_bpre.gba"
PACING = ("--block-repeat", "1", "--inter-block-gap-frames", "8")
WARNING = ("Emerald lasts until the game is closed. Saving in Emerald replaces the FireRed save on "
           "the console, and FireRed may then refuse to start from it, with no way to restore your "
           "backup from the console. Do this only with a save you can lose.")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--step", choices=("backup", "save", "stream"), default="backup")
    parser.add_argument("--keys", default="", help="prod.keys")
    parser.add_argument("--emerald-save", default="")
    parser.add_argument("--emerald", default="")
    parser.add_argument("--firered", default="")
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


def built_rom(path, folder):
    """-> the patched ROM's path in `folder`, built once."""
    import bps
    target = os.path.join(folder, BUILD)
    if not os.path.exists(target):
        print("Patching your Emerald ROM.", flush=True)
        with open(os.path.join(HERE, "emerald_bpre.bps"), "rb") as handle:
            rom = bps.apply(emerald_rom(path), handle.read())
        with open(target + ".part", "wb") as handle:
            handle.write(rom)
        os.replace(target + ".part", target)
    else:
        emerald_rom(path)
    return target


def firered_base(path, keys, folder):
    """-> the path of the console's cartridge, or "none": the stream then goes with no help from it."""
    if not path:
        print("No FireRed file: the stream takes about 5 h 30 min.", flush=True)
        return "none"
    from pokeldn.switch import cartridge
    try:
        rom = cartridge.read(path, keys)
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        sys.exit(f"Could not read {os.path.basename(path)}: {exc}")
    if hashlib.sha1(rom).hexdigest() != FIRERED_SHA1:
        sys.exit("That is not English FireRed from the Switch title, the only game this swap has "
                 "been measured on. Leave the FireRed file empty to go without it.")
    target = os.path.join(folder, "firered_e.gba")
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
    rom = built_rom(args.emerald, folder)
    base = firered_base(args.firered, args.keys, folder)
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
        return session(args, "--save-restore-emerald", args.emerald_save)
    if not args.emerald:
        sys.exit("Choose your Emerald ROM.")
    return stream(args, library, folder)


if __name__ == "__main__":
    sys.exit(main())
