#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_pack.py TEST_PACK PAK: the pack as the engine reads it against the pack tool's reading
(lrvne's xpak.py), and the packed game files against the originals (resources/inventory.tsv
md5s; tools/mkpack.py's rules).

1. test_pack lists the languages and every entry (name, type, lang, size, FNV-1a 64): must
   equal xpak.read_pack().
2. Lookups: a find with a language falls back to the neutral set only (mkpack completes the
   English script set itself), so RUN.MES must be found in ja and en, NV01.GPC everywhere.
3. Every GPC / USO / CLM / MES entry is byte-identical to an original file of that name in the
   inventory (pictures: one of the disks' copies; NV43A: disk B's), and no file the inventory
   marks "never packed" is in the pack.
4. The profile names the game and its start script, and the pack has both languages.
"""
import collections
import hashlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
sys.path.insert(1, os.path.join(HERE, '..', 'lrvne', 'tools'))
import gamedata  # noqa: E402
import mkpack    # noqa: E402
from lrvne import profile, xpak  # noqa: E402


def fnv(data):
    h = 1469598103934665603
    for b in data:
        h = ((h ^ b) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return '%016x' % h


def main():
    exe, pak = sys.argv[1], sys.argv[2]
    pack = xpak.read_pack(open(pak, 'rb').read())
    ents = pack.entries
    names = ['RUN.MES', 'NV01.GPC', 'NOVA.MES', 'profile', 'font16', 'NOSUCH']
    out = subprocess.run([exe, pak] + names, capture_output=True, text=True, check=True).stdout
    lines = out.splitlines()
    want = ['lang\t%d\t%s' % kv for kv in sorted(pack.langs.items())]
    want += ['%s\t%d\t%d\t%d\t%s' % (e.name, e.type, e.lang, e.size, fnv(e.data)) for e in ents]
    bad = 0
    if lines[:len(want)] != want:
        print('languages or entry list differ from xpak.py')
        bad += 1
    got_find = {tuple(l.split('\t')[1:3]): tuple(l.split('\t')[3:]) for l in lines[len(want):]}
    if len(got_find) != len(pack.langs) * len(names):
        print('%d lookups answered, expected %d' % (len(got_find), len(pack.langs) * len(names)))
        bad += 1
    for (l, name), res in sorted(got_find.items()):
        hit = pack.find(name, lang=int(l))
        exp = ('%d' % hit.type, '%d' % hit.lang) if hit else ('-', '-')
        if res != exp:
            print('find %s in lang %s: engine %s, expected %s' % (name, l, res, exp))
            bad += 1

    inv = gamedata.load_inventory()
    by_md5 = collections.defaultdict(list)
    for r in inv:
        by_md5[r.md5].append(r)
    kinds = {mkpack.T_GPC: 'image', mkpack.T_USO: 'music', mkpack.T_CLM: 'map hit table',
             mkpack.T_MES: 'script'}
    checked = 0
    for e in ents:
        if e.type not in kinds:
            continue
        rows = [r for r in by_md5.get(hashlib.md5(e.data).hexdigest(), [])
                if r.basename.upper() == e.name and r.get('kind') == kinds[e.type]
                and r.get('release') in ('pc98', 'en')]
        if not rows:
            print('%s (type %d, lang %d) is not an original file of that name'
                  % (e.name, e.type, e.lang))
            bad += 1
        if e.name == 'NV43A.GPC' and not any(r.name.startswith('B/') for r in rows):
            print('NV43A.GPC is not disk B\'s file')
            bad += 1
        checked += 1
    never = {r.md5 for r in inv if 'never packed' in r.get('kind')}
    for e in ents:
        if hashlib.md5(e.data).hexdigest() in never:
            print('%s holds a file that must never be packed' % e.name)
            bad += 1

    prof = profile.loads(pack.find('profile', xpak.T_META).data)
    if prof != {k: str(v) for k, v in mkpack.PROFILES[prof.get('id')]['profile'].items()}:
        print('the profile is not the one mkpack.py describes: %r' % prof)
        bad += 1
    if not pack.find(prof['start'].split('\\')[-1], mkpack.T_MES, lang=prof['lang']):
        print('the start script %s is not in the pack' % prof['start'])
        bad += 1
    if sorted(pack.langs.values()) != ['en', 'ja']:
        print('languages %r, expected ja and en' % pack.langs)
        bad += 1
    print('check_pack: %d entries, %d game files checked, %d lookups: %s'
          % (len(ents), checked, len(got_find), 'OK' if not bad else '%d FAILED' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
