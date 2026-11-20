#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_mes.py TEST_MES ORIGINAL: the interpreter's token stepper (skip_token 0xED3B), operand
reader (get_number 0xEC54) and block scanner (skip_block 0xEC22) against source/tools/mes.py,
whose scanner agrees with the interpreter's on every block of every script
(re-tools/mesdis.py check), on every byte offset of every script of every language and of the
start file. Offsets where mes.py's scan runs off the end of the file are left out (the engine
reads on into the memory after the script there, as the interpreter would). Numbers compare
modulo 2^16: the interpreter computes them in AX, mes.py does not wrap (only bytes that are
not real operands, e.g. inside strings, reach above 65535).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
import gamedata  # noqa: E402
import gamedir  # noqa: E402
import mes  # noqa: E402


def expected(d):
    out = []
    s = mes.Script(d)
    for p in range(len(d)):
        try:
            out.append('t %d %d' % (p, mes.token_len(d, p)))
        except IndexError:
            out.append(None)
        b = d[p]
        if 0x23 <= b <= 0x2C:
            if p + 3 <= len(d) or b < 0x28 or (b == 0x28 and p + 2 <= len(d)):
                v, q = s._num(p)
                s.covered = bytearray(len(d))
                out.append('n %d %d %d' % (p, v & 0xFFFF, q))     # AX is 16 bits
            else:
                out.append(None)
        if b in (0xA2, 0xA0):
            try:
                e = mes.skip_block(d, p + 1, b, b + 1)
                out.append('b %d %d %d' % (p, b, e))
            except IndexError:
                out.append(None)
    return out


def main():
    exe, original = sys.argv[1], sys.argv[2]
    desc = gamedir.load()
    files = [f for lang in desc.PACK['languages']
             for f in gamedata.part_files(original, desc.PACK['scripts'][lang])]
    start = desc.ORIGINAL['start']['path']
    files += [os.path.join(original, desc.ORIGINAL['release'], start)]
    bad = checked = 0
    for f in files:
        d = open(f, 'rb').read()
        got = subprocess.run([exe, f], capture_output=True, text=True, check=True).stdout.splitlines()
        want = expected(d)
        if len(got) != len(want):
            print('%s: %d results, expected %d' % (f, len(got), len(want)))
            bad += 1
            continue
        for g, w in zip(got, want):
            if w is None:
                continue
            checked += 1
            if g != w:
                if bad < 20:
                    print('%s: engine "%s", mes.py "%s"' % (os.path.basename(f), g, w))
                bad += 1
    print('check_mes: %d scripts, %d results compared: %s'
          % (len(files), checked, 'OK' if not bad else '%d FAILED' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
