#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build an Adv98X game pack from the imported original game.

usage: mkpack.py [--original DIR] --fonts DIR -o PACK

The game is the one tools/gamedir.py finds (GAME_DIR); its game.py says what the pack takes
(PACK), from which original files (ORIGINAL), and the pack's profile (PROFILE). DIR is its
resources/original/ as `gamedata.py import` fills it. Every file taken is checked against the
game's resources/inventory.tsv (name and md5); the build stops on anything missing or
different. Rows whose kind says "never packed" (the dumped copy's own saves and player's name)
are refused: a new install starts without them, like a new copy of the game.

The pack is lrvne's (source/lrvne/include/lrvne/pack.h, written with its tools/lrvne/xpak.py).
A file of the game is an entry under its own name ("NAME.GPC"), which is how the scripts ask
for it; its type is one of the engine's (TYPES below, engine/ax.h enum ax_pack_type):
  gpc      every picture once: where copies of a name on several disks differ, the game's
           PACK.pictures.choice names the disk whose copy is taken
  uso      the songs, clm the click maps
  mes      scripts per language (PACK.scripts); a language with a fallback takes the fallback
           language's script where it has none of its own. The start file is not packed: the
           profile's `start` is the script it starts (docs/re/interpreter.md §7)
and what the engine needs beside them:
  font     font16 (JIS X 0208, 16x16) and font8 (half-width, 8x16): the tables `make pack`
           makes from the X.Org bitmap fonts with lrvne's xfont (--no-bold)
  strings  "messages" per language: the interpreter's three built-in messages (save failed,
           nothing saved there, load failed) as script fragments ending in FF FF. The
           original's language: the original fragments, taken from the player's interpreter
           (ORIGINAL.interpreter, unpacked with re-tools/exeunpack.py); other languages: the
           game's own text (PACK.messages) in the same frame (text-clear 0, colour 15, the
           text, wait, text-clear 0)
  blob     "cursor": AdvBIOS's default mouse pointer (ORIGINAL.bios.cursor_at: width in bytes,
           height, AND mask, image; advbios.md §6.2)
  meta     "profile": the game's PROFILE (engine/game/profile.c has the keys), and "langs",
           the pack writer's list of the languages
Plug-in code (.TCM) and the original executables are not packed: the engine replaces them.
"""
import argparse
import collections
import hashlib
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))          # the engine's
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(ROOT, 're-tools'))
sys.path.insert(2, os.path.join(HERE, '..', 'lrvne', 'tools'))
import exeunpack  # noqa: E402
import gamedata  # noqa: E402
import gamedir  # noqa: E402
from lrvne import profile, xpak  # noqa: E402

# the engine's entry types (engine/ax.h)
T_GPC, T_USO, T_MES, T_CLM = range(xpak.T_ENGINE, xpak.T_ENGINE + 4)
TYPES = xpak.TypeRegistry({T_GPC: 'gpc', T_USO: 'uso', T_MES: 'mes', T_CLM: 'clm'})

# the frame of a built-in message, as in the original fragments: text-clear 0, text-color 15,
# the text, wait, text-clear 0, end of segment
MSG_HEAD = bytes([0xAA, 0x23, 0xA8, 0x28, 0x0F])
MSG_TAIL = bytes([0xAB, 0xAA, 0x23, 0xFF, 0xFF])


def original_messages(exe, at):
    """The three fragments from the interpreter image (checked to be framed as expected)."""
    img = exeunpack.unpack(exe, log=lambda *a: None)
    hdr = struct.unpack_from('<H', img, 8)[0] * 16
    blob = img[hdr + at[0]:hdr + at[1]]
    frags = blob.split(b'\xff\xff')
    if len(frags) != 4 or frags[3] or any(not f.startswith(MSG_HEAD) for f in frags[:3]):
        die('the interpreter: the built-in messages are not where expected')
    return blob


def default_cursor(exe, at):
    """AdvBIOS's default pointer shape: width (bytes), height, mask and image rows"""
    img = exeunpack.unpack(exe, log=lambda *a: None)
    hdr = struct.unpack_from('<H', img, 8)[0] * 16
    w, h = img[hdr + at], img[hdr + at + 1]
    if not (1 <= w <= 5 and 1 <= h <= 40):
        die('AdvBIOS: the default pointer is not where expected')
    return img[hdr + at:hdr + at + 2 + 2 * w * h]


def own_messages(texts):
    return b''.join(MSG_HEAD + b'!' + t.encode('ascii') + b'\0' + MSG_TAIL for t in texts)


