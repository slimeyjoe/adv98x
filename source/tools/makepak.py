#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""makepak - build a game's pack from the player's own copy, with nothing but Python 3.

usage: python3 -I makepak.py [SRC...] [--original DIR] [--x11fonts DIR] [-o PACK]

For the game tools/gamedir.py finds (GAME_DIR, or the nearest directory with a game.py):
  1. with SRC: import the game's files from your copies (directories, archives, disk images:
     the game's docs/game-data.md says what is accepted) into its resources/original/, checked
     against its inventory (tools/gamedata.py import); without SRC, what was imported before;
  2. make the pack's fonts from the X.Org bitmap fonts lrvne carries (lrvne's xfont);
  3. build the pack (tools/mkpack.py), by default build/<the game's PACK.name>.
`make pack` in a game's directory runs steps 2 and 3; a game's pack-building kit
(tools/mkkit.py) is this tool with what it needs, for players without a compiler or make.
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gamedir  # noqa: E402

LRVNE = os.path.join(HERE, '..', 'lrvne')
FONTS = (('ank8.xfnt', '8x16rk.bdf'), ('k16.xfnt', 'jiskan16.bdf'))


def run(*args):
    r = subprocess.run([sys.executable, '-I'] + list(args))
    if r.returncode:
        sys.exit(r.returncode)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('src', nargs='*', help='your copies of the game')
    ap.add_argument('--original', help='the imported files (default: the game\'s resources/original)')
    ap.add_argument('--x11fonts', default=os.path.join(LRVNE, 'fonts', 'x11'))
    ap.add_argument('-o', '--output')
    a = ap.parse_args()
    game = gamedir.require('makepak')
    os.environ['GAME_DIR'] = game                 # for the tools run below
    original = a.original or gamedir.original(game)
    if a.src:
        run(os.path.join(HERE, 'gamedata.py'), 'import', '--out', original, *a.src)
    run(os.path.join(HERE, 'gamedata.py'), 'check', '-q', '--out', original)
    fonts = gamedir.build(game, 'fonts')
    os.makedirs(fonts, exist_ok=True)
    for out, bdf in FONTS:
        subprocess.run([sys.executable, '-I', os.path.join(LRVNE, 'tools', 'lrvne'), 'xfont',
                        '--no-bold', '-o', os.path.join(fonts, out), os.path.join(a.x11fonts, bdf)],
                       stdout=subprocess.DEVNULL, check=True)
    pack = a.output or gamedir.build(game, gamedir.get('PACK.name', game))
    run(os.path.join(HERE, 'mkpack.py'), '--original', original, '--fonts', fonts, '-o', pack)


if __name__ == '__main__':
    main()
