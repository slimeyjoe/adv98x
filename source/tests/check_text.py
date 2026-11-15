#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_text.py TEST_TEXT PAK FONTDIR: the engine's INT F6h text services against AdvBIOS's own
code. The same scenario runs through test_text (engine/bios/bios_text.c) and through NV.OV1's
handlers under unicorn (re-tools/advbios_emu.py); the screen (all four planes) and the text
cursor must be identical at every snap.

Needs a Python with unicorn (EMU_PYTHON, docs/re/README.md "Tools") and the unpacked NV.OV1
(resources/derived/exe/, gamedata.py derive). FONTDIR holds the pack's k16.xfnt and ank8.xfnt:
both sides draw from the same glyph tables through the same kanji-ROM model, so what is
compared is AdvBIOS's logic: the GRCG writes, line pitch and wrapping, the bold quirk, the
half-width paths (1-byte codes and the two-byte codes of JIS rows 29h-2Bh), the Shift-JIS
conversion, control codes, fills, inversion, the window clamping and scrolling.
"""
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 're-tools'))


def sj(text):
    return text.encode('cp932')


def scenario():
    s = []
    # 1. full-width characters over a background: RMW keeps the clear pixels
    s += ['pattern', 'colour 4', 'cursor 0 0']
    s += ['char %04X' % int.from_bytes(sj(c), 'big') for c in 'あいう漢字、。！']
    s += ['colour 13', 'cursor 40 3', 'string ' + sj('カタカナと、ABC xyz').hex(), 'snap rmw']
    # 2. a narrow window: wrapping, line pitch 20, back to the top
    s += ['fillpage 0', 'window 10 100 30 160', 'fillwin 1', 'colour 15',
          'string ' + sj('吾輩は猫である。名前はまだ無い。どこで生れたかとんと見当がつかぬ。'
                         'Some English text, too: the quick brown fox.').hex(),
          'snap wrap']
    # 3. the edges: full-width at x = x1 wraps first, half-width at x1 wraps after
    s += ['fillwin 2', 'cursor 30 100', 'char 82A0', 'snap fw_at_x1',
          'cursor 30 120', 'char 0041', 'snap hw_at_x1',
          'cursor 29 140', 'char 82A0', 'char 82A2', 'snap fw_x1_minus_1']
    # 4. bold: every half-width glyph, the katakana, and full-width rows 21h and 28h
    s += ['fillpage 0', 'window 0 0 79 399', 'cursor 0 0', 'colour 15', 'bold 1',
          'string ' + bytes(range(0x20, 0x7F)).hex(),
          'string ' + bytes(range(0xA1, 0xE0)).hex()]
    for row in (0x21, 0x28):
        for cell in range(0x21, 0x7F):
            jis = (row << 8) | cell
            s.append('char %04X' % jis_to_sjis(jis))
    s += ['bold 0', 'colour 6', 'string ' + bytes(range(0x21, 0x7F)).hex(), 'snap bold']
    s += ['bold 2', 'snap bold_get']
    # 5. two-byte half-width codes (Shift-JIS 85xx = JIS rows 29h/2Ah, 86xx = 2Bh/2Ch),
    #    control codes, single bytes that draw nothing, CR, string terminators
    s += ['fillpage 0', 'cursor 0 0', 'colour 14']
    s += ['char %04X' % c for c in list(range(0x8540, 0x857F)) + list(range(0x8580, 0x85FD))]
    s += ['char %04X' % c for c in range(0x8640, 0x8660)]
    s += ['char 000D', 'char 0001', 'char 0080', 'char 009F', 'char 00E0', 'char 00FF',
          'char 0041', 'char 000D', 'char 0042']
    s += ['string ' + (b'AB' + b'\xff' + b'CD').hex(), 'string ' + b'\x82'.hex() + '00',
          'snap halfwidth']
    # 6. fills and inversion, the window clamped and sorted
    s += ['pattern', 'fillrect 3 10 20 50 5', 'invert 10 30 40 80', 'invert 0 0 79 0',
          'fillrect 79 399 79 399 9', 'snap fills',
          'window 90 500 5 20', 'fillwin 3', 'colour 0', 'string ' + sj('窓の中').hex(),
          'snap clamp']
    # 7. scrolling: the window and a rectangle, all four directions
    s += ['pattern', 'window 10 50 40 200', 'scroll 0 7', 'scroll 1 3', 'scroll 2 2',
          'scroll 3 5', 'snap scroll_window', 'pattern', 'scrollrect 0 0 79 399 0 2',
          'scrollrect 70 300 79 399 2 4', 'scrollrect 5 5 6 6 3 1', 'snap scroll_rect']
    return s


def jis_to_sjis(jis):
    hi, lo = jis >> 8, jis & 0xFF
    lo += 0x1F if hi & 1 else 0x7D
    if hi & 1 and lo >= 0x7F:
        lo += 1
    hi = (hi - 0x21) // 2 + 0x81
    if hi > 0x9F:
        hi += 0x40
    return (hi << 8) | lo


def run_emu(lines, fontdir):
    import advbios_emu
    emu = advbios_emu.AdvBiosEmu(fonts=fontdir)
    snaps = []
    for ln in lines:
        f = ln.split()
        op, a = f[0], f[1:]
        if op in ('window', 'fillrect', 'invert'):
            rect = struct.pack('<4H', *(int(v) & 0xFFFF for v in a[:4]))
            ah = {'window': 0x01, 'fillrect': 0x0D, 'invert': 0x0E}[op]
            al = int(a[4]) if op == 'fillrect' else 0
            emu.call(0xF6, ax=(ah << 8) | al, ds_si=rect)
        elif op == 'colour':
            emu.call(0xF6, ax=0x0300 | int(a[0]))
        elif op == 'cursor':
            emu.call(0xF6, ax=0x0500, cx=int(a[0]), dx=int(a[1]))
        elif op == 'bold':
            emu.call(0xF6, ax=0x1300 | int(a[0]))
        elif op == 'char':
            emu.call(0xF6, ax=0x0900, dx=int(a[0], 16))
        elif op == 'string':
            emu.call(0xF6, ax=0x0A00, ds_si=bytes.fromhex(a[0]) + b'\0\0')
        elif op == 'fillwin':
            emu.call(0xF6, ax=0x0B00 | int(a[0]))
        elif op == 'fillpage':
            emu.call(0xF6, ax=0x0C00 | int(a[0]))
        elif op == 'scroll':
            emu.call(0xF6, ax=0x1000 | int(a[0]), cx=int(a[1]))
        elif op == 'scrollrect':
            rect = struct.pack('<4H', *(int(v) for v in a[:4]))
            emu.call(0xF6, ax=0x1100 | int(a[4]), cx=int(a[5]), ds_si=rect)
        elif op == 'pattern':
            emu.set_planes([bytes(((i * 7 + p * 29 + (i // 80) * 3) & 0xFF) for i in range(32000))
                            for p in range(4)])
        elif op == 'snap':
            snaps.append((a[0], emu.ds_word(0x1A0), emu.ds_word(0x1A2), emu.planes()))
        else:
            raise ValueError(op)
    return snaps


def run_engine(exe, pak, lines):
    out = subprocess.run([exe, pak], input='\n'.join(lines) + '\n', capture_output=True,
                         text=True, check=True).stdout.splitlines()
    snaps = []
    i = 0
    while i < len(out):
        _, name, x, y = out[i].split()
        planes = [bytes.fromhex(out[i + 1 + p]) for p in range(4)]
        snaps.append((name, int(x), int(y), planes))
        i += 5
    return snaps


def first_diff(a, b):
    for p in range(4):
        for i in range(32000):
            if a[p][i] != b[p][i]:
                return 'plane %d byte %d (x %d..%d, y %d): engine %02x, AdvBIOS %02x' % (
                    p, i, (i % 80) * 8, (i % 80) * 8 + 7, i // 80, a[p][i], b[p][i])
    return None


def main():
    exe, pak, fontdir = sys.argv[1:4]
    try:
        import unicorn  # noqa: F401
    except ImportError:
        print('check_text: skipped (no unicorn in this Python)')
        return 0
    lines = scenario()
    ref = run_emu(lines, fontdir)
    got = run_engine(exe, pak, lines)
    bad = 0
    for (n1, x1, y1, p1), (n2, x2, y2, p2) in zip(got, ref):
        msgs = []
        if (x1, y1) != (x2, y2):
            msgs.append('cursor engine (%d, %d), AdvBIOS (%d, %d)' % (x1, y1, x2, y2))
        d = first_diff(p1, p2)
        if d:
            npx = sum(bin(p1[p][i] ^ p2[p][i]).count('1') for p in range(4) for i in range(32000))
            msgs.append('%s; %d plane bits differ' % (d, npx))
        if msgs:
            bad += 1
            print('%s: %s' % (n1, '; '.join(msgs)))
    if len(got) != len(ref):
        print('snap count: engine %d, AdvBIOS %d' % (len(got), len(ref)))
        bad += 1
    print('check_text: %d snaps, %d scenario lines: %s' % (len(ref), len(lines),
                                                          'OK' if not bad else '%d FAILED' % bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
