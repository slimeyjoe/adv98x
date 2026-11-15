#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""compare.py LABEL M68K NATIVE HOST_SNAPS HOST_WAV HOST_STORAGE: the outputs of tests/be68k.sh.

M68K and NATIVE are what be68k printed on the big-endian m68k and natively: they must be the
same, line for line. NATIVE must also be what the headless backend (adv98x) made of the same
input, so that the harness is known to run the engine as a real backend does: its snapshots'
frame hashes (HOST_SNAPS, JSON lines), the sound it recorded (HOST_WAV: the audio hash of each
snapshot over as many samples), the records it wrote (HOST_STORAGE). Stdlib only.
"""
import json
import os
import sys


def fnv(data, h=2166136261):
    for b in data:
        h = ((h ^ b) * 16777619) & 0xFFFFFFFF
    return h


def main():
    label, m68k, native, snaps, wav, storage = sys.argv[1:7]
    a = open(m68k).read().splitlines()
    b = open(native).read().splitlines()
    problems = []
    if a != b:
        diff = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), min(len(a), len(b)))
        problems.append('m68k and native differ from line %d: %r / %r' % (
            diff + 1, a[diff] if diff < len(a) else 'end', b[diff] if diff < len(b) else 'end'))
    host = {}
    for line in open(snaps):
        d = json.loads(line)
        if d.get('ev') == 'snap':
            host[d['name']] = d['hash']
    pcm = open(wav, 'rb').read()[44:]
    got_snaps, got_recs = {}, {}
    for line in b:
        w = line.split()
        if w[0] == 'snap':
            got_snaps[w[1]] = w[2:]
        elif w[0] == 'record':
            got_recs[w[1]] = (int(w[2]), w[3])
    if sorted(got_snaps) != sorted(host):
        problems.append('snapshots %d, the headless backend %d' % (len(got_snaps), len(host)))
    h, done = 2166136261, 0
    for name in sorted(got_snaps, key=lambda n: int(n[1:])):
        fh, frames, ah = got_snaps[name]
        if host.get(name) != fh:
            problems.append('%s: frame %s, the headless backend %s' % (name, fh, host.get(name)))
        h = fnv(pcm[2 * done:2 * int(frames)], h)
        done = int(frames)
        if '%08x' % h != ah:
            problems.append('%s: sound differs from the headless backend\'s within its first '
                            '%s samples' % (name, frames))
    want = {fn: (len(d), '%08x' % fnv(d)) for fn in os.listdir(storage)
            for d in [open(os.path.join(storage, fn), 'rb').read()]}
    if got_recs != want:
        problems.append('records %s, the headless backend %s' % (got_recs, want))
    for p in problems[:10]:
        print('    ' + p)
    print('be68k (%s): %d snapshots, %d samples, records %s: %s' % (
        label, len(got_snaps), done, ' '.join(sorted(got_recs)) or 'none',
        'OK' if not problems and got_snaps else 'FAILED'))
    return 1 if problems or not got_snaps else 0


if __name__ == '__main__':
    sys.exit(main())
