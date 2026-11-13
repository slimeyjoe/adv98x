#!/usr/bin/env python3
"""The original game data: import it from your copies of the releases and check it.

The repository carries none of the game (Cat's Pro, 1993). `import` reads the files from the
original media, keeps those whose name and md5 are in resources/inventory.tsv and writes them
to resources/original/<path> (not committed). Everything else is derived from there by tools.

usage:
  gamedata.py import SRC... [--out DIR]
  gamedata.py check [--out DIR]
  gamedata.py scan RELEASE SRC...        # print inventory rows for what SRC holds (maintenance)

SRC: any mix of
  - floppy images (D88, FDI, raw) and hard-disk images (HDI, NHD) with FAT12/16 volumes;
  - the Windows release's EVE.PCK (its members are taken);
  - zip archives of such files; directories (searched recursively; loose game files in them
    are taken as well, e.g. an installed copy or an emulator's host directory).
Releases in the inventory (column 1; destination resources/original/<release>/...):
  pc98      the four 2HD floppies of 1993-05-28, kept per disk (pc98/A/..., pc98/B/GPC/...):
            the same name can hold different data on different disks
  win       members of the Windows 1996 EVE.PCK
  en        the scripts of the English translation by Fuzion (the files that differ)
A file is recognised by name + md5 wherever it is found, so a hard-disk install of the
Japanese release supplies the pc98 rows too.
"""
import argparse
import collections
import hashlib
import os
import struct
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
ORIG = os.path.join(ROOT, 'resources', 'original')
INVENTORY = os.path.join(ROOT, 'resources', 'inventory.tsv')
sys.path.insert(0, HERE)
import diskimg   # noqa: E402

IMAGE_EXT = ('.d88', '.d98', '.88d', '.fdi', '.hdm', '.xdf', '.dup', '.hdi', '.nhd')
Row = collections.namedtuple('Row', 'release path size mtime md5 kind')


def md5(data):
    return hashlib.md5(data).hexdigest()


def load_inventory(path=INVENTORY):
    rows = []
    with open(path, encoding='utf-8') as f:
        head = f.readline().rstrip('\n').split('\t')
        for line in f:
            if line.strip() and not line.startswith('#'):
                r = dict(zip(head, line.rstrip('\n').split('\t')))
                rows.append(Row(r['release'], r['path'], int(r['size']), r['mtime'], r['md5'], r['kind']))
    return rows


def blobs(label, data):
    """(origin, volume label, path, mtime, data) of every file inside one image/archive."""
    low = label.lower()
    if low.endswith('.zip') or data[:4] == b'PK\x03\x04':
        import io
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for n in sorted(z.namelist()):
                if n.endswith('/'):
                    continue
                if n.lower().endswith(IMAGE_EXT + ('.zip', '.pck')):
                    yield from blobs(label + '::' + n, z.read(n))
        return
    if diskimg.is_pck(data):
        for name, d in diskimg.pck_members(data):
            yield label, 'PCK', name, '', d
        return
    try:
        vols = diskimg.volumes(data, label)
    except (ValueError, struct.error) as e:
        print('gamedata: skipped %s: %s' % (label, e))
        return
    for v in vols:
        for path, mtime, d in v.walk():
            yield label, v.volume, path, mtime, d


def sources(spec):
    if os.path.isdir(spec):
        for dp, dirs, files in os.walk(spec):
            dirs.sort()
            for f in sorted(files):
                full = os.path.join(dp, f)
                low = f.lower()
                if low.endswith(IMAGE_EXT + ('.zip', '.pck')):
                    with open(full, 'rb') as fh:
                        yield from blobs(full, fh.read())
                elif os.path.getsize(full) < 4 << 20:
                    with open(full, 'rb') as fh:
                        t = time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(full)))
                        yield spec, '', os.path.relpath(full, spec).replace(os.sep, '/'), t, fh.read()
        return
    with open(spec, 'rb') as fh:
        yield from blobs(spec, fh.read())


