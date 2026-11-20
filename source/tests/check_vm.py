#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_vm.py TEST_VM PAK ORIGINAL FONTS [SCENARIO... | routes]: the engine against the original
interpreter. Each scenario starts the game at its start script (the profile's `start`) with given
save files and key presses and runs it twice: through the engine (test_vm) and through NV.OVL on
AdvBIOS under emulation (re-tools/nvovl_emu.py). Both stop when the game waits for input and no key is left (or ends);
then these must be identical:

  * the interpreter's state: 0000-00FFh (flags, variables, script name, drives), the script
    and sub-script buffers 9000-BFFFh and C006-D005h, the interpreter's variables D006-D8BFh (text state, menu
    tables, menu2 buffer, procedure slots), the player's name D937-D958h, the parameter and
    file-name buffers D9E3-DAFFh and the save buffer DB20-DC1Fh. (0100-8FFFh holds the
    plug-ins' code in the original and is not compared; the engine replaces them.)
  * the text VRAM (A000h-A3FFh: codes and attributes; the curtain);
  * the screen: all four planes of the page, and, where the pointer is shown, the frame with
    the pointer (drawn into VRAM by AdvBIOS's driver, into the presented frame by the engine);
  * the DAC (palette at the current brightness);
  * the save files written;
  * the sound calls (INT F4h function and argument), in order;
  * every palette write of the plug-ins (INT F3h AH=13h / 15h), in order.

The scenarios are the game's (its tests/cases.py, written with casekit.py): SCENARIOS play the
game's own scripts; SYNTHETIC ones run test scripts assembled there, put in place of the start
script on both sides, for what the game reaches only late (plug-ins' calls, say).

ROUTES (`routes`: all of them; `make e2e`, not in the default run: minutes each under
emulation) play a whole story. The input comes from the exploring player of tests/e2e/explore.py
run on the engine (adv98x next to the test programs) with the story choices fixed per route,
recorded as keys and clicks; both sides then replay it from the start script until the game
writes the route's unlock file (an ending may loop for ever after it), where the state is
compared as above. The route must pass through the script the route names.

Scenarios run in parallel (CHECK_VM_JOBS, default: the number of CPUs).
CHECK_VM_OUT=DIR writes both screens of a failing scenario there as PNG.

Input is the PC-98 keyboard: a key is accepted only while the game waits for one. The dumped
copy's own saves (in the game's cases.SAVES_DIR) are the test inputs of the scenarios that need
saves; they are never packed, and those scenarios are skipped without them.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 're-tools'))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
import gamedir  # noqa: E402

GAME = gamedir.cases()
from casekit import RESET  # noqa: E402  (gamedir.cases() put it on the path)

SCENARIOS, SYNTHETIC, ROUTES = GAME.SCENARIOS, GAME.SYNTHETIC, GAME.ROUTES
START = gamedir.load().PROFILE['start']                 # the start script, as the game names it
START_NAME = START.split('\\')[-1].upper()

# the interpreter's memory compared (the build of re-tools/advbuild.py)
RANGES = [(0x0000, 0x0100), (0x9000, 0xC000), (0xC006, 0xD006), (0xD006, 0xD8C0), (0xD937, 0xD959),
          (0xD9E3, 0xDB00), (0xDB20, 0xDC20)]


def save_file(original, name):
    """one of the dumped copy's own saves (the game's cases.SAVES_DIR)"""
    return os.path.join(original, GAME.SAVES_DIR, name)


def run_reference(original, fonts, lang, saves, keys, script=None, stop=None):
    import nvovl_emu
    if RESET in keys:                           # the machine started again: what follows
        keys = keys[len(keys) - keys[::-1].index(RESET):]
    storage = {s: open(save_file(original, s), 'rb').read() for s in saves}
    files = GAME.interpreter_files(original, lang)
    if script:
        files[START_NAME] = script
    emu = nvovl_emu.NvOvlEmu(files, fonts=fonts, keys=list(keys), storage=storage, stop_save=stop)
    r = emu.run(START, count=100_000_000_000 if stop else 400_000_000)
    written = {k: v for k, v in r['storage'].items() if storage.get(k) != v}
    return dict(end=r['end'], mem=r['mem'], planes=r['planes'], pointer=r['pointer_planes'],
                palette_log=r['palette_log'], tvram=r['tvram'],
                dac=[v for rgb in emu.dac for v in rgb], storage=written,
                sound=['%d %s' % (ah, '-' if a is None else a) for ah, a in r['sound']])


def script_pack(pak, script):
    """the pack with the start script replaced by a test script (in every language)"""
    sys.path.insert(0, os.path.join(HERE, '..', 'lrvne', 'tools'))
    from lrvne import xpak
    pack = xpak.read_pack(open(pak, 'rb').read())
    out = xpak.PackWriter(langs=[pack.langs[i] for i in sorted(pack.langs)])
    for e in pack.entries:
        if e.name != xpak.LANGS_ENTRY:          # the writer makes that entry itself
            out.add(e.raw_name, e.type, script if e.name == START_NAME else e.data,
                    lang=e.lang_tag or None)
    path = os.path.join(tempfile.mkdtemp(prefix='adv98x-pak-'), 'test.pak')
    out.write(path)
    return path


