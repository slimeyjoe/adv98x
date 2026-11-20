#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""The original game data: import it from your copies of the releases, check it, derive from it.

No repository carries the game, only an inventory of its files: the game's
resources/inventory.tsv (release, path, size, mtime, md5, kind). This is lrvne's import
framework (source/lrvne/tools: lrvne.inventory, which finds the files in whatever you have:
directories, zip/7z/rar archives, floppy and hard-disk images, nested in any order) with what
only the game knows, from its game.py (tools/gamedir.py finds it): IMPORT, the framework's hooks
(where a release goes, which rows are required, the game's own archive formats, how `scan`
names what it finds); PACK and ORIGINAL, what `derive` works on.

usage (python3 -I tools/gamedata.py ...):
  import [SRC...] [--out DIR]    copy the files of the inventory from your media into
                                 resources/original/<release>/<path> (not committed)
  check [-q] [--out DIR]         verify that tree; exit status 1 while a required file is
                                 missing
  scan [SRC...]                  print inventory rows for what SRC holds (maintenance; the
                                 game's IMPORT scan_row names them)
  derive [PART...] [--python PY] everything the documents and tests refer to, see below
SRC defaults to the directories named in the LRVNE_MEDIA environment variable.

derive: made from resources/original/ into resources/derived/ (not committed) by the tools in
re-tools/ and source/tools/:
    exe      the unpacked executables: the interpreter, AdvBIOS and ORIGINAL.unpack
             (exeunpack.py)                                      -> derived/exe/
    scripts  listings, strings, graph of the scripts of every language (mesdis.py, mesgraph.py):
             the original's with the start file                 -> derived/scripts/
             the others                                          -> derived/scripts-<lang>/
    images   every picture of every disk as PNG (gpc.py)         -> derived/images/gpc/
    listing  annotated listings of the plug-ins (tcmtool.py), of AdvBIOS and of the interpreter
             (dis16.py with docs/re/listing/*-names.tsv)        -> derived/listing/
    vgm      reference recordings (VGM and register-write logs) of all songs from the original
             driver under emulation (usdemu.py; needs unicorn: --python names a Python that
             has it)                                             -> derived/music/vgm/
  Default: all parts; a part whose Python module is missing is skipped with a note.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(HERE, '..', 'lrvne', 'tools'))
import gamedir                # noqa: E402
from lrvne import inventory   # noqa: E402

ENGINE = gamedir.ENGINE


def load_inventory():
    """The rows of the game's resources/inventory.tsv (lrvne.inventory.Row: name = the path
    inside the release, get('release'), get('kind'))."""
    return inventory.Inventory.load(gamedir.inventory()).rows


def rows_of(inv, part):
    """The paths of the rows a part of the game's description selects: release, kind, and the
    path's prefix and suffix. `inv` maps (release, path) to rows."""
    prefix, suffix = part.get('prefix', ''), part.get('suffix', '').upper()
    return sorted(p for (r, p), row in inv.items()
                  if r == part['release'] and row.get('kind') == part['kind']
                  and p.startswith(prefix) and p.upper().endswith(suffix))


def hooks():
    return inventory.Hooks(**gamedir.load().IMPORT)


# ---- derive --------------------------------------------------------------------------------

DERIVE_PARTS = ('exe', 'scripts', 'images', 'listing', 'vgm')


def cmd_derive(a):
    game = gamedir.require('gamedata')
    desc = gamedir.load(game)
    orig = desc.ORIGINAL
    retools = os.path.join(ENGINE, 're-tools')
    der = gamedir.derived(game)
    a.out = a.out or gamedir.original(game)
    inv = {(r.get('release'), r.name): r for r in load_inventory()}

    def original(release, path):
        return os.path.join(a.out, release, path)

    interp = original(orig['release'], orig['interpreter']['path'])
    bios = original(orig['release'], orig['bios']['path'])
    if not os.path.exists(interp):
        sys.exit('gamedata: %s is missing: import the game first' % interp)
    exe_dir = os.path.join(der, 'exe')

    def unpacked(path):
        return os.path.join(exe_dir, os.path.basename(path))
    py = a.python or sys.executable
    env = dict(os.environ, GAME_DIR=game)

    def run(interp, *args):
        cmd = [interp] + (['-I'] if interp == sys.executable else []) + list(args)
        r = subprocess.run(cmd, cwd=game, env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True)
        tail = r.stdout.strip().splitlines()[-1:] or ['']
        print('  %s %s' % ('ok  ' if r.returncode == 0 else 'FAIL', tail[0][:110]))
        return r.returncode == 0

    def has(interp, mod):
        return subprocess.run([interp, '-c', 'import ' + mod], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0
    ok = True
    for part in a.parts or DERIVE_PARTS:
        print('derive %s:' % part)
        if part == 'exe':
            os.makedirs(exe_dir, exist_ok=True)
            for f in [interp, bios] + [original(orig['release'], p) for p in orig.get('unpack', ())]:
                ok &= run(sys.executable, os.path.join(retools, 'exeunpack.py'), f, unpacked(f))
        elif part == 'scripts':
            langs = desc.PACK['languages']
            parts = desc.PACK['scripts']
            files = {lang: [original(parts[lang]['release'], p) for p in rows_of(inv, parts[lang])
                            if os.path.exists(original(parts[lang]['release'], p))]
                     for lang in langs}
            files[langs[0]].append(original(orig['release'], orig['start']['path']))
            ok &= run(sys.executable, os.path.join(retools, 'mesdis.py'), 'check',
                      *[f for lang in langs for f in files[lang]])
            for i, lang in enumerate(langs):
                if files[lang]:
                    out = os.path.join(der, 'scripts' if i == 0 else 'scripts-' + lang)
                    ok &= run(sys.executable, os.path.join(retools, 'mesdis.py'), 'export', out,
                              *files[lang])
        elif part == 'images':
            pics = desc.PACK['pictures']
            files = [original(pics['release'], p) for p in rows_of(inv, pics)]
            ok &= run(sys.executable, os.path.join(HERE, 'gpc.py'), 'png', *files, '-o',
                      os.path.join(der, 'images', 'gpc'), '--disk-prefix')
        elif part == 'listing':
            if not has(py, 'capstone'):
                print('  skipped: %s has no capstone (--python)' % py)
                continue
            plugins = orig['plugins']
            ok &= run(py, os.path.join(retools, 'tcmtool.py'), 'list', '--dir',
                      original(plugins['release'], plugins['prefix']))
            # AdvBIOS and the interpreter, named from docs/re/listing/
            names = os.path.join(ENGINE, 'docs', 're', 'listing')
            lst = os.path.join(der, 'listing')
            os.makedirs(lst, exist_ok=True)
            ok &= run(py, os.path.join(retools, 'dis16.py'), unpacked(bios),
                      '--names', os.path.join(names, 'advbios-names.tsv'),
                      '--out', os.path.join(lst, 'advbios.lst'))
            ovl_names = os.path.join(lst, 'nvovl-names.seg.tsv')     # bare offsets -> 0000:OFF
            with open(os.path.join(names, 'nvovl-names.tsv'), encoding='utf-8') as fi, \
                    open(ovl_names, 'w', encoding='utf-8') as fo:
                for line in fi:
                    if line.strip() and not line.startswith('#') and '\t' in line:
                        fo.write('0000:' + line)
            ok &= run(py, os.path.join(retools, 'dis16.py'), unpacked(interp),
                      '--names', ovl_names, '--out', os.path.join(lst, 'nvovl.lst'))
        elif part == 'vgm':
            if not has(py, 'unicorn'):
                print('  skipped: %s has no unicorn (--python)' % py)
                continue
            if not os.path.exists(unpacked(bios)):
                print('  skipped: derive exe first')
                continue
            ok &= run(py, os.path.join(retools, 'usdemu.py'), '--all', '--logs')
        else:
            sys.exit('gamedata: unknown part %s (parts: %s)' % (part, ' '.join(DERIVE_PARTS)))
    return 0 if ok else 1


def add_derive_arguments(p):
    p.add_argument('parts', nargs='*')
    p.add_argument('--python')
    p.add_argument('--out', default=None)


def main():
    game = gamedir.require('gamedata')
    return inventory.run_cli(None, gamedir.inventory(game), gamedir.original(game), hooks=hooks(),
                             prog='gamedata', description=__doc__.split('\n')[0],
                             commands={'derive': (add_derive_arguments, cmd_derive)})


if __name__ == '__main__':
    sys.exit(main())