def kind_of(path):
    ext = os.path.splitext(path)[1].upper()
    return {'.MES': 'script', '.GPC': 'image', '.USO': 'music', '.TCM': 'plug-in code',
            '.CLM': 'map hit table', '.PI': 'image (Pi)', '.EVE': 'script (EVE)',
            '.WAV': 'sound effect', '.CDF': 'map hit table', '.OVL': 'engine', '.OV1': 'engine',
            '.COM': 'engine loader', '.INI': 'engine start script', '.EXE': 'installer',
            '.SYS': 'boot', '.DEF': 'default name'}.get(ext, 'save' if 'FLAG' in path.upper() else 'other')


def cmd_scan(a):
    seen = set()
    out = []
    for spec in a.src:
        for origin, vol, path, mtime, data in sources(spec):
            dest = path
            if a.release == 'pc98':
                if not vol.startswith('NOVA____98'):
                    continue
                dest = vol[-1] + '/' + path
            key = (dest, md5(data))
            if key in seen:
                continue
            seen.add(key)
            out.append('\t'.join((a.release, dest, str(len(data)), mtime, md5(data), kind_of(path))))
    print('\n'.join(sorted(out)))


def verify(path, r):
    try:
        with open(path, 'rb') as f:
            return md5(f.read()) == r.md5
    except OSError:
        return False


def report(inv, have, where):
    ok = True
    for rel in sorted({r.release for r in inv}):
        rows = [r for r in inv if r.release == rel]
        miss = [r.path for r in rows if r not in have]
        line = '  %-5s %3d/%d' % (rel, len(rows) - len(miss), len(rows))
        if miss:
            line += '  missing: ' + ' '.join(miss[:8]) + (' ...' if len(miss) > 8 else '')
            if rel == 'pc98':
                ok = False
        print(line)
    print('gamedata: %s: %s' % (where, 'the PC-98 release is complete' if ok else
                                'INCOMPLETE: files of the PC-98 release are missing'))
    return ok


def cmd_import(a):
    inv = load_inventory()
    by_key = collections.defaultdict(list)
    for r in inv:
        by_key[(os.path.basename(r.path).upper(), r.md5)].append(r)
    found = {}
    for spec in a.src:
        if not os.path.exists(spec):
            sys.exit('gamedata: %s does not exist' % spec)
        n = 0
        for origin, vol, path, mtime, data in sources(spec):
            for r in by_key.get((os.path.basename(path).upper(), md5(data)), ()):
                if r not in found:
                    found[r] = data
                    n += 1
        print('gamedata: %s: %d files of the game' % (spec, n))
    written = 0
    for r, data in found.items():
        dest = os.path.join(a.out, r.release, r.path)
        if not verify(dest, r):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, 'wb') as f:
                f.write(data)
            written += 1
        if r.mtime:
            t = time.mktime(time.strptime(r.mtime, '%Y-%m-%d %H:%M'))
            os.utime(dest, (t, t))
    print('gamedata: %d files written to %s (%d already there)' % (written, a.out, len(found) - written))
    have = {r for r in inv if r in found or verify(os.path.join(a.out, r.release, r.path), r)}
    return 0 if report(inv, have, a.out) else 1


def cmd_check(a):
    inv = load_inventory()
    have = {r for r in inv if verify(os.path.join(a.out, r.release, r.path), r)}
    return 0 if report(inv, have, a.out) else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('import'); p.add_argument('src', nargs='+'); p.add_argument('--out', default=ORIG)
    p = sub.add_parser('check'); p.add_argument('--out', default=ORIG)
    p = sub.add_parser('scan'); p.add_argument('release'); p.add_argument('src', nargs='+')
    a = ap.parse_args()
    sys.exit({'import': cmd_import, 'check': cmd_check, 'scan': cmd_scan}[a.cmd](a))


if __name__ == '__main__':
    main()