def die(msg):
    sys.exit('mkpack: ' + msg)


def read_checked(inv, original, release, path):
    """The file's bytes, after checking it against the inventory row."""
    row = inv.get((release, path))
    if row is None:
        die('%s/%s is not in the inventory' % (release, path))
    if 'never packed' in row.get('kind'):
        die('%s/%s must never be packed (%s)' % (release, path, row.get('kind')))
    full = os.path.join(original, release, path)
    if not os.path.exists(full):
        die('%s is missing: import the game first (make data SRC=...; the game\'s '
            'docs/game-data.md)' % full)
    data = open(full, 'rb').read()
    if hashlib.md5(data).hexdigest() != row.md5:
        die('%s differs from the inventory (md5)' % full)
    return data


rows_of = gamedata.rows_of


def name(path):
    return os.path.basename(path).upper()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--original')
    ap.add_argument('--fonts', required=True,
                    help='directory with k16.xfnt and ank8.xfnt (lrvne xfont --no-bold)')
    ap.add_argument('-o', '--output', required=True)
    a = ap.parse_args()
    game = gamedir.load()
    pack, orig = game.PACK, game.ORIGINAL
    langs = tuple(pack['languages'])
    a.original = a.original or gamedir.original()

    inv = {(r.get('release'), r.name): r for r in gamedata.load_inventory()}
    pk = xpak.PackWriter(TYPES, langs=langs)
    counts = collections.Counter()

    def read(release, path):
        return read_checked(inv, a.original, release, path)

    # pictures: one per name
    part = pack['pictures']
    by_name = collections.defaultdict(dict)          # name -> {disk: data}
    for path in rows_of(inv, part):
        by_name[name(path)][path.split('/')[0]] = read(part['release'], path)
    for pic in sorted(by_name):
        copies = by_name[pic]
        if len(set(copies.values())) > 1:
            disk = part.get('choice', {}).get(os.path.splitext(pic)[0])
            if disk not in copies:
                die('picture %s differs between disks %s and has no rule'
                    % (pic, ', '.join(sorted(copies))))
            data = copies[disk]
        else:
            data = next(iter(copies.values()))
        pk.add(pic, T_GPC, data)
        counts['pictures'] += 1

    for key, typ, label in (('songs', T_USO, 'songs'), ('click_maps', T_CLM, 'click maps')):
        part = pack[key]
        for path in rows_of(inv, part):
            pk.add(name(path), typ, read(part['release'], path))
            counts[label] += 1

    # scripts per language
    scripts = {lang: {name(p): read(part['release'], p) for p in rows_of(inv, part)}
               for lang, part in pack['scripts'].items()}
    if not scripts[langs[0]]:
        die('no scripts of the original (%s) in the inventory' % langs[0])
    present = [lang for lang in langs if scripts.get(lang)]
    for lang in present:
        own = scripts[lang]
        fallback = pack['scripts'][lang].get('fallback')
        base = scripts[fallback] if fallback else {}
        for script in sorted(set(own) | set(base)):
            pk.add(script, T_MES, own.get(script, base.get(script)), lang=lang)
        counts['%s scripts' % lang] = len(own)
        if fallback:
            counts['%s from %s' % (lang, fallback)] = len(set(base) - set(own))

    interp = orig['interpreter']
    pk.add('messages', xpak.T_STRINGS,
           original_messages(read(orig['release'], interp['path']), interp['messages_at']),
           lang=langs[0])
    for lang in present[1:]:
        pk.add('messages', xpak.T_STRINGS, own_messages(pack['messages'][lang]), lang=lang)
    bios = orig['bios']
    pk.add('cursor', xpak.T_BLOB, default_cursor(read(orig['release'], bios['path']),
                                                 bios['cursor_at']))

    for entry, fname in (('font16', 'k16.xfnt'), ('font8', 'ank8.xfnt')):
        f = os.path.join(a.fonts, fname)
        if not os.path.exists(f):
            die('%s is missing (make pack makes it)' % f)
        pk.add(entry, xpak.T_FONT, open(f, 'rb').read())
        counts['fonts'] += 1

    pk.add('profile', xpak.T_META, profile.dumps(game.PROFILE).encode('utf-8'))

    data = pk.build(dedupe=True)
    os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
    with open(a.output, 'wb') as fo:
        fo.write(data)
    print('%s: %d entries, %d bytes (%s)' % (a.output, len(pk.names()) + 1, len(data),
                                           ', '.join('%s %d' % kv for kv in counts.items())))


if __name__ == '__main__':
    main()