def route_keys(exe, pak, original, name):
    """the route's input: the exploring player on the engine, recorded"""
    lang, saves, title, choose, unlock, via = ROUTES[name]
    d = tempfile.mkdtemp(prefix='adv98x-route-')
    for s in saves:
        open(os.path.join(d, s), 'wb').write(open(save_file(original, s), 'rb').read())
    rec, route = os.path.join(d, 'keys.json'), os.path.join(d, 'route.txt')
    cmd = [sys.executable, '-I', os.path.join(HERE, 'e2e', 'explore.py'), exe, pak, original,
           '--lang', lang, '--storage', d, '--until-save', unlock, '--title-pick', str(title),
           '--frames', '600000', '--record', rec, '--route-file', route]
    for c in choose:
        cmd += ['--choose', c]
    subprocess.run(cmd, check=True, capture_output=True)
    if via not in open(route).read().split():
        raise RuntimeError('%s: the route does not pass through %s' % (name, via))
    import json
    return [tuple(k) for k in json.load(open(rec))]


def run_engine(exe, pak, original, lang, saves, keys, script=None, stop=None):
    if script:
        pak = script_pack(pak, script)
    d = tempfile.mkdtemp(prefix='adv98x-vm-')
    before = {}
    for s in saves:
        data = open(save_file(original, s), 'rb').read()
        open(os.path.join(d, s), 'wb').write(data)
        before[s] = data
    keystr = ','.join('C:%d:%d' % k[1:] if k[0] == 'click' else 'R*' if k[0] == 'ret*' else
                      'RESET' if k[0] == 'reset' else '%02X%02X' % k for k in keys) or '-'
    env = dict(os.environ)
    if stop:
        env['TEST_VM_STOP_SAVE'] = stop
    out = subprocess.run([exe, pak, d, lang, keystr], capture_output=True, text=True, env=env).stdout
    r = dict(sound=[], planes=[], pointer=None, palette_log=[])
    for line in out.splitlines():
        k, _, v = line.partition(' ')
        if k == 'end':
            r['end'] = v
        elif k == 'mem':
            r['mem'] = bytes.fromhex(v)
        elif k == 'plane':
            r['planes'].append(bytes.fromhex(v))
        elif k == 'tvram':
            r['tvram'] = bytes.fromhex(v)
        elif k == 'pal':
            r['palette_log'].append(v)
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
    if got.get('tvram') != ref['tvram']:
        n = sum(1 for a, b in zip(got.get('tvram') or b'', ref['tvram']) if a != b)
        bad.append('text VRAM: %d bytes differ' % n)
    if got.get('dac') != ref['dac']:
        bad.append('dac: engine %s, NV.OVL %s' % (got.get('dac'), ref['dac']))
    if got['storage'] != ref['storage']:
        bad.append('saves written: engine %s, NV.OVL %s' % (sorted(got['storage']), sorted(ref['storage'])))
    if got['palette_log'] != ref['palette_log']:
        i = next((i for i, (a, b) in enumerate(zip(got['palette_log'], ref['palette_log'])) if a != b),
                 min(len(got['palette_log']), len(ref['palette_log'])))
        bad.append('palette writes (%d / %d): first difference at %d: engine %s, NV.OVL %s' % (
            len(got['palette_log']), len(ref['palette_log']), i,
            got['palette_log'][i:i + 1], ref['palette_log'][i:i + 1]))
    if got['sound'] != ref['sound']:
        bad.append('sound: engine %s, NV.OVL %s' % (got['sound'][:12], ref['sound'][:12]))
    script = ref['mem'][0x9A:0xFD].split(b'\0')[0].decode('ascii', 'replace')
    print('%s: %s at %s%s, %d sound calls, %d palette writes, %d saves: %s' % (
        name, ref['end'], script, ' (pointer shown)' if ref['pointer'] else '',
        len(ref['sound']), len(ref['palette_log']), len(ref['storage']),
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
    names = sys.argv[5:] or list(SCENARIOS) + list(SYNTHETIC)
    if names == ['routes']:
        names = list(ROUTES)
    skipped = [n for n in names if n in SCENARIOS
               and not all(os.path.exists(save_file(original, f)) for f in SCENARIOS[n][1])]
    if skipped:
        print('check_vm: skipped without the dumped copy\'s saves: %s' % ' '.join(skipped))
        names = [n for n in names if n not in skipped]
    try:
        import unicorn  # noqa: F401
    except ImportError:
        print('check_vm: skipped (no unicorn in this Python)')
        return 0
    adv98x = os.path.join(os.path.dirname(os.path.abspath(exe)), '..', 'adv98x')
    jobs = []
    for name in names:
        script = stop = None
        if name in SYNTHETIC:
            lang, saves, keys, make = SYNTHETIC[name]
            script = make()
        elif name in ROUTES:
            lang, saves, stop = ROUTES[name][0], ROUTES[name][1], ROUTES[name][4]
            keys = route_keys(adv98x, pak, original, name)
        else:
            lang, saves, keys = SCENARIOS[name]
        jobs.append((name, (lang, saves, keys, script, stop)))
    import concurrent.futures
    n = int(os.environ.get('CHECK_VM_JOBS', 0)) or os.cpu_count() or 1
    ok = True
    with concurrent.futures.ProcessPoolExecutor(max_workers=min(n, len(jobs))) as pool:
        refs = [pool.submit(run_reference, original, fonts, *args) for _, args in jobs]
        for (name, args), ref in zip(jobs, refs):
            got = run_engine(exe, pak, original, *args)
            ok &= compare(name, got, ref.result())
            sys.stdout.flush()
    print('check_vm: %d scenarios: %s' % (len(names), 'OK' if ok else 'FAILED'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
