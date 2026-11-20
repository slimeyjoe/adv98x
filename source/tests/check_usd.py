#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_usd.py TEST_USD [ORIGINAL]: the engine's music driver (engine/snd/usd.c) against
re-tools/usdmodel.py, the clean-room model of NOVA's USDdrv that is identical, write for write
and clock for clock, to the original driver (segment 0328 of NV.OV1) run under emulation
(usdmodel.py --check against re-tools/usdemu.py), and directly against the original driver's
recordings.

Scenarios run through usdmodel.Model and through test_usd (one process per scenario); every
register write is compared (clock, register, value), with the results of the calls that return
one and, at the end, the clock, the timer-A tick count and whether a channel is active. They are
those of usdmodel.py --check, with the same parameters:
  play       per song of ORIGINAL/pc98/A/MUS: `sound "file"` + `sound 1`, intro + --loops loop
             passes (3), capped at --cap seconds of song time (420)
  fade       per song: fade-in, fade-out, stop, restarts with volume offsets, raw fades, a
             restart over the playing song
  chain      all songs forwards then backwards on one driver instance
  phase      four songs x four phases of the two timers at the start call
  synthetic  --synth generated songs (400; usdmodel.synth_song with usdmodel's seed and its
             exact sequence of calls: groups of 8 songs on one driver, effect banks, play_se,
             stop by priority, fades with a threshold - what NOVA's files do not use)
  recording  per song with a recording resources/derived/music/vgm/<song>.tsv (usdemu.py
             --all --logs: the original driver under emulation, `sound "file"` + `sound 1`
             after AdvBIOS start-up, intro + 2 loop passes or 60 s): every write the original
             made after its start-up against test_usd run with the same calls up to the
             original's last interrupt (Model's default start state = that start-up)
