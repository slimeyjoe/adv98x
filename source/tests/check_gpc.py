#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_gpc.py TEST_GPC ORIGINAL: the engine's GPC decoder (engine/gfx/gpc.c) against
source/tools/gpc.py, which is bit-exact with AdvBIOS's decoder under emulation on all 103
distinct GPC files (re-tools/gpc_verify.py).

1. decode: every distinct GPC file of the four PC-98 disks (by md5): size, position,
   interleave, palette and every pixel.
2. draw: INT F3h AH=01h semantics on a background pattern, the expected planes built from
   gpc.py's pixels: the file's position or the caller's (byte column, line), opaque or colour
   0 transparent (per byte: the OR of the four plane bytes is the mask), rows 80 bytes apart
   from y * 80 + x (a row reaching past column 79 continues on the next line), nothing
   written outside the 32000 bytes of a plane.
"""
import glob
import hashlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
import gpc  # noqa: E402

M64 = 0xFFFFFFFFFFFFFFFF


def fnv(chunks):
    h = 1469598103934665603
    for data in chunks:
        for b in data:
            h = ((h ^ b) * 1099511628211) & M64
    return '%016x' % h


def background():
    return [bytearray(((i * 7 + p * 29 + (i // 80) * 3) & 0xFF) for i in range(32000))
            for p in range(4)]


def draw_expected(w, h, x, y, pix, xb, yy, masked):
    planes = background()
    if xb == 65535:
        xb, yy = x >> 3, y
    bw = (w + 7) >> 3
    for r in range(h):
        line = pix[r * w:(r + 1) * w] + bytes(bw * 8 - w)
        for k in range(bw):
            off = (yy + r) * 80 + xb + k
            if not 0 <= off < 32000:
                continue
            px = line[k * 8:k * 8 + 8]
            src = [sum(((c >> p) & 1) << (7 - i) for i, c in enumerate(px)) for p in range(4)]
            m = (src[0] | src[1] | src[2] | src[3]) if masked else 0xFF
            for p in range(4):
                planes[p][off] = (planes[p][off] & ~m & 0xFF) | (src[p] & m)
    return fnv(planes)


def main():
    exe, original = sys.argv[1], sys.argv[2]
    files = {}
    for f in sorted(glob.glob(os.path.join(original, 'pc98', '*', 'GPC', '*.GPC'))):
        files.setdefault(hashlib.md5(open(f, 'rb').read()).hexdigest(), f)
    paths = list(files.values())
    out = subprocess.run([exe, 'decode'] + paths, capture_output=True, text=True,
                         check=True).stdout.splitlines()
    bad = 0
    decoded = {}
    for path, got in zip(paths, out):
        hdr, pal, w, h, x, y, pix = gpc.decode(open(path, 'rb').read())
        decoded[path] = (w, h, x, y, pix)
        p = ','.join('%03X' % v for v in hdr['palette_raw']) if pal else '-'
        want = '%d %d %d %d %d %s %s' % (w, h, x, y, hdr['interleave'], p, fnv([pix]))
        if got != want:
            print('%s: engine "%s", gpc.py "%s"' % (path, got, want))
            bad += 1
    if len(out) != len(paths):
        print('decode: %d results for %d files' % (len(out), len(paths)))
        bad += 1
    # draw semantics on a few representative pictures
    by_name = {os.path.basename(p).upper(): p for p in paths}
    cases = [('NV19.GPC', 65535, 0, 0), ('NV19.GPC', 65535, 0, 1), ('NVWIN.GPC', 65535, 0, 1),
             ('NV28B.GPC', 3, 17, 1), ('NV32A.GPC', 65535, 0, 0), ('NV32A.GPC', 40, 10, 0),
             ('CP.GPC', 65535, 0, 1), ('SAVE.GPC', 70, 390, 0), ('OPPAL.GPC', 65535, 0, 0)]
    for name, xb, yy, masked in cases:
        path = by_name.get(name)
        if not path:
            print('draw: no %s' % name)
            bad += 1
            continue
        got = subprocess.run([exe, 'draw', path, str(xb), str(yy), str(masked)],
                             capture_output=True, text=True, check=True).stdout.strip()
        want = draw_expected(*decoded[path], xb, yy, masked)
        if got != want:
            print('draw %s at %d,%d masked %d: engine %s, expected %s' % (name, xb, yy, masked,
                                                                           got, want))
            bad += 1
    print('check_gpc: %d distinct files decoded, %d draws: %s'
          % (len(paths), len(cases), 'OK' if not bad else '%d FAILED' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
