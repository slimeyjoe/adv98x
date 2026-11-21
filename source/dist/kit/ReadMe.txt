@NAME@: the pack-building kit
========================================

This kit turns your own copy of a PC-98 game into the pack (a .pak file) that the Adv98X engine
plays. It holds only tools and the list of the game's files; none of the game.


What you need
-------------

* Python 3.8 or newer (the standard library is enough), on any system.
* Your copy of the game: directories, disk images or archives (docs/game-data.md says which).


Building the pack
-----------------

    python3 makepak.py path/to/your/copy [more copies...]

The files are found by name and checked against the game's inventory (resources/inventory.tsv);
they are copied into resources/original/ here, and the pack is written to build/. Run it again
without arguments to rebuild the pack from what was imported.

Put the pack next to the adv98x program (the engine's release archive), or name it with --pak.


Licence
-------

The tools are free software under the GNU General Public License, version 3 or later (LICENSE).
The bitmap fonts in engine/source/lrvne/fonts/x11 keep their own licences (the COPYING files
there).