Needs no unicorn (python3 -I is enough). --quick: --cap 60, --synth 80.
"""
import argparse
import os
import random
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 're-tools'))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
import gamedir  # noqa: E402
import usdmodel  # noqa: E402
import usoinfo  # noqa: E402

CLOCK = usdmodel.CLOCK
START_CLK, START_PHASE, START_TEMPO = usdmodel.Model.__init__.__defaults__
SCENARIOS = ('play', 'fade', 'chain', 'phase', 'synthetic', 'recording')


class Scenario:
    """usdmodel.Model driven by calls that are also recorded as test_usd commands; `out` is
    the output test_usd must print for them"""

    def __init__(self, title, phase=None):
        self.title = title
        if phase is None:
            self.m = usdmodel.Model()
            self.cmds = ['init']
        else:
            self.m = usdmodel.Model(START_CLK, phase, START_TEMPO)
            self.cmds = ['init %d %d %d %d' % (START_CLK, phase[0], phase[1], START_TEMPO)]
        self.out = ['init']
        self.nwrites = 0

    def _flush(self):
        w = self.m.writes
        if w:
            self.out.extend(map('%d %d %d'.__mod__, w))
            self.nwrites += len(w)
            del w[:]

    def _call(self, cmd, fn, *args, result=False):
        self.cmds.append(cmd)
        r = fn(*args)
        self._flush()
        if result:
            self.out.append('= %d' % int(r))

    def load(self, path):                   # script `sound "file"`: AH=02h, AH=00h
        self.stop()
        self._call('load ' + path, self.m.load, open(path, 'rb').read())

    def load_data(self, data):
        self._call('loadhex ' + data.hex(), self.m.load, data)

    def load_bank(self, data):
        self._call('bankhex ' + data.hex(), self.m.load_bank, data)

    def play(self):
        self._call('play', self.m.play, result=True)

    def volume(self, n):
        self._call('volume %d' % n, self.m.volume, n, result=True)

    def fade_in(self):
        self._call('fadein', self.m.fade_in)

    def fade_out(self):
        self._call('fadeout', self.m.fade_out)

    def stop(self):
        self._call('stop', self.m.stop)

    def fade(self, p, s, f):
        self._call('fade %d %d %d' % (p, s, f), self.m.fade, p, s, f)

    def stop_owner(self, n):
        self._call('stopowner %d' % n, self.m.stop_owner, n)

    def play_se(self, i):
        self._call('se %d' % i, self.m.play_se, i, result=True)

    def run(self, seconds=None, aticks=None):
        if seconds is not None:
            self._call('seconds %r' % seconds, self.m.run, seconds)
        else:
            self._call('aticks %d' % aticks, lambda: self.m.run(aticks=aticks))

    def end(self):
        self.cmds.append('clock')
        self.out.append('@ %d %d %d' % (self.m.clk, self.m.atick, any(self.m.active())))


def run_test(exe, cmds):
    p = subprocess.run([exe], input='\n'.join(cmds) + '\n', capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError('test_usd failed (%d): %s' % (p.returncode, p.stderr.strip()))
    return p.stdout


def first_difference(got, want):
    n = min(len(got), len(want))
    for i in range(n):
        if got[i] != want[i]:
            ctx = ['   %s %-24s %s' % ('>>' if j == i else '  ', want[j], got[j])
                   for j in range(max(0, i - 5), min(n, i + 6))]
            return 'line %d differs (reference | engine):\n%s' % (i + 1, '\n'.join(ctx))
    return 'reference has %d lines, the engine %d (the first %d equal)' % (len(want), len(got), n)


class Checker:
    def __init__(self, exe, verbose=False):
        self.exe = exe
        self.verbose = verbose
        self.scenarios = 0
        self.writes = 0
        self.bad = 0

    def compare(self, title, cmds, want, only_writes=False):
        """want: the expected output lines (writes only if only_writes)"""
        got = run_test(self.exe, cmds).splitlines()
        if only_writes:
            got = [ln for ln in got if ln[0].isdigit()]
        self.scenarios += 1
        nw = sum(1 for ln in got if ln[0].isdigit())
        self.writes += nw
        if got == want:
            if self.verbose:
                print('  %-34s %8d writes  identical' % (title, nw))
            return True
        self.bad += 1
        print('  %s: DIFFERENT\n%s' % (title, first_difference(got, want)))
        return False

    def scenario(self, s):
        s.end()
        self.compare(s.title, s.cmds, s.out)


# ---- the scenarios of usdmodel.py --check -------------------------------------------------
def check_play(ck, files, loops, cap):
    for path in files:
        tm = usoinfo.song_timing(usoinfo.load(path))
        s = Scenario('play %s' % os.path.basename(path))
        s.load(path)
        s.play()
        if tm['loops']:
            ticks = tm['intro'] + loops * tm['loop'] + 1 if tm['loop'] <= 40000 else None
            if ticks is not None and tm['seconds'] / tm['ticks'] * ticks <= cap:
                s.run(aticks=ticks)
            else:
                s.run(seconds=min(cap, 120.0) if ticks is None else cap)
        else:
            s.run(aticks=tm['ticks'] + 2)
            s.run(seconds=0.5)
        ck.scenario(s)


def check_fade(ck, files):
    for path in files:
        s = Scenario('fade %s' % os.path.basename(path))
        s.load(path)
        s.fade_in()
        s.run(seconds=6.0)
        s.fade_out()
        s.run(seconds=2.0)
        s.fade_in()                 # restart while fading out
        s.run(seconds=1.3)
        s.fade_out()
        s.run(seconds=5.5)
        s.stop()
        s.run(seconds=0.3)
        s.volume(-20)
        s.run(seconds=3.0)
        s.volume(-64)
        s.run(seconds=1.0)
        s.fade(3, 2, 0)             # raw: +2 every 3 effect ticks
        s.run(seconds=2.0)
        s.fade(1, -5, 0)
        s.run(seconds=0.7)
        s.play()                    # restart over the playing song, full volume
        s.run(seconds=4.0)
        s.stop()
        s.run(seconds=0.2)
        ck.scenario(s)


def check_chain(ck, files):
    s = Scenario('chain (%d songs)' % (2 * len(files)))
    for i, path in enumerate(files + files[::-1]):
        s.load(path)
        if i % 3:
            s.play()
        else:
            s.fade_in()
        s.run(seconds=4.0 if i % 4 else 1.7)
        if i % 5 == 0:
            s.play()                # start again over itself: channels are active
            s.run(seconds=1.1)
    ck.scenario(s)


def check_phase(ck, files):
    rng = random.Random(11)
    for name in ('NV08', 'NV14', 'NVSE01', 'NV10'):
        path = [f for f in files if os.path.basename(f).upper() == name + '.USO']
        if not path:
            continue
        for k in range(4):
            phase = (38016, 38016) if k == 0 else (rng.randrange(1, 53064), rng.randrange(1, 38016))
            s = Scenario('phase %s %d,%d' % (name, phase[0], phase[1]), phase)
            s.load(path[0])
            s.play()
            s.run(seconds=25.0)
            ck.scenario(s)


def check_synthetic(ck, count, seed):
    """usdmodel.check_synthetic without the emulator: the same random sequence"""
    rng = random.Random(seed)
    s = None
    nbank = 0
    for i in range(count):
        if s is None or i % 8 == 0:
            nbank = 0
            if s is not None:
                ck.scenario(s)
            s = Scenario('synthetic songs %d-%d' % (i, min(i + 8, count) - 1))
        data = usdmodel.synth_song(rng)
        if rng.random() < 0.8:
            s.stop()
        s.load_data(data)
        r = rng.random()
        if r < 0.5:
            s.play()
        elif r < 0.75:
            s.fade_in()
        else:
            s.volume(rng.randint(-70, 5))
        if rng.random() < 0.3:
            entries = [usdmodel.synth_song(rng, se=True) for _ in range(rng.randint(1, 3))]
            bank = struct.pack('<H', len(entries))
            off = 2 * len(entries)
            for en in entries:
                bank += struct.pack('<H', off)
                off += len(en)
            bank += b''.join(entries)
            s.load_bank(bank)
            s.play()
            nbank = len(entries)
        for _ in range(rng.randint(1, 4)):
            s.run(seconds=rng.uniform(0.2, 1.6))
            if nbank and rng.random() < 0.6:
                s.play_se(rng.randint(0, nbank))
                s.run(seconds=rng.uniform(0.1, 0.8))
            r = rng.random()
            if r < 0.15:
                s.fade_out()
            elif r < 0.30:
                s.fade(rng.randint(0, 4), rng.randint(-9, 9), rng.randint(0, 3))
            elif r < 0.40:
                s.stop_owner(rng.randint(1, 3))
            elif r < 0.50:
                s.play()
            elif r < 0.55:
                s.fade_in()
    if s is not None:
        ck.scenario(s)


# ---- the original's recordings --------------------------------------------------------------
def check_recordings(ck, files, recdir):
    """usdemu.py's TSV: clock, seconds since the play call, kind (I = start-up, C = INT F4h
    call, A/B/AB = interrupt), irq number, tick, register (hex), value (hex)"""
    n = 0
    for path in files:
        stem = os.path.splitext(os.path.basename(path))[0]
        tsv = os.path.join(recdir, stem + '.tsv')
        if not os.path.exists(tsv):
            continue
        with open(tsv) as f:
            next(f)
            recs = [line.split('\t') for line in f]
        title = 'recording %s' % stem
        # the play call (seconds 0) must be where usdmodel.Model() takes over: the
        # rest of the start-up state (timer phases, tempo) shows in the comparison
        t0 = int(recs[0][0]) - int(round(float(recs[0][1]) * CLOCK)) if recs else None
        if t0 is None or abs(t0 - START_CLK) > 4:
            print('  %s: the play call is not at clock %d (%s)' % (title, START_CLK, t0))
            ck.bad += 1
            continue
        # the start-up's writes are kind I or interrupts before the play call
        rows = ['%d %d %d' % (int(clk), int(reg, 16), int(val, 16))
                for clk, _sec, kind, _irq, _tick, reg, val in recs
                if kind == 'C' or int(clk) > START_CLK]
        if not rows:
            print('  %s: no writes after the play call' % title)
            ck.bad += 1
            continue
        last = int(rows[-1].split()[0])
        cmds = ['init', 'stop', 'load ' + path, 'play', 'until %d' % last]
        ck.compare(title, cmds, rows, only_writes=True)
        n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('exe', help='test_usd')
    ap.add_argument('original', nargs='?', default=gamedir.original())
    ap.add_argument('--recordings', default=gamedir.derived(None, 'music', 'vgm'))
    ap.add_argument('--songs', help='comma-separated song names (default: all)')
    ap.add_argument('--only', help='comma-separated scenarios: ' + ','.join(SCENARIOS))
    ap.add_argument('--loops', type=int, default=3)
    ap.add_argument('--cap', type=float, default=420.0)
    ap.add_argument('--synth', type=int, default=400)
    ap.add_argument('--seed', type=int, default=1993)
    ap.add_argument('--quick', action='store_true', help='--cap 60 --synth 80')
    ap.add_argument('-v', '--verbose', action='store_true')
    a = ap.parse_args()
    if a.quick:
        a.cap, a.synth = 60.0, 80
    only = set(a.only.split(',')) if a.only else set(SCENARIOS)
    unknown = only - set(SCENARIOS)
    if unknown:
        ap.error('unknown scenario %s' % ', '.join(sorted(unknown)))
    musdir = os.path.join(a.original, 'pc98', 'A', 'MUS')
    files = sorted(os.path.join(musdir, f) for f in os.listdir(musdir)
                   if f.upper().endswith('.USO')) if os.path.isdir(musdir) else []
    if a.songs:
        want = {x.upper().replace('.USO', '') for x in a.songs.split(',')}
        files = [f for f in files if os.path.basename(f).upper()[:-4] in want]
    if not files:
        print('check_usd: no songs in %s: only the synthetic scenario' % musdir)
    ck = Checker(a.exe, a.verbose)
    if files:
        if 'play' in only:
            check_play(ck, files, a.loops, a.cap)
        if 'fade' in only:
            check_fade(ck, files)
        if 'chain' in only:
            check_chain(ck, files)
        if 'phase' in only:
            check_phase(ck, files)
    if 'synthetic' in only and a.synth > 0:
        check_synthetic(ck, a.synth, a.seed)
    nrec = 0
    if files and 'recording' in only:
        if os.path.isdir(a.recordings):
            nrec = check_recordings(ck, files, a.recordings)
        if not nrec:
            print('check_usd: no recordings <song>.tsv in %s (re-tools/usdemu.py --all --logs): '
                  'skipped' % a.recordings)
    print('check_usd: %d scenarios (%d songs, %d synthetic, %d recordings of the original), '
          '%d writes compared: %s' % (ck.scenarios, len(files), a.synth if 'synthetic' in only else 0,
                                      nrec, ck.writes, 'OK' if not ck.bad else '%d FAILED' % ck.bad))
    return 1 if ck.bad else 0


if __name__ == '__main__':
    sys.exit(main())
