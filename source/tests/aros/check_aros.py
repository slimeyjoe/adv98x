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

The rig is lrvne's (lrvne/rigs/README.md: aros/aros.sh, lrvrig/aros.py). Nothing waits for a
number of seconds: a run ends when its commands are done (aros.sh waits for their marker);
AROS_TIMEOUT (default 900 s) is each run's backstop, for a run that is stuck, and a run that did
not finish fails that check saying how (aros.sh's exit status). A run's system tree is removed
afterwards (its Work: kept).

Needs AROS_HOSTED or AROS_DIR in the environment or tests/rig.conf. Stdlib only.
"""
import argparse
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'lrvne', 'rigs'))
from lrvrig import aros, frames                             # noqa: E402

PLAY_TICKS = 30000
# random presses of return, up, down and esc every 20 ticks (menus, waits, the name entry),
# Shift held to skip text after the opening; a snapshot every 500 ticks
PLAY_SPEC = 'rand:11 shift:2000-%d snap:%s' % (
    PLAY_TICKS, ','.join(str(t) for t in range(500, PLAY_TICKS + 1, 500)))


def check(ref, run, label):
    """Problems of a run: its outcome, every reference snapshot against the AROS one."""
    snapdir = run.work('snaps')
    reqs = aros.requests(snapdir)
    problems = ([run.problem] if run.problem else []) + aros.compare(ref, reqs, snapdir, label)
    for line in aros.summary(run.out):
        print('    %s: %s' % (label, line))
    return problems


def cmd_present(args):
    ref = frames.present_reference(args.host_bin, args.pak)
    run = aros.run('present', [args.aros_bin, args.pak],
                   ['!MakeDir Work:snaps', 'Work:adv98x PRESENTTEST SNAPDIR=Work:snaps/'],
                   prune=not args.keep)
    return len(ref), check(ref, run, 'present'), run.rundir


def cmd_play(args, lang, preload):
    work = tempfile.mkdtemp(prefix='check-aros-')
    try:
        spec = os.path.join(work, 'play.spec')
        with open(spec, 'w') as f:
            f.write(PLAY_SPEC + '\n')
        storage = os.path.join(work, 'host-saves')
        os.makedirs(storage)
        ref = {f.name: f for f in frames.run([args.host_bin, '--pak', args.pak, '--lang', lang,
                                              '--no-audio', '--storage', storage, '--autoplay',
                                              '@' + spec, '--max-ticks', str(PLAY_TICKS)])}
        cmd = ('Work:adv98x LANG=%s AUDIO=none FAST AUTOPLAY=@Work:play.spec MAXTICKS=%d '
               'SNAPDIR=Work:snaps/ PRELOAD=%s' % (lang, PLAY_TICKS, preload))
        run = aros.run('play-' + lang, [args.aros_bin, args.pak, spec], ['!MakeDir Work:snaps', cmd],
                       prune=not args.keep)
        label = 'play %s' % lang
        problems = check(ref, run, label)
        saves = run.work('saves', 'nova')
        got = sorted(os.listdir(saves)) if os.path.isdir(saves) else []
        want = sorted(os.listdir(storage))
        if got != want:
            problems.append('%s: records %s, host %s' % (label, got, want))
        for fn in set(got) & set(want):
            if open(os.path.join(saves, fn), 'rb').read() != open(os.path.join(storage, fn), 'rb').read():
                problems.append('%s: record %s differs from the host\'s' % (label, fn))
        print('    %s: records written: %s' % (label, ' '.join(want) or 'none'))
        return len(ref), problems, run.rundir
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--aros-bin', required=True)
    ap.add_argument('--host-bin', required=True)
    ap.add_argument('--pak', required=True)
    ap.add_argument('--runs', help='where the run directories go (default: RIG_RUNS, else a '
                    'temporary directory)')
    ap.add_argument('--keep', action='store_true', help='keep the run directories, the system '
                    'trees too')
    ap.add_argument('what', nargs='*', default=['present', 'play'])
    args = ap.parse_args()
    for exe in (args.aros_bin, args.host_bin, args.pak):
        if not os.path.exists(exe):
            sys.exit('check_aros: %s is missing' % exe)
    temp = not (args.runs or os.environ.get('RIG_RUNS'))
    runs = os.path.abspath(args.runs or os.environ.get('RIG_RUNS') or tempfile.mkdtemp(prefix='aros-runs-'))
    os.environ['RIG_RUNS'] = runs
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
            shutil.rmtree(runs, ignore_errors=True)
    return rc


if __name__ == '__main__':
    sys.exit(main())
