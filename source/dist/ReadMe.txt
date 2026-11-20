Adv98X @VERSION@
================

A portable engine for PC-9801 games made with Adv98V 1.70.54, the adventure-game engine of
Tuneup and Ides. Adv98X runs a game's original scripts unmodified and reproduces its PC-98
release: text, pictures, palette effects, menus, click maps, saves and the FM music.

This archive holds only the engine. It contains none of the game.


What you need
-------------

* SDL 3 (the shared library: libSDL3 from your package manager, Homebrew or MacPorts).
* The game's pack, built from your own copy of the game with the game's tools (its source's
  docs/game-data.md: `make data SRC=...` then `make pack`). Put it next to the adv98x program
  (as adv98x.pak, or as the only .pak there), or name it with --pak.


Playing
-------

    ./adv98x                      in the game's own language
    ./adv98x --lang en            in another the pack has, e.g. English
    ./adv98x --help               all options

Options: --lang CODE, --fullscreen, --window WxH, --scale integer|aspect|fit|stretch,
--volume 0..100, --no-audio, --opn ymfm|lite, --storage DIR, --pak FILE, --view (browse the
pictures).

The keyboard is the PC-98's: Return and Space go on, the cursor keys move in menus, Esc
cancels, Shift held skips text. The mouse works as on the PC-98: click to go on, click menu
items and places on the maps, right-click to cancel.

  F11 or Alt+Return   fullscreen on/off
  F12                 next scaling mode
  Kana / Scroll Lock  kana input on/off (name entry; the JIS kana layout)
  Ctrl+Shift+R        reset: the game starts again at its title (saves are kept)
  Shift+Esc           quit at once

An ending may stay on its last screen for ever, as on the PC-98, where the player switched the
machine off. Press Ctrl+Shift+R to return to the title.


Saves
-----

Saves and the player's name are kept as the original's files (FLAG0..FLAG9, NAME.DEF) in
$XDG_DATA_HOME/adv98x/<game> (default ~/.local/share/adv98x/<game>), or in the directory given
with --storage. Files from a PC-98 copy of the game can be put there and are used as they
are.


Licence
-------

Adv98X is free software under the GNU General Public License, version 3 or later (LICENSE).
Its source is available where you got this archive. The FM sound is made by ymfm (Aaron
Giles, BSD 3-Clause licence: LICENSE.ymfm).
