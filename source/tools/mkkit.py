#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""mkkit - a game's pack-building kit: what a player needs to build the pack, without a compiler.

usage: python3 -I mkkit.py -o KIT.zip [--name NAME]

For the game tools/gamedir.py finds. The kit is a zip of one directory NAME (default: the
archive's name without .zip) laid out as the game's repository is, so its tools find each other
as they do there:
  NAME/makepak.py            the player runs this: python3 makepak.py <your copies...>
  NAME/ReadMe.txt            the game's dist/kit/ReadMe.txt, else the engine's dist/kit/ReadMe.txt
  NAME/game.py, VERSION, resources/inventory.tsv, docs/game-data.md, LICENSE    (the game's)
  NAME/engine/source/tools/  gamedir, gamedata, mkpack, makepak
  NAME/engine/re-tools/      exeunpack (the original executables are unpacked for their data)
  NAME/engine/source/lrvne/  its Python tools, and the two X.Org bitmap fonts with their
                             licences
Everything in it is our own or free; none of it is the game. The zip is the same for the same
files: entries in order, with a fixed time.
"""
import argparse
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gamedir  # noqa: E402

ENGINE = gamedir.ENGINE
LRVNE = os.path.join(ENGINE, 'source', 'lrvne')
STAMP = (1993, 5, 28, 0, 0, 0)          # a fixed time for every entry

SHIM = '''#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the game's pack from your own copy: python3 makepak.py <your copies...> (ReadMe.txt)."""
import os
import runpy
import sys

here = os.path.dirname(os.path.abspath(__file__))
os.environ['GAME_DIR'] = here
sys.argv[0] = os.path.join(here, 'engine', 'source', 'tools', 'makepak.py')
runpy.run_path(sys.argv[0], run_name='__main__')
'''


def files(game):
    """(path in the kit, source file) of everything the kit holds."""
    out = []
    for rel in ('game.py', 'VERSION', 'resources/inventory.tsv', 'docs/game-data.md', 'LICENSE'):
        if os.path.exists(os.path.join(game, rel)):
            out.append((rel, os.path.join(game, rel)))
    readme = os.path.join(game, 'dist', 'kit', 'ReadMe.txt')
    if not os.path.exists(readme):
        readme = os.path.join(ENGINE, 'source', 'dist', 'kit', 'ReadMe.txt')
    out.append(('ReadMe.txt', readme))
    for t in ('gamedir.py', 'gamedata.py', 'mkpack.py', 'makepak.py'):
        out.append(('engine/source/tools/' + t, os.path.join(HERE, t)))
    out.append(('engine/re-tools/exeunpack.py', os.path.join(ENGINE, 're-tools', 'exeunpack.py')))
    pkg = os.path.join(LRVNE, 'tools', 'lrvne')
    for f in sorted(os.listdir(pkg)):
        if f.endswith('.py'):
            out.append(('engine/source/lrvne/tools/lrvne/' + f, os.path.join(pkg, f)))
    fonts = os.path.join(LRVNE, 'fonts', 'x11')
    for f in ('8x16rk.bdf', 'jiskan16.bdf', 'README.md', 'COPYING.jis-misc', 'COPYING.sony-misc'):
        out.append(('engine/source/lrvne/fonts/x11/' + f, os.path.join(fonts, f)))
    out.append(('engine/LICENSE', os.path.join(ENGINE, 'LICENSE')))
    return sorted(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('-o', '--output', required=True)
    ap.add_argument('--name')
    a = ap.parse_args()
    game = gamedir.require('mkkit')
    name = a.name or os.path.splitext(os.path.basename(a.output))[0]
    version = ''
    if os.path.exists(os.path.join(game, 'VERSION')):
        version = open(os.path.join(game, 'VERSION'), encoding='utf-8').read().strip()
    os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
    entries = files(game)
    with zipfile.ZipFile(a.output, 'w', zipfile.ZIP_DEFLATED) as z:
        def add(rel, data, mode=0o644):
            info = zipfile.ZipInfo(name + '/' + rel, STAMP)
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
        add('makepak.py', SHIM.encode('utf-8'), 0o755)
        for rel, src in entries:
            data = open(src, 'rb').read()
            if rel == 'ReadMe.txt':
                data = data.replace(b'@VERSION@', version.encode('ascii')).replace(
                    b'@NAME@', name.encode('ascii'))
            add(rel, data, 0o755 if rel.endswith('.py') and data.startswith(b'#!') else 0o644)
    print('%s: %d files' % (a.output, len(entries) + 1))


if __name__ == '__main__':
    main()
