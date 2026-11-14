#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_vm.py TEST_VM PAK ORIGINAL FONTS [SCENARIO...]: the engine against the original
interpreter. Each scenario starts the game at RUN.MES with given save files and key presses and
runs it twice: through the engine (test_vm) and through NV.OVL on AdvBIOS under emulation
(re-tools/nvovl_emu.py). Both stop when the game waits for input and no key is left (or ends);
then these must be identical:

  * the interpreter's state: 0000-00FFh (flags, variables, script name, drives), the script
    and sub-script buffers 9000-BFFFh and C006-D005h, the interpreter's variables D006-D8BFh (text state, menu
    tables, menu2 buffer, procedure slots), the player's name D937-D958h, the parameter and
    file-name buffers D9E3-DAFFh and the save buffer DB20-DC1Fh. (0100-8FFFh holds the
    plug-ins' code in the original and is not compared; the engine replaces them.)
  * the screen: all four planes of the page, and, where the pointer is shown, the frame with
    the pointer (drawn into VRAM by AdvBIOS's driver, into the presented frame by the engine);
  * the DAC (palette at the current brightness);
  * the save files written;
  * the sound calls (INT F4h function and argument), in order.

CHECK_VM_OUT=DIR writes both screens of a failing scenario there as PNG.

Input is the PC-98 keyboard: a key is accepted only while the game waits for one. The dumped
copy's own saves (resources/original/pc98/A/FLAG0..5, NAME.DEF) are the test inputs of the
scenarios that need saves; they are never packed.
"""
import glob
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 're-tools'))

RET, DOWN = (0x1C, 0x0D), (0x3D, 0x00)
RET_TO_CLICK = ('ret*',)          # Return at every key wait up to the next click-map wait
DUMP_SAVES = ['FLAG0', 'FLAG1', 'FLAG2', 'FLAG3', 'FLAG4', 'FLAG5', 'NAME.DEF']

# name: (language, save files from the dump, keys)
SCENARIOS = {
    # title menu (menu2): 3 x down to "continue", Return, file No1 -> flag-load 0
    'continue': ('ja', DUMP_SAVES, [DOWN] * 3 + [RET, RET] + [RET] * 40),
    # "2nd story": an empty noun list selects at once
    # the 2nd / 3rd story start with name entry: Return alone takes the default name
    'story2': ('ja', DUMP_SAVES, [DOWN, RET] + [RET] * 40),
    'story3': ('ja', DUMP_SAVES, [DOWN, DOWN, RET] + [RET] * 40),
    # a new game on a fresh install; the name typed: a, ｶ, ﾞ, ﾊ, ﾟ, BS, ﾎ, ﾟ, Z, Return
    'newgame': ('ja', [], [RET, (0x1D, 0x61), (0x24, 0xB6), (0x1A, 0xDE), (0x17, 0xCA),
                           (0x1B, 0xDF), (0x0E, 0x08), (0x2D, 0xCE), (0x1B, 0xDF),
                           (0x29, 0x5A), RET] + [RET] * 30),
    # continue, click SAVE on the 2nd-deck map (region 14), file No2 -> flag-save 1
    'save': ('ja', DUMP_SAVES, [DOWN] * 3 + [RET, RET, RET_TO_CLICK, ('click', 550, 243), DOWN, DOWN, RET]
             + [RET] * 10),
    # continue, click a room of the map
    'map_click': ('ja', DUMP_SAVES, [DOWN] * 3 + [RET, RET, RET_TO_CLICK, ('click', 120, 330)]
                  + [RET] * 30),
    'sound': ('ja', DUMP_SAVES, [DOWN] * 4 + [RET] + [DOWN, RET, DOWN, DOWN, RET]),
    'graphic': ('ja', DUMP_SAVES, [DOWN] * 5 + [RET] + [RET] * 12),
    'continue_en': ('en', DUMP_SAVES, [DOWN] * 3 + [RET, RET] + [RET] * 40),
}

AFTER_M5 = {}

RANGES = [(0x0000, 0x0100), (0x9000, 0xC000), (0xC006, 0xD006), (0xD006, 0xD8C0), (0xD937, 0xD959),
          (0xD9E3, 0xDB00), (0xDB20, 0xDC20)]


def original_files(original, lang):
    files = {}
    for d in 'DCBA':                            # disk A's copy of a name wins
        for f in glob.glob(os.path.join(original, 'pc98', d, '*', '*')):
            files[os.path.basename(f).upper()] = open(f, 'rb').read()
    for f in glob.glob(os.path.join(original, 'pc98', 'A', '*.TCM')):
        files[os.path.basename(f).upper()] = open(f, 'rb').read()
    if lang == 'en':
        for f in glob.glob(os.path.join(original, 'en', 'MES', '*.MES')):
            files[os.path.basename(f).upper()] = open(f, 'rb').read()
    # NV43A: the disk B file, as the pack (docs/re/disks.md §4)
    files['NV43A.GPC'] = open(os.path.join(original, 'pc98', 'B', 'GPC', 'NV43A.GPC'), 'rb').read()
    return files


def run_reference(original, fonts, lang, saves, keys):
    import nvovl_emu
    storage = {s: open(os.path.join(original, 'pc98', 'A', s), 'rb').read() for s in saves}
    emu = nvovl_emu.NvOvlEmu(original_files(original, lang), fonts=fonts, keys=list(keys),
                             storage=storage)
    r = emu.run('\\MES\\RUN.MES')
    written = {k: v for k, v in r['storage'].items() if storage.get(k) != v}
    return dict(end=r['end'], mem=r['mem'], planes=r['planes'], pointer=r['pointer_planes'],
                dac=[v for rgb in emu.dac for v in rgb], storage=written,
                sound=['%d %s' % (ah, '-' if a is None else a) for ah, a in r['sound']])


def run_engine(exe, pak, original, lang, saves, keys):
    d = tempfile.mkdtemp(prefix='adv98x-vm-')
    before = {}
    for s in saves:
        data = open(os.path.join(original, 'pc98', 'A', s), 'rb').read()
        open(os.path.join(d, s), 'wb').write(data)
        before[s] = data
    keystr = ','.join('C:%d:%d' % k[1:] if k[0] == 'click' else 'R*' if k[0] == 'ret*' else
                      '%02X%02X' % k for k in keys) or '-'
    out = subprocess.run([exe, pak, d, lang, keystr], capture_output=True, text=True).stdout
    r = dict(sound=[], planes=[], pointer=None)
    for line in out.splitlines():
        k, _, v = line.partition(' ')
        if k == 'end':
            r['end'] = v
        elif k == 'mem':
            r['mem'] = bytes.fromhex(v)
        elif k == 'plane':
            r['planes'].append(bytes.fromhex(v))
        elif k == 'pointer':
            r['pointer'] = (r['pointer'] or []) + [bytes.fromhex(v)]
        elif k == 'dac':
            r['dac'] = [int(x) for x in v.split()]
        elif k == 'sound':
            fn, _, arg = v.partition(' ')
            r['sound'].append('%d %s' % (int(fn), arg))
    r['storage'] = {}
    for f in os.listdir(d):
        data = open(os.path.join(d, f), 'rb').read()
        if before.get(f) != data:
            r['storage'][f] = data
    return r


def compare(name, got, ref):
    bad = []
    if got.get('end') != ref['end']:
        bad.append('end: engine %s, NV.OVL %s' % (got.get('end'), ref['end']))
    for lo, hi in RANGES:
        g, w = got['mem'][lo:hi], ref['mem'][lo:hi]
        if g != w:
            i = next(i for i in range(hi - lo) if g[i] != w[i])
            bad.append('memory %04X: engine %s, NV.OVL %s' % (lo + i, g[i:i + 8].hex(), w[i:i + 8].hex()))
    for p in range(4):
        if got['planes'][p] != ref['planes'][p]:
            n = sum(1 for a, b in zip(got['planes'][p], ref['planes'][p]) if a != b)
            i = next(i for i in range(32000) if got['planes'][p][i] != ref['planes'][p][i])
            bad.append('plane %d: %d bytes differ, first at x %d y %d' % (p, n, (i % 80) * 8, i // 80))
    if (got['pointer'] is None) != (ref['pointer'] is None):
        bad.append('pointer shown: engine %s, NV.OVL %s' % (got['pointer'] is not None,
                                                           ref['pointer'] is not None))
    elif got['pointer'] is not None and got['pointer'] != ref['pointer']:
        n = sum(1 for p in range(4) for a, b in zip(got['pointer'][p], ref['pointer'][p]) if a != b)
        bad.append('the frame with the pointer: %d bytes differ' % n)
    if got.get('dac') != ref['dac']:
        bad.append('dac: engine %s, NV.OVL %s' % (got.get('dac'), ref['dac']))
    if got['storage'] != ref['storage']:
        bad.append('saves written: engine %s, NV.OVL %s' % (sorted(got['storage']), sorted(ref['storage'])))
    if got['sound'] != ref['sound']:
        bad.append('sound: engine %s, NV.OVL %s' % (got['sound'][:12], ref['sound'][:12]))
    script = ref['mem'][0x9A:0xFD].split(b'\0')[0].decode('ascii', 'replace')
    print('%s: %s at %s%s, %d sound calls, %d saves: %s' % (
        name, ref['end'], script, ' (pointer shown)' if ref['pointer'] else '',
        len(ref['sound']), len(ref['storage']),
        'OK' if not bad else 'FAILED'))
    for b in bad:
        print('    ' + b)
    out = os.environ.get('CHECK_VM_OUT')
    if bad and out:
        write_png(os.path.join(out, name + '-engine.png'), got['planes'], got.get('dac') or [0] * 48)
        write_png(os.path.join(out, name + '-nvovl.png'), ref['planes'], ref['dac'])
    return not bad


def write_png(path, planes, dac):
    """the screen as an indexed PNG (CHECK_VM_OUT=DIR on failures), stdlib only"""
    sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
    import gpc
    pix = bytearray(640 * 400)
    for i in range(32000):
        for b in range(8):
            pix[i * 8 + b] = sum(((planes[p][i] >> (7 - b)) & 1) << p for p in range(4))
    gpc.write_png(path, 640, 400, bytes(pix), [tuple(dac[k * 3:k * 3 + 3]) for k in range(16)])


def main():
    exe, pak, original, fonts = sys.argv[1:5]
    names = sys.argv[5:] or list(SCENARIOS)
    try:
        import unicorn  # noqa: F401
    except ImportError:
        print('check_vm: skipped (no unicorn in this Python)')
        return 0
    ok = True
    for name in names:
        lang, saves, keys = SCENARIOS.get(name) or AFTER_M5[name]
        ref = run_reference(original, fonts, lang, saves, keys)
        got = run_engine(exe, pak, original, lang, saves, keys)
        ok &= compare(name, got, ref)
    print('check_vm: %d scenarios: %s' % (len(names), 'OK' if ok else 'FAILED'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
