#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_run.py ADV98X PAK ORIGINAL [--lang ja|en] [--frames N]: play the game headless from
RUN.MES (null backend, control mode), answering every wait for input with Return, and check the
interpreter's control flow against source/tools/mes.py's parse of the scripts:

* every opcode executed in a script (trace "op", script offset = pos - 9000h) starts an opcode
  node of the parse (so execution never leaves the token boundaries the interpreter's own
  scanner agrees with); opcodes run from procedure slots are not script offsets and are counted
  separately;
* every script entered after the first is a mes-jump target of the script before it;
* every picture shown (trace "picture") is named by an image-file of the current script;
* no "error" event, and the run reaches at least the scripts given in EXPECT for the language.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
import mes  # noqa: E402

# RUN -> MODE (title) -> "start from the beginning" -> NVOP (opening) -> its successors
EXPECT = ['RUN', 'MODE', 'NVOP']


def base(name):
    return os.path.splitext(name.replace('\\', '/').split('/')[-1])[0].upper()


class Scripts:
    def __init__(self, original, lang):
        self.dirs = ([os.path.join(original, 'en', 'MES')] if lang == 'en' else []) + \
                    [os.path.join(original, 'pc98', 'A', 'MES')]
        self.cache = {}

    def get(self, name):
        name = base(name)
        if name not in self.cache:
            for d in self.dirs:
                f = os.path.join(d, name + '.MES')
                if os.path.exists(f):
                    break
            sc = mes.Script(open(f, 'rb').read())
            sc.parse()
            ops, jumps, pics = set(), set(), set()
            for seg in sc.segments:
                for n in mes.walk(seg['body']):
                    if n[0] != 'op':
                        continue
                    ops.add(n[1])
                    for a in n[4]:
                        if isinstance(a, tuple) and a[0] == 'str':
                            if n[3] == 0xB1:
                                jumps.add(base(a[1].decode('ascii', 'replace')))
                            elif n[3] == 0xC9:
                                pics.add(a[1].decode('ascii', 'replace').upper())
            self.cache[name] = (ops, jumps, pics)
        return self.cache[name]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('exe')
    ap.add_argument('pak')
    ap.add_argument('original')
    ap.add_argument('--lang', default='ja')
    ap.add_argument('--frames', type=int, default=20000)
    a = ap.parse_args()
    scripts = Scripts(a.original, a.lang)
    storage = tempfile.mkdtemp(prefix='adv98x-run-')
    p = subprocess.Popen([a.exe, '--pak', a.pak, '--lang', a.lang, '--control', '--storage', storage,
                          '--max-ticks', str(a.frames)], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    bad, seen, cur = [], [], None
    n_ops = n_proc = n_pics = 0

    def send(c):
        p.stdin.write(c + '\n')
        p.stdin.flush()

    for line in p.stdout:
        ev = json.loads(line)
        k = ev['ev']
        if k == 'script':
            name = base(ev['name'])
            if cur is not None and name not in scripts.get(cur)[1]:
                bad.append('%s entered from %s, which has no mes-jump to it' % (name, cur))
            cur = name
            seen.append(name)
        elif k == 'op' and cur:
            pos = ev['pos']
            if 0x9000 <= pos < 0xC000:
                n_ops += 1
                if pos - 0x9000 not in scripts.get(cur)[0]:
                    bad.append('%s: opcode %02X executed at %04X, not an opcode of the parse'
                               % (cur, ev['a'][0], pos - 0x9000))
            else:
                n_proc += 1
        elif k == 'picture' and cur:
            n_pics += 1
            if ev['name'].upper() not in scripts.get(cur)[2]:
                bad.append('%s: picture %s is not named by the script' % (cur, ev['name']))
        elif k == 'error':
            bad.append('error event: %s' % line.strip())
        elif k == 'stop':
            if ev['why'] == 'blocked':
                send('press ok')
            send('run')
        elif k == 'exit':
            break
        if len(bad) > 20:
            break
    p.kill()
    for want in EXPECT:
        if want not in seen:
            bad.append('the run did not reach %s' % want)
    for b in bad[:20]:
        print(b)
    print('check_run (%s): %d frames, scripts %s; %d opcodes at script offsets, %d in procedures, '
          '%d pictures: %s' % (a.lang, a.frames, ' '.join(seen), n_ops, n_proc, n_pics,
                               'OK' if not bad else '%d FAILED' % len(bad)))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
