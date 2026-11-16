#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_aros.py --aros-bin B --host-bin H --pak P [--runs DIR] [--keep] [present] [play]:
the AROS build in hosted AROS (tests/aros/aros.sh, docs/amiga.md "Testing") against the headless
host build (the null backend) given the same input.

  present  the presentation test (lrvne's backends/common/ptest.h) in the engine's video mode:
           PRESENTTEST on AROS, --present-test on the host
  play     the game from its start under scripted input (lrvne's backends/common/autoplay.h),
           once per language: AUDIO=none FAST AUTOPLAY=@spec MAXTICKS=N on AROS, the same spec
           with --autoplay on the host; the English run reads the pack from its file
           (PRELOAD=no), the Japanese one from memory

Each snapshot is checked two ways: the frame hash the AROS program computed of what it
presented (lrv_frame_hash32) must be the host's for the same snapshot, and the picture the
program read back from its screen (lrvne's backends/amiga/aros/snap_aros.c, a PPM in SNAPDIR)
must be the host frame's colours, each 4-bit DAC value times 17 (black with graphics off). After
a play run the records the game wrote (the player's name, saves) must be the host's, byte for
byte. The host build is the reference only for what is the same C on both: the engine and
lrvne; it is itself checked against the original (tests/run.sh).

Nothing waits for a number of seconds: a run ends when its commands are done (aros.sh waits for
their marker); AROS_TIMEOUT (default 900 s) is each run's backstop, for a run that is stuck, and
a run that did not finish fails that check saying how (aros.sh's exit status).

Needs AROS_HOSTED in the environment (aros.sh). Stdlib only.
"""
import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ARGS_SH = os.path.join(HERE, 'aros.sh')
W, H = 640, 400
TIMEOUT = int(os.environ.get('AROS_TIMEOUT', '900'))
OUTCOMES = {3: 'AROS ended before the commands were done', 4: 'the X server could not start',
            124: 'timeout (the backstop, AROS_TIMEOUT=%d s): the run did not end' % TIMEOUT}
PLAY_TICKS = 30000
# random presses of return, up, down and esc every 20 ticks (menus, waits, the name entry),
# Shift held to skip text after the opening; a snapshot every 500 ticks
PLAY_SPEC = 'rand:11 shift:2000-%d snap:%s' % (
    PLAY_TICKS, ','.join(str(t) for t in range(500, PLAY_TICKS + 1, 500)))


def host_frames(cmd, cwd=None):
    """The snapshots a host run prints: {name: record}; the exit code."""
    p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    frames = {}
    for line in p.stdout.splitlines():
        d = json.loads(line)
        if d.get('ev') == 'snap':
            frames[d['name']] = d
    return frames, p.returncode


def expected_rgb(d):
    """The frame's picture as 640x400 RGB bytes."""
    if not d['gon']:
        return bytes(W * H * 3)
    pal = bytes.fromhex(d['pal'])
    lut = [bytes(v * 17 for v in pal[3 * i:3 * i + 3]) for i in range(16)]
    out = bytearray()
    for b in base64.b64decode(d['data']):
        out += lut[b >> 4] + lut[b & 15]
    return bytes(out)


def read_ppm(path):
    with open(path, 'rb') as f:
        data = f.read()
    fields, pos = [], 0
    while len(fields) < 4:                      # P6 width height maxval, then one blank
        while data[pos:pos + 1].isspace():
            pos += 1
        start = pos
        while not data[pos:pos + 1].isspace():
            pos += 1
        fields.append(data[start:pos])
    if fields[0] != b'P6' or fields[3] != b'255':
        raise ValueError('%s: not an 8-bit P6 picture' % path)
    return int(fields[1]), int(fields[2]), data[pos + 1:]


def aros_snaps(snapdir):
    """{name: words of its request file} (lrvne's backends/amiga/core/snap.c)."""
    recs = {}
    for fn in sorted(os.listdir(snapdir)) if os.path.isdir(snapdir) else []:
        if fn.startswith('snap_') and fn.endswith('.req'):
            with open(os.path.join(snapdir, fn)) as f:
                words = dict(w.split('=', 1) for w in f.read().split() if '=' in w)
            recs[words.get('name')] = words
    return recs


def compare(ref, recs, snapdir, label):
    """Problems: every reference snapshot against the AROS one of the same name."""
    problems = []
    for name in ref:
        rec = recs.get(name)
        if rec is None:
            problems.append('%s %s: no snapshot from AROS' % (label, name))
            continue
        if rec.get('hash') != ref[name]['hash']:
            problems.append('%s %s: frame hash %s, host %s' % (label, name, rec.get('hash'),
                                                                ref[name]['hash']))
        if 'image' not in rec:
            problems.append('%s %s: no picture read back' % (label, name))
            continue
        w, h, rgb = read_ppm(os.path.join(snapdir, rec['image']))
        want = expected_rgb(ref[name])
        if (w, h) != (W, H) or len(rgb) < len(want):
            problems.append('%s %s: picture %dx%d, expected %dx%d' % (label, name, w, h, W, H))
            continue
        if rgb[:len(want)] == want:
            continue
        bad = [i for i in range(0, len(want), 3) if rgb[i:i + 3] != want[i:i + 3]]
        if bad:
            y, x = divmod(bad[0] // 3, W)
            problems.append('%s %s: %d pixels differ, the first at x %d y %d' % (
                label, name, len(bad), x, y))
    extra = sorted(set(recs) - set(ref))
    if extra:
        problems.append('%s: AROS snapshots the host has not: %s' % (label, ' '.join(extra[:5])))
    return problems


def run_aros(args, name, files, commands):
    """runs the commands in hosted AROS: the run dir, aros.sh's log, the program's output and
    the run's problem (None when it finished)"""
    rundir = os.path.join(args.runs, name)
    env = dict(os.environ, AROS_FILES=' '.join(files))
    log = subprocess.run([ARGS_SH, rundir, str(TIMEOUT)], input='\n'.join(commands) + '\n',
                         text=True, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = os.path.join(rundir, 'AROS', 'out.txt')
    text = open(out, errors='replace').read() if os.path.exists(out) else ''
    problem = None
    if log.returncode:
        problem = '%s: hosted AROS: %s' % (name, OUTCOMES.get(log.returncode, 'aros.sh exit %d: %s' % (
            log.returncode, log.stdout.strip()[-300:])))
    return rundir, log.stdout.strip(), text, problem


def report_run(label, log, out):
    for line in out.splitlines():
        if line.startswith(('stack:', 'memory:', 'exit ', 'timer:', 'max ticks')):
            print('    %s: %s' % (label, line))


def cmd_present(args):
    frames, _ = host_frames([args.host_bin, '--pak', args.pak, '--present-test'])
    ref = {'%02d-%s' % (d['t'], name): d for name, d in frames.items()}
    rundir, log, out, problem = run_aros(args, 'present', [args.aros_bin, args.pak],
                                         ['!MakeDir Work:snaps',
                                          'Work:adv98x PRESENTTEST SNAPDIR=Work:snaps/'])
    snapdir = os.path.join(rundir, 'AROS', 'Work', 'snaps')
    problems = ([problem] if problem else []) + compare(ref, aros_snaps(snapdir), snapdir, 'present')
    report_run('present', log, out)
    return len(ref), problems, rundir


def cmd_play(args, lang, preload):
    work = tempfile.mkdtemp(prefix='check-aros-')
    try:
        spec = os.path.join(work, 'play.spec')
        with open(spec, 'w') as f:
            f.write(PLAY_SPEC + '\n')
        storage = os.path.join(work, 'host-saves')
        os.makedirs(storage)
        ref, _ = host_frames([args.host_bin, '--pak', args.pak, '--lang', lang, '--no-audio',
                              '--storage', storage, '--autoplay', '@' + spec,
                              '--max-ticks', str(PLAY_TICKS)])
        cmd = ('Work:adv98x LANG=%s AUDIO=none FAST AUTOPLAY=@Work:play.spec MAXTICKS=%d '
               'SNAPDIR=Work:snaps/ PRELOAD=%s' % (lang, PLAY_TICKS, preload))
        rundir, log, out, problem = run_aros(args, 'play-' + lang, [args.aros_bin, args.pak, spec],
                                             ['!MakeDir Work:snaps', cmd])
        snapdir = os.path.join(rundir, 'AROS', 'Work', 'snaps')
        label = 'play %s' % lang
        problems = ([problem] if problem else []) + compare(ref, aros_snaps(snapdir), snapdir, label)
        saves = os.path.join(rundir, 'AROS', 'Work', 'saves', 'nova')
        got = sorted(os.listdir(saves)) if os.path.isdir(saves) else []
        want = sorted(os.listdir(storage))
        if got != want:
            problems.append('%s: records %s, host %s' % (label, got, want))
        for fn in set(got) & set(want):
            if open(os.path.join(saves, fn), 'rb').read() != open(os.path.join(storage, fn), 'rb').read():
                problems.append('%s: record %s differs from the host\'s' % (label, fn))
        report_run(label, log, out)
        print('    %s: records written: %s' % (label, ' '.join(want) or 'none'))
        return len(ref), problems, rundir
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--aros-bin', required=True)
    ap.add_argument('--host-bin', required=True)
    ap.add_argument('--pak', required=True)
    ap.add_argument('--runs', help='where the run directories go (each a copy of the hosted '
                    'system, ~170 MB; default: a temporary directory)')
    ap.add_argument('--keep', action='store_true', help='keep the run directories')
    ap.add_argument('what', nargs='*', default=['present', 'play'])
    args = ap.parse_args()
    for exe in (args.aros_bin, args.host_bin, args.pak):
        if not os.path.exists(exe):
            sys.exit('check_aros: %s is missing' % exe)
    if not os.environ.get('AROS_HOSTED'):
        sys.exit('check_aros: set AROS_HOSTED to the hosted AROS system (docs/amiga.md "Testing")')
    temp = not args.runs
    args.runs = os.path.abspath(args.runs or tempfile.mkdtemp(prefix='aros-runs-'))
    jobs = []
    if 'present' in args.what:
        jobs.append(('present', cmd_present))
    if 'play' in args.what:
        jobs.append(('play ja', lambda a: cmd_play(a, 'ja', 'yes')))
        jobs.append(('play en', lambda a: cmd_play(a, 'en', 'no')))
    rc = 0
    try:
        for label, fn in jobs:
            n, problems, rundir = fn(args)
            for p in problems[:20]:
                print('    ' + p)
            print('check_aros %s: %d snapshots: %s' % (label, n, 'OK' if not problems and n else 'FAILED'))
            rc |= 1 if problems or not n else 0
            if not args.keep:
                shutil.rmtree(rundir, ignore_errors=True)
    finally:
        if temp and not args.keep:
            shutil.rmtree(args.runs, ignore_errors=True)
    return rc


if __name__ == '__main__':
    sys.exit(main())
