#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""present.py ADV98X_SDL3 PAK [--lang ja|en]: the SDL3 backend's presentation, offscreen.

The game is played from RUN.MES in control mode (Return at every wait, the title's first item)
with the window at a size and scale mode per run; at fixed stops the engine's frame (`snap`:
the planes, palette and graphics-on flag handed to the backend) and what the renderer drew
(`readback`, backends/control/control.c) are compared:

  * the destination rectangle is the one the scale mode prescribes for the drawable, centred
    (integer: the largest whole factor; aspect: whole factors with height = 1.2 x width; fit:
    640x480 scaled into the window; stretch: the whole window);
  * nothing outside it is lit;
  * integer and aspect (nearest filtering): every source pixel is its palette colour, 4-bit
    DAC values times 17 (black with graphics off), and every destination pixel of its block
    equals it;
  * fit and stretch (linear filtering): pixels whose eight neighbours have the same index are
    checked (interpolating equal colours gives that colour); edges are left alone.

The frame itself is the engine's (checked against the original interpreter by check_vm.py);
this checks the path from the planes to the window. Stdlib only.
"""
import argparse
import base64
import json
import math
import subprocess
import sys
import tempfile

INTEGER, ASPECT, FIT, STRETCH = 0, 1, 2, 3
# (scale option, mode, window size)
RUNS = [('integer', INTEGER, (1280, 800)), ('integer', INTEGER, (1000, 700)),
        ('aspect', ASPECT, (1400, 1000)), ('fit', FIT, (1000, 700)),
        ('stretch', STRETCH, (900, 500))]
STOPS = (2, 6, 15, 30)          # the input waits at which the frame is checked


def expected_dest(W, H, mode):
    if mode == INTEGER:
        f = max(1, min(W // 640, H // 400))
        w, h = 640 * f, 400 * f
    elif mode == ASPECT:
        bx = by = 1
        for fx in range(1, W // 640 + 1):
            fy = int(fx * 1.2 + 0.5)
            if 1 <= fy <= H // 400:
                bx, by = fx, fy
        w, h = 640 * bx, 400 * by
    elif mode == FIT:
        s = min(W / 640.0, H / 480.0)
        w, h = 640.0 * s, 480.0 * s
    else:
        w, h = W, H
    x, y = (W - w) / 2.0, (H - h) / 2.0
    r = lambda v: int(math.floor(v + 0.5))
    return r(x), r(y), r(w), r(h)


def indices(snap):
    packed = base64.b64decode(snap['data'])
    idx = bytearray(640 * 400)
    for i, b in enumerate(packed):
        idx[2 * i] = b >> 4
        idx[2 * i + 1] = b & 15
    return idx


def check(snap, rb, where):
    bad = []
    W, H = rb['win']
    exp = expected_dest(W, H, rb['mode'])
    if tuple(rb['dest']) != exp:
        bad.append('dest %s, expected %s for %dx%d' % (tuple(rb['dest']), exp, W, H))
    if rb['border_lit']:
        bad.append('%d lit pixels outside the picture' % rb['border_lit'])
    if not rb['linear'] and rb['nonuniform']:
        bad.append('%d destination pixels differ from their source pixel' % rb['nonuniform'])
    idx = indices(snap)
    pal4 = bytes.fromhex(snap['pal'])
    pal = [bytes(v * 17 for v in pal4[i * 3:i * 3 + 3]) if snap['gon'] else b'\0\0\0'
           for i in range(16)]
    rgb = base64.b64decode(rb['data'])
    n = 0
    first = None
    for y in range(400):
        for x in range(640):
            i = y * 640 + x
            if rb['linear'] and not flat(idx, x, y):
                continue
            if rgb[i * 3:i * 3 + 3] != pal[idx[i]]:
                n += 1
                first = first or (x, y, rgb[i * 3:i * 3 + 3].hex(), pal[idx[i]].hex())
    if n:
        bad.append('%d pixels differ from the frame, first at x %d y %d: drawn %s, frame %s'
                   % ((n,) + first))
    return ['%s: %s' % (where, b) for b in bad]


def flat(idx, x, y):
    c = idx[y * 640 + x]
    for dy in (-1, 0, 1):
        yy = y + dy
        if not 0 <= yy < 400:
            continue
        for dx in (-1, 0, 1):
            xx = x + dx
            if 0 <= xx < 640 and idx[yy * 640 + xx] != c:
                return False
    return True


def run(exe, pak, lang, opt, mode, size):
    storage = tempfile.mkdtemp(prefix='adv98x-present-')
    p = subprocess.Popen([exe, '--pak', pak, '--lang', lang, '--control', '--storage', storage,
                          '--scale', opt, '--window', '%dx%d' % size, '--max-ticks', '100000'],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True)
    send = lambda c: (p.stdin.write(c + '\n'), p.stdin.flush())
    where = '%s %dx%d' % (opt, size[0], size[1])
    problems, checked, stops, snap = [], 0, 0, None
    for line in p.stdout:
        ev = json.loads(line)
        k = ev['ev']
        if k == 'stop':
            if ev['why'] != 'blocked':
                send('run')
                continue
            stops += 1
            if stops in STOPS:
                send('snap s%d' % stops)
                send('readback s%d' % stops)
                continue
            send('press ok')
            send('run')
        elif k == 'snap':
            snap = ev
        elif k == 'present':
            if ev['mode'] != mode:
                problems.append('%s: the backend reports scale mode %d' % (where, ev['mode']))
            problems += check(snap, ev, '%s, stop %d' % (where, stops))
            checked += 1
            if stops == STOPS[-1]:
                break
            send('press ok')
            send('run')
        elif k in ('exit', 'error'):
            problems.append('%s: %s' % (where, ev))
            break
    p.kill()
    if checked < len(STOPS):
        problems.append('%s: %d of %d frames checked' % (where, checked, len(STOPS)))
    return checked, problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('exe')
    ap.add_argument('pak')
    ap.add_argument('--lang', default='ja')
    a = ap.parse_args()
    total, problems = 0, []
    for opt, mode, size in RUNS:
        n, pr = run(a.exe, a.pak, a.lang, opt, mode, size)
        total += n
        problems += pr
    for pr in problems:
        print('    ' + pr)
    print('present (%s): %d frames in %d window/scale runs: %s' % (
        a.lang, total, len(RUNS), 'OK' if not problems else 'FAILED'))
    return 0 if not problems else 1


if __name__ == '__main__':
    sys.exit(main())
