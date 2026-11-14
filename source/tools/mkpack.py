#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the Adv98X game pack (nova.pak) from the imported original game.

usage: mkpack.py [--original DIR] [--fonts DIR] [--game nova] -o nova.pak

DIR is resources/original/ as `gamedata.py import` fills it: pc98/A..D (the four floppies of
the PC-98 release) and en/MES (the scripts of Fuzion's English translation). Every file taken
is checked against resources/inventory.tsv (name and md5); the build stops on anything missing
or different. The dumped copy's own state (FLAG0..FLAG5, NAME.DEF) is never packed: a new
install starts without saves and without a player name, like a new copy of the game.

Contents (types and the layout: source/engine/pack/pack.h, tools/xpak.py):
  GPC      every picture once, under its bare name (docs/re/disks.md §3, the "simpler
           alternative"): all copies of a name on the four disks are identical except NV43A,
           where disk B's file is taken (§4: the two files show the same picture; B's is the
           one six of the nine references load)
  USO      the 28 songs, CLM the four click maps (disk A)
  MES      scripts per language: ja = the 118 scripts of disk A; en = the 117 English scripts
           plus the Japanese ones the translation does not replace (RUN.MES). NV.INI is not
           packed: the engine starts where it ends (docs/re/interpreter.md §7)
  FONT     font16 (JIS X 0208, 16x16) and font8 (half-width, 8x16), from xfont.py (--no-bold)
  STRINGS  "messages" per language: the interpreter's three built-in messages (save failed,
           nothing saved there, load failed) as script fragments ending in FF FF. Japanese:
           the original fragments, taken from the user's NV.OVL (unpacked with
           re-tools/exeunpack.py, 0xD95B-0xD9E2); other languages: our own text in the same
           frame (text-clear 0, colour 15, the text, wait, text-clear 0)
  BLOB     "cursor": AdvBIOS's default mouse pointer (01AB:09D8 of the user's NV.OV1: width in
           bytes, height, AND mask, image; advbios.md §6.2)
  META     "profile" (the game: title, start script, plug-in modules, default language),
           "lang" per language (encoding, name), "meta" (pack format)
Plug-in code (.TCM) and the engine executables are not packed: the engine replaces them.
"""
import argparse
import collections
import hashlib
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(ROOT, 're-tools'))
import exeunpack  # noqa: E402
import gamedata  # noqa: E402
import xpak      # noqa: E402

DISKS = 'ABCD'

# The game profiles this tool can build (engine/game/profile.c reads the result).
PROFILES = {
    'nova': {
        'title': 'NOVA ～魅入られた肢体～',
        'start': 'RUN',
        'modules': 'chgfonth,palch,whiteh,inputnam,acte1',
        'lang': 'ja',
        # duplicated picture names whose files differ, and the disk whose file is taken
        'picture_choice': {'NV43A': 'B'},
        'languages': {'ja': '日本語', 'en': 'English'},
        # the built-in messages: where they are in the unpacked NV.OVL, and our English text
        'messages_at': (0xD95B, 0xD9E3),
        'messages_en': ('Could not save.', 'Nothing is saved there.', 'Could not load.'),
    },
}

# the frame of a built-in message, as in the original fragments: text-clear 0, text-color 15,
# the text, wait, text-clear 0, end of segment
MSG_HEAD = bytes([0xAA, 0x23, 0xA8, 0x28, 0x0F])
MSG_TAIL = bytes([0xAB, 0xAA, 0x23, 0xFF, 0xFF])


def original_messages(nvovl, at):
    """The three fragments from the interpreter image (checked to be framed as expected)."""
    img = exeunpack.unpack(nvovl, log=lambda *a: None)
    hdr = struct.unpack_from('<H', img, 8)[0] * 16
    blob = img[hdr + at[0]:hdr + at[1]]
    frags = blob.split(b'\xff\xff')
    if len(frags) != 4 or frags[3] or any(not f.startswith(MSG_HEAD) for f in frags[:3]):
        die('NV.OVL: the built-in messages are not where expected')
    return blob


def default_cursor(nvov1):
    """AdvBIOS's default pointer shape: width (bytes), height, mask and image rows"""
    img = exeunpack.unpack(nvov1, log=lambda *a: None)
    hdr = struct.unpack_from('<H', img, 8)[0] * 16
    at = hdr + 0x1AB0 + 0x9D8
    w, h = img[at], img[at + 1]
    if not (1 <= w <= 5 and 1 <= h <= 40):
        die('NV.OV1: the default pointer is not where expected')
    return img[at:at + 2 + 2 * w * h]


def own_messages(texts):
    return b''.join(MSG_HEAD + b'!' + t.encode('ascii') + b'\0' + MSG_TAIL for t in texts)


def die(msg):
    sys.exit('mkpack: ' + msg)


