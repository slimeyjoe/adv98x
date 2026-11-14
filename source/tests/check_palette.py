#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_palette.py TEST_PALETTE: the engine's INT F3h palette services against AdvBIOS's own
code under unicorn (re-tools/advbios_emu.py; needs unicorn and the unpacked NV.OV1). The
scenario sets palettes, brightness levels 0..15 and single entries (AH=10h, 11h, 13h, 15h);
the colours programmed into the hardware, the brightness and the palette buffer must agree
at every snap. This also checks the brightness table round(v * L / 15) against the table in
the original (0290:049C), entry by entry, through the DAC values it produces.
"""
import os
import random
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 're-tools'))


def scenario():
    rnd = random.Random(98)
    s = ['default', 'snap default_only', 'bright 15', 'snap default15']
    ramp = ['%X%X%X' % (i, i, i) for i in range(16)]
    s += ['setpal %s 255' % ' '.join(ramp), 'snap ramp_kept']
    for level in range(16):
        s += ['bright %d' % level, 'snap ramp%d' % level]
    for k in range(6):
        pal = ['%03X' % rnd.randrange(0x1000) for _ in range(16)]
        s += ['setpal %s %d' % (' '.join(pal), rnd.randrange(16)), 'snap rnd%d' % k]
    s += ['entry 3 F0F 7', 'snap entry_now', 'entry 5 0A5 255', 'snap entry_later',
          'bright 9', 'snap after', 'entry 12 FFF 15', 'snap entry_full']
    return s


def run_emu(lines):
    import advbios_emu
    emu = advbios_emu.AdvBiosEmu()
    snaps = []
    for ln in lines:
        f = ln.split()
        op, a = f[0], f[1:]
        if op == 'default':
            emu.call(0xF3, ax=0x1000)
        elif op == 'bright':
            emu.call(0xF3, ax=0x1100 | int(a[0]))
        elif op == 'setpal':
            words = struct.pack('<16H', *(int(v, 16) for v in a[:16]))
            emu.call(0xF3, ax=0x1300 | int(a[16]), ds_si=words)
        elif op == 'entry':
            emu.call(0xF3, ax=0x1500 | int(a[0]), bx=int(a[1], 16), cx=int(a[2]))
        elif op == 'snap':
            r = emu.call(0xF3, ax=0x1400, es_di=bytes(32))
            buf = struct.unpack('<16H', bytes(emu.uc.mem_read(0x9000 * 16 + 0x4000, 32)))
            dac = [v for rgb in emu.dac for v in rgb]
            snaps.append((a[0], r['ax'] & 0xFFFF, dac, list(buf)))
    return snaps


def run_engine(exe, lines):
    out = subprocess.run([exe], input='\n'.join(lines) + '\n', capture_output=True, text=True,
                         check=True).stdout.splitlines()
    snaps = []
    for i in range(0, len(out), 3):
        _, name, b = out[i].split()
        snaps.append((name, int(b), [int(v) for v in out[i + 1].split()],
                      [int(v, 16) for v in out[i + 2].split()]))
    return snaps


def main():
    try:
        import unicorn  # noqa: F401
    except ImportError:
        print('check_palette: skipped (no unicorn in this Python)')
        return 0
    lines = scenario()
    ref, got = run_emu(lines), run_engine(sys.argv[1], lines)
    bad = 0
    for g, r in zip(got, ref):
        if g[1:] != r[1:]:
            bad += 1
            print('%s: engine brightness %d dac %s pal %s\n%s  AdvBIOS brightness %d dac %s pal %s'
                  % (g[0], g[1], g[2], ['%03X' % v for v in g[3]], ' ' * len(g[0]), r[1], r[2],
                     ['%03X' % v for v in r[3]]))
    if len(got) != len(ref):
        print('snap count: engine %d, AdvBIOS %d' % (len(got), len(ref)))
        bad += 1
    print('check_palette: %d snaps: %s' % (len(ref), 'OK' if not bad else '%d FAILED' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
