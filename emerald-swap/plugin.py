"""pokeldn plugin: Emerald in place of a running English FireRed, built from the player's own ROM."""
from pokeldn.plugins import Field, Tool

MENU = "Title screen: Mystery Gift, Wonder Cards, Friend. Wait on the search screen."
JOIN = "Press Start here, then pick POKELDN when it appears."


def register(api):
    api.add_tool("frlg", Tool(
        "emerald-swap", "Emerald swap", "swap.py",
        "Stream your own Emerald ROM into a running English FireRed, then play it. Every console is stock; "
        "it lasts until the game is closed.",
        (("Back up first: nothing else starts until a backup exists.", ("--step", "backup")),
         (MENU, ("--step", "backup")), (JOIN, ("--step", "backup")),
         ("Keep the game open from here on: the next two parts need the same launch. Skip this part "
          "when Emerald has saved on this console before: its save is still there.", ("--step", "save")),
         (MENU, ("--step", "save")), (JOIN, ("--step", "save")),
         ("Turn the console's auto-sleep off and keep it charging. A console that sleeps stops the "
          "stream. Back on the title screen, run this part again: it goes on from where it stopped. A "
          "black screen means closing the game and starting again from part 2.", ("--step", "stream")),
         (MENU, ("--step", "stream")), (JOIN, ("--step", "stream")),
         ("Leave it. With your FireRed file it takes about 3 h 20 min, without about 5 h 30 min. "
          "Emerald starts on its own.", ("--step", "stream")),
         ("In a later launch FireRed says the save file is corrupted, then loads its own copy: press A. "
          "Do not save in FireRed unless part 1 has run: that save replaces Emerald's.", ("--step", "stream"))),
        fields=(
            Field("--step", "Part", "choice", default="backup",
                  choices=(("backup", "1. Back up the FireRed save"),
                           ("save", "2. Put an Emerald save on the console (optional)"),
                           ("stream", "3. Stream Emerald")),
                  help="In this order, without closing the game after part 2."),
            Field("--emerald-save", "Emerald save", "file", exts=("sav",), when=("--step", "save"),
                  required=True, help="A 128 KB Emerald .sav. It is loaded when Emerald starts."),
            Field("--emerald", "Your Emerald ROM", "file", exts=("gba", "zip"), when=("--step", "stream"),
                  required=True, help="Pokemon Emerald, USA/Europe, as a .gba or a .zip holding one. "
                                      "The plugin carries a patch and no game."),
            Field("--firered", "Your FireRed (optional)", "file", exts=("gba", "nsp", "xci"),
                  when=("--step", "stream"),
                  help="English FireRed as a .gba or the game's package. It cuts the stream by 40%."),
        )))
