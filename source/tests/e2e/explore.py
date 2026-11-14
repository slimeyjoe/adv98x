#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""explore.py ADV98X PAK ORIGINAL [--lang ja|en] [--until SCRIPT] [--frames N] [-v]: play the
game headless (control mode) with an exploring player and report the scripts it went through.

The player answers every wait as a person might who tries everything in turn:
  * a key wait: Return;
  * a menu: the item after the one taken the last time this menu was met (counted per script,
    menu position and item count), reached with → presses (→ steps by the menu's column step and
    wraps, interpreter.md §4), then Return; one key per stop, as menus flush type-ahead;
  * a click map: the next region of the map last loaded (its centre), clicked;
  * name entry: Return (the default name).
Rotating the choices makes the flag-gated hubs open up (rooms visited once, menu items that
disappear), so the routes of the game are walked without a hand-written route.
"""
import argparse
import collections
import json
import os
import subprocess
import sys
import tempfile


def base(name):
    return os.path.splitext(name.replace('\\', '/').split('/')[-1])[0].upper()


def regions(original, name):
    path = os.path.join(original, 'pc98', 'A', 'CLM', base(name) + '.CLM')
    d = open(path, 'rb').read()
    x0, y0, w, h = d[1:5]
    cells = collections.defaultdict(list)
    for i in range(w * h):
        b = d[5 + i // 2]
        v = (b >> 4) if i % 2 == 0 else b & 15
        if v:
            cells[v].append((x0 + i % w, y0 + i // w))
    out = []
    for v in sorted(cells):
        cx = sum(c[0] for c in cells[v]) / len(cells[v])
        cy = sum(c[1] for c in cells[v]) / len(cells[v])
        best = min(cells[v], key=lambda c: (c[0] - cx) ** 2 + (c[1] - cy) ** 2)  # inside it
        out.append((v, best[0] * 8 + 4, best[1] * 8 + 4))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('exe')
    ap.add_argument('pak')
    ap.add_argument('original')
    ap.add_argument('--lang', default='ja')
    ap.add_argument('--until', default='END')
    ap.add_argument('--frames', type=int, default=3000000)
    ap.add_argument('--storage')
    ap.add_argument('--until-save', help='stop when the game writes this record (e.g. FLAG3)')
    ap.add_argument('--title-pick', type=int, default=0,
                    help='the item to take in the first menu (the title): 1 = 2nd story, ...')
    ap.add_argument('-v', action='store_true')
    a = ap.parse_args()
    storage = a.storage or tempfile.mkdtemp(prefix='adv98x-explore-')
    p = subprocess.Popen([a.exe, '--pak', a.pak, '--lang', a.lang, '--control', '--storage',
                          storage, '--max-ticks', str(a.frames)],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True)
    send = lambda c: (p.stdin.write(c + '\n'), p.stdin.flush())
    visits = collections.Counter()
    seen, script, clickmap = [], None, []
    plan = []                                   # keys still to press for the current choice
    menu = None                                 # (script, pos, count) of the menu waited in
    reached = False
    t = 0
    for line in p.stdout:
        ev = json.loads(line)
        k = ev['ev']
        t = ev.get('t', t)
        if k == 'script':
            script = base(ev['name'])
            seen.append(script)
            if a.v:
                print('%8d %s' % (t, script))
            if not a.until_save and script == base(a.until):
                reached = True
                break
        elif k == 'save' and a.until_save and ev.get('name') == a.until_save:
            reached = True
            break
        elif k == 'load' and ev['a'][0] == -1:
            clickmap = regions(a.original, ev['name'])
        elif k == 'wait' and ev['a'][1] == 0 and ev['a'][0] == 2:        # a menu starts
            menu = (script, ev['pos'], ev['a'][2])
            n = visits[menu] % max(ev['a'][2], 1)
            if not any(visits.values()):
                n = a.title_pick
            visits[menu] += 1
            plan = ['right'] * n + ['ok']
        elif k == 'stop':
            if ev['why'] == 'blocked':
                w = ev['wait']
                if w == 2 and plan:
                    send('press ' + plan.pop(0))
                elif w == 3 and clickmap:
                    key = (script, 'map', len(clickmap))
                    v, x, y = clickmap[visits[key] % len(clickmap)]
                    visits[key] += 1
                    send('mouse %d %d' % (x, y))
                    send('press mouse_l')
                else:
                    send('press ok')
            send('run')
        elif k == 'exit':
            break
    p.kill()
    route = [s for i, s in enumerate(seen) if i == 0 or s != seen[i - 1]]
    print('explore (%s): %s %s after %d frames; %d scripts entered, %d distinct' % (
        a.lang, 'reached' if reached else 'did not reach', a.until_save or base(a.until), t, len(seen),
        len(set(seen))))
    if not a.v:
        print('  ' + ' '.join(route[:60]) + (' ...' if len(route) > 60 else ''))
    return 0 if reached else 1


if __name__ == '__main__':
    sys.exit(main())
