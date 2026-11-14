#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_pack.py TEST_PACK PAK: the engine's pack reader against tools/xpak.py, and the packed
game files against the originals (resources/inventory.tsv md5s; tools/mkpack.py's rules).

1. test_pack lists every entry (name, type, lang, size, FNV-1a 64): must equal xpak.read().
2. Lookups: xpak_find with a language falls back to the neutral set only (mkpack completes the
   English script set itself), so RUN must be found in ja and en, NV01 everywhere.
3. Every GPC / USO / CLM / MES entry is byte-identical to an original file of that name in the
   inventory (pictures: one of the disks' copies; NV43A: disk B's), and no file the inventory
   marks "never packed" is in the pack.
"""
import collections
import hashlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
import gamedata  # noqa: E402
import xpak      # noqa: E402


def fnv(data):
    h = 1469598103934665603
    for b in data:
        h = ((h ^ b) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return '%016x' % h


def main():
    exe, pak = sys.argv[1], sys.argv[2]
    data = open(pak, 'rb').read()
    ents = xpak.read(data)
    names = ['RUN', 'NV01', 'NOVA', 'profile', 'font16', 'NOSUCH']
    out = subprocess.run([exe, pak] + names, capture_output=True, text=True, check=True).stdout
    lines = out.splitlines()
    want = ['%s\t%d\t%d\t%d\t%s' % (e['name'], e['type'], e['lang'], e['size'], fnv(e['data']))
            for e in ents]
    bad = 0
    if lines[:len(want)] != want:
        print('entry list differs from xpak.py')
        bad += 1
    got_find = {tuple(l.split('\t')[1:3]): tuple(l.split('\t')[3:]) for l in lines[len(want):]}
    for (l, name), res in sorted(got_find.items()):
        cands = [e for e in ents if e['name'].upper() == name.upper()]
        hit = [e for e in cands if e['lang'] == int(l)] or [e for e in cands if e['lang'] == 0]
        exp = ('%d' % hit[0]['type'], '%d' % hit[0]['lang']) if hit else ('-', '-')
        if res != exp:
            print('find %s in lang %s: engine %s, expected %s' % (name, l, res, exp))
            bad += 1

    inv = gamedata.load_inventory()
    by_md5 = collections.defaultdict(list)
    for r in inv:
        by_md5[r.md5].append(r)
    kinds = {xpak.T_GPC: 'image', xpak.T_USO: 'music', xpak.T_CLM: 'map hit table',
             xpak.T_MES: 'script'}
    checked = 0
    for e in ents:
        if e['type'] not in kinds:
            continue
        rows = [r for r in by_md5.get(hashlib.md5(e['data']).hexdigest(), [])
                if os.path.splitext(os.path.basename(r.path))[0].upper() == e['name']
                and r.kind == kinds[e['type']] and r.release in ('pc98', 'en')]
        if not rows:
            print('%s (type %d, lang %d) is not an original file of that name'
                  % (e['name'], e['type'], e['lang']))
            bad += 1
        if e['name'] == 'NV43A' and not any(r.path.startswith('B/') for r in rows):
            print('NV43A is not disk B\'s file')
            bad += 1
        checked += 1
    never = {r.md5 for r in inv if 'never packed' in r.kind}
    for e in ents:
        if hashlib.md5(e['data']).hexdigest() in never:
            print('%s holds a file that must never be packed' % e['name'])
            bad += 1
    print('check_pack: %d entries, %d game files checked, %d lookups: %s'
          % (len(ents), checked, len(got_find), 'OK' if not bad else '%d FAILED' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