def read_checked(inv, original, release, path):
    """The file's bytes, after checking it against the inventory row."""
    row = inv.get((release, path))
    if row is None:
        die('%s/%s is not in resources/inventory.tsv' % (release, path))
    if 'never packed' in row.kind:
        die('%s/%s must never be packed (%s)' % (release, path, row.kind))
    full = os.path.join(original, release, path)
    if not os.path.exists(full):
        die('%s is missing: import the game first (make data SRC=...; docs/game-data.md)' % full)
    data = open(full, 'rb').read()
    if hashlib.md5(data).hexdigest() != row.md5:
        die('%s differs from the inventory (md5)' % full)
    return data


def rows_of(inv, release, kind, prefix=''):
    return sorted(p for (r, p), row in inv.items()
                  if r == release and row.kind == kind and p.startswith(prefix))


def base(path):
    return os.path.splitext(os.path.basename(path))[0].upper()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--original', default=os.path.join(ROOT, 'resources', 'original'))
    ap.add_argument('--fonts', help='directory with k16.xfnt and ank8.xfnt (xfont.py --no-bold)')
    ap.add_argument('--game', default='nova', choices=sorted(PROFILES))
    ap.add_argument('-o', '--output', required=True)
    a = ap.parse_args()
    prof = PROFILES[a.game]

    inv = {(r.release, r.path): r for r in gamedata.load_inventory()}
    pk = xpak.Pack()
    counts = collections.Counter()

    # pictures: one per name
    by_name = collections.defaultdict(dict)          # name -> {disk: data}
    for path in rows_of(inv, 'pc98', 'image'):
        if not path.upper().endswith('.GPC'):
            continue
        by_name[base(path)][path[0]] = read_checked(inv, a.original, 'pc98', path)
    for name in sorted(by_name):
        copies = by_name[name]
        if len(set(copies.values())) > 1:
            disk = prof['picture_choice'].get(name)
            if disk not in copies:
                die('picture %s differs between disks %s and has no rule'
                    % (name, ''.join(sorted(copies))))
            data = copies[disk]
        else:
            data = next(iter(copies.values()))
        pk.add(name, xpak.T_GPC, xpak.L_ANY, data)
        counts['pictures'] += 1

    for path in rows_of(inv, 'pc98', 'music', 'A/'):
        pk.add(base(path), xpak.T_USO, xpak.L_ANY, read_checked(inv, a.original, 'pc98', path))
        counts['songs'] += 1
    for path in rows_of(inv, 'pc98', 'map hit table', 'A/'):
        pk.add(base(path), xpak.T_CLM, xpak.L_ANY, read_checked(inv, a.original, 'pc98', path))
        counts['click maps'] += 1

    # scripts per language
    ja = {base(p): read_checked(inv, a.original, 'pc98', p)
          for p in rows_of(inv, 'pc98', 'script', 'A/MES/')}
    en = {base(p): read_checked(inv, a.original, 'en', p)
          for p in rows_of(inv, 'en', 'script', 'MES/')}
    if not ja:
        die('no Japanese scripts in the inventory')
    for name, data in sorted(ja.items()):
        pk.add(name, xpak.T_MES, xpak.L_JA, data)
    counts['ja scripts'] = len(ja)
    langs = ['ja']
    if en:
        for name in sorted(set(ja) | set(en)):
            pk.add(name, xpak.T_MES, xpak.L_EN, en.get(name, ja.get(name)))
        counts['en scripts'] = len(en)
        counts['en from ja'] = len(set(ja) - set(en))
        langs.append('en')
    for lang in langs:
        pk.add('lang', xpak.T_META, xpak.LANG_IDS[lang],
               ('encoding=cp932\nname=%s\n' % prof['languages'][lang]).encode('utf-8'))
    nvovl = read_checked(inv, a.original, 'pc98', 'A/NV.OVL')
    pk.add('messages', xpak.T_STRINGS, xpak.L_JA, original_messages(nvovl, prof['messages_at']))
    if 'en' in langs:
        pk.add('messages', xpak.T_STRINGS, xpak.L_EN, own_messages(prof['messages_en']))
    pk.add('cursor', xpak.T_BLOB, xpak.L_ANY,
           default_cursor(read_checked(inv, a.original, 'pc98', 'A/NV.OV1')))

    if a.fonts:
        for name, fname in (('font16', 'k16.xfnt'), ('font8', 'ank8.xfnt')):
            f = os.path.join(a.fonts, fname)
            if not os.path.exists(f):
                die('%s is missing (xfont.py --no-bold)' % f)
            pk.add(name, xpak.T_FONT, xpak.L_ANY, open(f, 'rb').read())
            counts['fonts'] += 1

    profile = ''.join('%s=%s\n' % (k, prof[k]) for k in ('title', 'start', 'modules', 'lang'))
    pk.add('profile', xpak.T_META, xpak.L_ANY, profile.encode('utf-8'))
    pk.add('meta', xpak.T_META, xpak.L_ANY, b'format=1\ngame=%s\n' % a.game.encode('ascii'))

    data = pk.build(dedupe=True)
    os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
    with open(a.output, 'wb') as fo:
        fo.write(data)
    print('%s: %d entries, %d bytes (%s)' % (a.output, len(pk.entries), len(data),
                                           ', '.join('%s %d' % kv for kv in counts.items())))


if __name__ == '__main__':
    main()
