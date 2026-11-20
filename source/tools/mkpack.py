"""Build an Adv98X game pack from the imported original game.

usage: mkpack.py [--original DIR] --fonts DIR [--game ID] -o PACK

DIR is resources/original/ as `gamedata.py import` fills it: pc98/A..D (the four floppies of
the PC-98 release) and en/MES (the scripts of Fuzion's English translation). Every file taken
is checked against resources/inventory.tsv (name and md5); the build stops on anything missing
or different. The dumped copy's own state (FLAG0..FLAG5, NAME.DEF) is never packed: a new
install starts without saves and without a player name, like a new copy of the game.

The pack is lrvne's (source/lrvne/include/lrvne/pack.h, written with its tools/lrvne/xpak.py).
A file of the game is an entry under its own name ("NV01.GPC"), which is how the scripts ask
for it; its type is one of the engine's (TYPES below, engine/ax.h enum ax_pack_type):
  gpc      every picture once (docs/re/disks.md §3, the "simpler alternative"): all copies of a
           name on the four disks are identical except the ones the game's profile below has a
           rule for (§4)
  uso      the songs, clm the click maps (disk A)
  mes      scripts per language: ja = the scripts of disk A; en = the English scripts plus the
           Japanese ones the translation does not replace (RUN.MES). NV.INI is not packed: the
           profile's `start` is the script it starts (docs/re/interpreter.md §7)
and what the engine needs beside them:
  font     font16 (JIS X 0208, 16x16) and font8 (half-width, 8x16): the tables `make pack`
           makes from the X.Org bitmap fonts with lrvne's xfont (--no-bold)
  strings  "messages" per language: the interpreter's three built-in messages (save failed,
           nothing saved there, load failed) as script fragments ending in FF FF. Japanese:
           the original fragments, taken from the user's NV.OVL (unpacked with
           re-tools/exeunpack.py); other languages: our own text in the same frame (text-clear
           0, colour 15, the text, wait, text-clear 0)
  blob     "cursor": AdvBIOS's default mouse pointer (01AB:09D8 of the user's NV.OV1: width in
           bytes, height, AND mask, image; advbios.md §6.2)
  meta     "profile": what makes the engine run this game (PROFILES below; engine/game/
           profile.c has the keys), and "langs", the pack writer's list of the languages
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
sys.path.insert(2, os.path.join(HERE, '..', 'lrvne', 'tools'))
import exeunpack  # noqa: E402
import gamedata  # noqa: E402
import gamedir  # noqa: E402
from lrvne import profile, xpak  # noqa: E402

# the engine's entry types (engine/ax.h)
T_GPC, T_USO, T_MES, T_CLM = range(xpak.T_ENGINE, xpak.T_ENGINE + 4)
TYPES = xpak.TypeRegistry({T_GPC: 'gpc', T_USO: 'uso', T_MES: 'mes', T_CLM: 'clm'})

DISKS = 'ABCD'

# The games this tool can build a pack of. `profile` is the pack's profile as the engine reads
# it (engine/game/profile.c): the id names the saves' directory, `start` is the script the
# game's start file (NV.INI) runs, as that file names it, `modules` the plug-ins the game loads.
PROFILES = {
    'nova': {
        'profile': {
            'id': 'nova',
            'title': 'NOVA ～魅入られた肢体～',
            'lang': 'ja',
            'modules': 'CHGFONTH,PALCH,WHITEH,INPUTNAM,ACTE1',
            'start': '\\MES\\RUN.MES',
        },
        # duplicated picture names whose files differ, and the disk whose file is taken
        'picture_choice': {'NV43A': 'B'},
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
    if 'never packed' in row.get('kind'):
        die('%s/%s must never be packed (%s)' % (release, path, row.get('kind')))
    full = os.path.join(original, release, path)
    if not os.path.exists(full):
        die('%s is missing: import the game first (make data SRC=...; docs/game-data.md)' % full)
    data = open(full, 'rb').read()
    if hashlib.md5(data).hexdigest() != row.md5:
        die('%s differs from the inventory (md5)' % full)
    return data


def rows_of(inv, release, kind, prefix=''):
    return sorted(p for (r, p), row in inv.items()
                  if r == release and row.get('kind') == kind and p.startswith(prefix))


def name(path):
    return os.path.basename(path).upper()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--original')
    ap.add_argument('--fonts', required=True,
                    help='directory with k16.xfnt and ank8.xfnt (lrvne xfont --no-bold)')
    ap.add_argument('--game', choices=sorted(PROFILES),
                    default=next(iter(PROFILES)) if len(PROFILES) == 1 else None,
                    required=len(PROFILES) > 1)
    ap.add_argument('-o', '--output', required=True)
    a = ap.parse_args()
    a.original = a.original or gamedir.original()
    prof = PROFILES[a.game]

    inv = {(r.get('release'), r.name): r for r in gamedata.load_inventory()}
    pk = xpak.PackWriter(TYPES, langs=('ja', 'en'))
    counts = collections.Counter()

    # pictures: one per name
    by_name = collections.defaultdict(dict)          # name -> {disk: data}
    for path in rows_of(inv, 'pc98', 'image'):
        if not path.upper().endswith('.GPC'):
            continue
        by_name[name(path)][path[0]] = read_checked(inv, a.original, 'pc98', path)
    for pic in sorted(by_name):
        copies = by_name[pic]
        if len(set(copies.values())) > 1:
            disk = prof['picture_choice'].get(os.path.splitext(pic)[0])
            if disk not in copies:
                die('picture %s differs between disks %s and has no rule'
                    % (pic, ''.join(sorted(copies))))
            data = copies[disk]
        else:
            data = next(iter(copies.values()))
        pk.add(pic, T_GPC, data)
        counts['pictures'] += 1

    for path in rows_of(inv, 'pc98', 'music', 'A/'):
        pk.add(name(path), T_USO, read_checked(inv, a.original, 'pc98', path))
        counts['songs'] += 1
    for path in rows_of(inv, 'pc98', 'map hit table', 'A/'):
        pk.add(name(path), T_CLM, read_checked(inv, a.original, 'pc98', path))
        counts['click maps'] += 1

    # scripts per language
    ja = {name(p): read_checked(inv, a.original, 'pc98', p)
          for p in rows_of(inv, 'pc98', 'script', 'A/MES/')}
    en = {name(p): read_checked(inv, a.original, 'en', p)
          for p in rows_of(inv, 'en', 'script', 'MES/')}
    if not ja:
        die('no Japanese scripts in the inventory')
    for script, data in sorted(ja.items()):
        pk.add(script, T_MES, data, lang='ja')
    counts['ja scripts'] = len(ja)
    if en:
        for script in sorted(set(ja) | set(en)):
            pk.add(script, T_MES, en.get(script, ja.get(script)), lang='en')
        counts['en scripts'] = len(en)
        counts['en from ja'] = len(set(ja) - set(en))
    nvovl = read_checked(inv, a.original, 'pc98', 'A/NV.OVL')
    pk.add('messages', xpak.T_STRINGS, original_messages(nvovl, prof['messages_at']), lang='ja')
    if en:
        pk.add('messages', xpak.T_STRINGS, own_messages(prof['messages_en']), lang='en')
    pk.add('cursor', xpak.T_BLOB,
           default_cursor(read_checked(inv, a.original, 'pc98', 'A/NV.OV1')))

    for entry, fname in (('font16', 'k16.xfnt'), ('font8', 'ank8.xfnt')):
        f = os.path.join(a.fonts, fname)
        if not os.path.exists(f):
            die('%s is missing (make pack makes it)' % f)
        pk.add(entry, xpak.T_FONT, open(f, 'rb').read())
        counts['fonts'] += 1

    pk.add('profile', xpak.T_META, profile.dumps(prof['profile']).encode('utf-8'))

    data = pk.build(dedupe=True)
    os.makedirs(os.path.dirname(os.path.abspath(a.output)), exist_ok=True)
    with open(a.output, 'wb') as fo:
        fo.write(data)
    print('%s: %d entries, %d bytes (%s)' % (a.output, len(pk.names()) + 1, len(data),
                                           ', '.join('%s %d' % kv for kv in counts.items())))


if __name__ == '__main__':
    main()
