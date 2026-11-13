#!/usr/bin/env python3
"""usoinfo.py - structure dump of .USO song files (USDdrv / USDtrap, K.KONDO 1991, the
YM2203 music driver inside AdvBIOS 0.54; see docs/re/usd-sequencer.md).

  python3 -I re-tools/usoinfo.py FILE.USO [...]        full dump: header, track records, voice
                                                       blocks field by field, every track
                                                       disassembled, loop structure, lengths
  python3 -I re-tools/usoinfo.py --tsv [FILE...]       one row per file (default: all of MUS/)
  python3 -I re-tools/usoinfo.py --check [FILE...]     byte accounting + structural checks
  python3 -I re-tools/usoinfo.py --stats [FILE...]     command usage counts over the files
  python3 -I re-tools/usoinfo.py --index OUT.tsv       write the per-song table
                                                       (resources/music/index.tsv)

Everything here follows the driver code (NV.OV1 segment 0328): header binding 0328:02FE,
track start 0328:0C5F, the two byte-code interpreters 0328:16C8 (FM) / 0328:17D2 (SSG) and
their shared command table 0328:195E / 199E.  The dump prints the game's data: redirect it
under resources/derived/ only.

As a module:  parse(data) -> Song;  Song.tracks[i].ins = [Ins];  flow(song, i) -> TrackFlow;
song_timing(song) -> dict.
"""
import argparse
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MUSDIR = os.path.join(ROOT, 'resources', 'original', 'pc98', 'A', 'MUS')

OPN_CLOCK = 3993600
LEN_TABLE = [192, 144, 96, 72, 48, 36, 24, 18, 12, 9, 6]      # 0328:07C0, ticks; 192 = whole note
NOTE_NAMES = ['c', 'c+', 'd', 'd+', 'e', 'f', 'f+', 'g', 'g+', 'a', 'a+', 'b']
GATE_NAMES = {0: 'full', 1: '1/8', 2: '2/8', 3: '3/8', 4: '4/8', 5: '5/8', 6: '6/8', 7: '7/8'}
FM_VOICE_SIZE, SSG_VOICE_SIZE = 39, 30

# command byte -> (mnemonic, operand format); formats: b = byte, s = signed byte, w = word,
# j = signed word relative to the byte after it.  Everything else in C0..FF is a 1-byte no-op.
COMMANDS = {
    0xFF: ('end', ''),
    0xFE: ('transpose', 's'),
    0xFD: ('volume', 's'),
    0xFC: ('detune', 's'),
    0xFB: ('tempo', 'w'),
    0xF8: ('gate', 'b'),
    0xF7: ('tie', ''),
    0xF6: ('porta', 'b'),
    0xF5: ('jump', 'j'),
    0xF4: ('loop_exit', 'bbj'),
    0xF3: ('loop_back', 'bbj'),
    0xE1: ('fm_voice', 'b'),
    0xE0: ('ssg_voice', 'b'),
}


def u16(b, o):
    return struct.unpack_from('<H', b, o)[0]


def s8(v):
    return v - 256 if v & 0x80 else v


def s16(v):
    return v - 65536 if v & 0x8000 else v


def note_name(n):
    if n < 0:
        return 'n%d' % n
    return '%s%d' % (NOTE_NAMES[n % 12], n // 12)


def timer_a_value(word):
    """tempo word -> YM2203 timer A value NA (reg 24h = low byte, reg 25h = bits 8-9)."""
    return ((word & 0xFF) << 2) | ((word >> 8) & 3)


def tick_seconds(word):
    return 72.0 * (1024 - timer_a_value(word)) / OPN_CLOCK


class FormatError(Exception):
    pass


class Ins:
    """one byte-code instruction"""
    __slots__ = ('off', 'size', 'op', 'name', 'args', 'length', 'note', 'target')

    def __init__(self, off, size, op, name, args=(), length=None, note=None, target=None):
        self.off, self.size, self.op, self.name = off, size, op, name
        self.args, self.length, self.note, self.target = args, length, note, target


class Track:
    def __init__(self, index, channel, priority, rel, garbage):
        self.index, self.channel, self.priority, self.rel, self.garbage = \
            index, channel, priority, rel, garbage
        self.start = None      # file offset of the first byte
        self.end = None        # file offset one past the track's region
        self.ins = []
        self.by_off = {}

    @property
    def kind(self):
        return 'FM' if self.channel < 3 else 'SSG'

    @property
    def chname(self):
        return '%s%d' % (self.kind, self.channel % 3 + 1) if self.channel < 6 else '?%d' % self.channel


class Song:
    pass


def decode_ins(d, p, end):
    """decode one instruction at file offset p (driver: 0328:16D0 / 17DA)."""
    b = d[p]
    if b < 0xB0:
        return Ins(p, 1, b, 'note' if b & 15 else 'rest', length=LEN_TABLE[b >> 4], note=b & 15)
    if b < 0xC0:
        if p + 1 >= end:
            raise FormatError('truncated length at %04X' % p)
        v = d[p + 1]
        if v & 0x80:
            if p + 2 >= end:
                raise FormatError('truncated length at %04X' % p)
            return Ins(p, 3, b, 'note' if b & 15 else 'rest',
                       length=((v << 8) | d[p + 2]) & 0x7FFF, note=b & 15)
        return Ins(p, 2, b, 'note' if b & 15 else 'rest', length=v, note=b & 15)
    name, fmt = COMMANDS.get(b, ('nop', ''))
    q = p + 1
    args = []
    target = None
    for f in fmt:
        if f in 'bs':
            if q >= end:
                raise FormatError('truncated operand at %04X' % p)
            args.append(s8(d[q]) if f == 's' else d[q])
            q += 1
        else:
            if q + 1 >= end:
                raise FormatError('truncated operand at %04X' % p)
            v = u16(d, q)
            q += 2
            if f == 'j':
                target = (q + s16(v))
                args.append(s16(v))
            else:
                args.append(v)
    return Ins(p, q - p, b, name, tuple(args), target=target)


def parse(data, name='?'):
    d = bytes(data)
    s = Song()
    s.name, s.data, s.size = name, d, len(d)
    if len(d) < 8:
        raise FormatError('too short')
    s.owner, s.ntracks, s.nblocks = u16(d, 0), u16(d, 2), u16(d, 4)
    if not 1 <= s.ntracks <= 6:
        raise FormatError('track count %d (driver refuses 0 and > 6)' % s.ntracks)
    s.tracks = []
    p = 6
    for i in range(s.ntracks):
        ch, prio, rel = d[p], d[p + 1], u16(d, p + 2)
        s.tracks.append(Track(i, ch, prio, rel, d[p + 4:p + 10]))
        p += 10
    s.blocks = []          # (type, file offset of payload, length)
    s.fm_voices, s.ssg_voices = [], []
    s.fm_block = s.ssg_block = None
    for i in range(s.nblocks):
        typ, ln = u16(d, p), u16(d, p + 2)
        s.blocks.append((typ, p + 4, ln))
        if typ == 0:
            s.fm_block = (p + 4, ln)       # a later block of the same kind replaces an earlier one
        else:
            s.ssg_block = (p + 4, ln)
        p += 4 + ln
    if s.fm_block:
        o, ln = s.fm_block
        s.fm_voices = [d[o + k:o + k + FM_VOICE_SIZE] for k in range(0, ln - FM_VOICE_SIZE + 1, FM_VOICE_SIZE)]
    if s.ssg_block:
        o, ln = s.ssg_block
        s.ssg_voices = [d[o + k:o + k + SSG_VOICE_SIZE] for k in range(0, ln - SSG_VOICE_SIZE + 1, SSG_VOICE_SIZE)]
    s.lenword_off = p
    s.datalen = u16(d, p)
    s.base = p + 2
    starts = sorted(set(t.rel for t in s.tracks))
    for t in s.tracks:
        t.start = s.base + t.rel
        nxt = [x for x in starts if x > t.rel]
        t.end = s.base + nxt[0] if nxt else len(d)
        q = t.start
        while q < t.end:
            ins = decode_ins(d, q, t.end)
            t.ins.append(ins)
            t.by_off[q] = ins
            q += ins.size
    return s


# ---------------------------------------------------------------- flow (ticks, loops)
class TrackFlow:
    """result of following one track's control flow"""

    def __init__(self):
        self.ended = False        # reached FF
        self.total = 0            # ticks until FF (ended) or until the state first repeats
        self.loop_start = None    # tick at which the repeating part begins
        self.loop_len = None
        self.tempos = []          # (tick, word) tempo commands, tick = 0-based start tick of the row
        self.notes = 0
        self.max_loop_index = -1
        self.stuck = False        # loops without consuming time (driver would hang)
        self.events = 0


def flow(song, ti, max_events=2000000):
    """Follow track ti the way the driver does (loop counters 0328:1A7A / 1A99) without
    producing sound: returns tick positions, loop structure and tempo commands."""
    t = song.tracks[ti]
    d = song.data
    f = TrackFlow()
    cnt = {}
    pos = t.start
    tick = 0
    seen = {}
    last_tick_at_jump = None
    while f.events < max_events:
        if pos not in t.by_off:
            raise FormatError('%s track %d: flow leaves the track at %04X' % (song.name, ti, pos))
        ins = t.by_off[pos]
        f.events += 1
        nxt = pos + ins.size
        if ins.name in ('note', 'rest'):
            if ins.name == 'note':
                f.notes += 1
            tick += ins.length if ins.length else 65536     # counter 0 wraps: 65536 ticks
            pos = nxt
            continue
        taken = False
        if ins.name == 'end':
            f.ended = True
            break
        elif ins.name == 'tempo':
            f.tempos.append((tick, ins.args[0]))
        elif ins.name == 'jump':
            nxt = ins.target
            taken = True
        elif ins.name == 'loop_exit':
            n, c = ins.args[0], ins.args[1]
            f.max_loop_index = max(f.max_loop_index, n)
            if cnt.get(n, 0) == 0:
                cnt[n] = c
            else:
                cnt[n] = (cnt[n] - 1) & 0xFF
                if cnt[n] == 0:
                    nxt = ins.target
                    taken = True
        elif ins.name == 'loop_back':
            n, c = ins.args[0], ins.args[1]
            f.max_loop_index = max(f.max_loop_index, n)
            if cnt.get(n, 0) == 0:
                cnt[n] = c
                nxt = ins.target
                taken = True
            else:
                cnt[n] = (cnt[n] - 1) & 0xFF
                if cnt[n] != 0:
                    nxt = ins.target
                    taken = True
        if taken and nxt <= pos:
            key = (nxt, tuple(sorted((k, v) for k, v in cnt.items() if v)))
            if key in seen:
                t0, ntemp = seen[key]
                if tick == t0:
                    f.stuck = True
                    break
                f.loop_start, f.loop_len = t0, tick - t0
                f.tempos_in_loop = f.tempos[ntemp:]
                f.tempos = f.tempos[:ntemp] + f.tempos_in_loop
                break
            seen[key] = (tick, len(f.tempos))
        pos = nxt
    f.total = tick
    return f


def song_timing(song):
    """Song-level lengths.  ticks = length of one complete pass: for an ending song the tick
    count of the longest track, for a looping one intro + one loop, where loop = lcm of the
    looping tracks' loop lengths and intro = latest loop start.  Seconds integrate the tempo
    commands (a tempo command executed in tick n changes the tick length from the interval
    n+2 -> n+3 on, see usd-driver.md); before the first one the song's first tempo is assumed."""
    flows = [flow(song, i) for i in range(len(song.tracks))]
    looping = [f for f in flows if f.loop_len]
    ended = [f for f in flows if f.ended]
    res = {'flows': flows}
    if looping:
        loop = 1
        for f in looping:
            loop = loop * f.loop_len // math.gcd(loop, f.loop_len)
        intro = max(f.loop_start for f in looping)
        if ended:
            intro = max(intro, max(f.total for f in ended))
        res.update(loops=True, intro=intro, loop=loop, ticks=intro + loop)
    else:
        res.update(loops=False, intro=max(f.total for f in flows), loop=0,
                   ticks=max(f.total for f in flows))
    # tempo map: (tick, word), expanded over the horizon
    horizon = res['ticks']
    ev = []
    for f in flows:
        if f.loop_len:
            pre = [(t, w) for t, w in f.tempos if t < f.loop_start]
            inl = [(t, w) for t, w in f.tempos if t >= f.loop_start]
            ev += pre
            k = 0
            while inl and f.loop_start + k * f.loop_len < horizon:
                ev += [(t + k * f.loop_len, w) for t, w in inl]
                k += 1
        else:
            ev += f.tempos
    ev = sorted(set(e for e in ev if e[0] < horizon))
    res['tempo_events'] = ev
    words = [w for t, w in ev]
    res['tempos'] = sorted(set(words), key=words.index)
    first = words[0] if words else 0x0347        # 0347h: what the built-in init sequence leaves

    def seconds(t0, t1):
        # interval k (from tick row k to k+1) uses the last tempo executed at a row <= k-2
        total = 0.0
        cur = first
        i = 0
        k = 0
        while k < t1:
            while i < len(ev) and ev[i][0] <= k - 2:
                cur = ev[i][1]
                i += 1
            nxt = min(t1, (ev[i][0] + 2) if i < len(ev) else t1)
            if nxt <= k:
                nxt = k + 1
            a, b = max(k, t0), nxt
            if b > a:
                total += (b - a) * tick_seconds(cur)
            k = nxt
        return total
    res['seconds'] = seconds(0, res['ticks'])
    res['loop_seconds'] = seconds(res['intro'], res['ticks']) if res['loops'] else 0.0
    res['first_tempo'] = first
    return res


# ---------------------------------------------------------------- checks
def check(song):
    """returns (list of problems, coverage description)"""
    probs = []
    d = song.data
    cov = bytearray(len(d))

    def mark(a, b):
        for i in range(a, b):
            cov[i] += 1
    mark(0, 6 + 10 * song.ntracks)
    for typ, o, ln in song.blocks:
        mark(o - 4, o + ln)
        size = FM_VOICE_SIZE if typ == 0 else SSG_VOICE_SIZE
        if ln % size:
            probs.append('block type %d length %d is not a multiple of %d' % (typ, ln, size))
    mark(song.lenword_off, song.base)
    if song.datalen != len(d) - song.base:
        probs.append('data length word %d != %d bytes after it' % (song.datalen, len(d) - song.base))
    chans = [t.channel for t in song.tracks]
    if len(set(chans)) != len(chans):
        probs.append('channel used twice')
    done = set()
    for t in song.tracks:
        if t.channel > 5:
            probs.append('track %d: channel %d' % (t.index, t.channel))
        if t.start >= len(d):
            probs.append('track %d starts outside the file' % t.index)
            continue
        if t.start in done:
            probs.append('track %d shares its start with another track' % t.index)
            continue
        done.add(t.start)
        q = t.start
        for ins in t.ins:
            mark(ins.off, ins.off + ins.size)
            q = ins.off + ins.size
            if ins.target is not None and ins.target not in t.by_off:
                probs.append('track %d: %s at %04X targets %04X (not an instruction of this track)'
                             % (t.index, ins.name, ins.off, ins.target))
            if ins.name == 'nop':
                probs.append('track %d: undefined command %02X at %04X' % (t.index, ins.op, ins.off))
            if ins.name == 'fm_voice' and (t.kind != 'FM' or ins.args[0] >= len(song.fm_voices)):
                probs.append('track %d: fm_voice %d at %04X invalid' % (t.index, ins.args[0], ins.off))
            if ins.name == 'ssg_voice' and (t.kind != 'SSG' or ins.args[0] >= len(song.ssg_voices)):
                probs.append('track %d: ssg_voice %d at %04X invalid' % (t.index, ins.args[0], ins.off))
            if ins.name in ('loop_exit', 'loop_back') and ins.args[0] > 3:
                probs.append('track %d: loop counter index %d at %04X (only 0..3 are cleared at start)'
                             % (t.index, ins.args[0], ins.off))
            if ins.name == 'gate' and (ins.args[0] & ~0x0E):
                probs.append('track %d: gate operand %02X at %04X has bits outside 0Eh'
                             % (t.index, ins.args[0], ins.off))
        if q != t.end:
            probs.append('track %d: decoding stops at %04X, region ends at %04X' % (t.index, q, t.end))
        if not t.ins or t.ins[-1].name != 'end':
            probs.append('track %d: region does not end with FF' % t.index)
        try:
            f = flow(song, t.index)
            if f.stuck:
                probs.append('track %d: loop without duration' % t.index)
            if not f.ended and not f.loop_len:
                probs.append('track %d: neither ends nor loops' % t.index)
        except FormatError as e:
            probs.append(str(e))
    holes = sum(1 for c in cov if c == 0)
    multi = sum(1 for c in cov if c > 1)
    if holes:
        probs.append('%d bytes not accounted for' % holes)
    if multi:
        probs.append('%d bytes accounted for more than once' % multi)
    return probs, (len(d), holes, multi)


# ---------------------------------------------------------------- dump
def fm_voice_lines(v):
    r = lambda k: ' '.join('%02X' % x for x in v[k:k + 4])
    alg, fb = v[24] & 7, (v[24] >> 3) & 7
    out = ['      slot order S1 S3 S2 S4 (registers +0 +4 +8 +C)',
           '      30h DT/MUL  %s' % r(0),
           '      40h TL      %s' % r(4),
           '      50h KS/AR   %s' % r(8),
           '      60h AM/DR   %s' % r(12),
           '      70h SR      %s' % r(16),
           '      80h SL/RR   %s' % r(20),
           '      B0h FB/ALG  %02X  (FB %d, ALG %d)' % (v[24], fb, alg),
           '      volume mask %02X  (slots %s receive the track volume)' % (
               v[25], ','.join(('S1', 'S3', 'S2', 'S4')[i] for i in range(4) if v[25] >> i & 1) or '-'),
           '      key-on mask %02X  (reg 28h = (mask & F0h) | channel)' % v[26]]
    for nm, o in (('pitch LFO', 27), ('volume LFO', 33)):
        out.append('      %-10s  %s' % (nm, lfo_text(v[o:o + 6])))
    return out


LFO_SHAPES = ['ramp', 'sawtooth', 'zigzag', 'square']


def lfo_text(b):
    typ, delay, speed, count, step = b[0], b[1], b[2], b[3], s16(b[4] | (b[5] << 8))
    if typ == 0:
        s = 'off'
        if any(b[1:]):
            s += '  (other bytes %s)' % ' '.join('%02X' % x for x in b[1:])
        return s
    return 'type %02X = %s, delay %d, speed %d, count %d, step %d' % (
        typ, LFO_SHAPES[(typ >> 1) & 3], delay, speed, count, step)


def ssg_voice_lines(v):
    out = ['      mixer %02X (%s%s)  noise period %02X' % (
        v[0], 'tone' if v[0] & 1 else '', ('+' if v[0] & 1 else '') + 'noise' if v[0] & 8 else '', v[1]),
        '      envelope: attack +%d/step to %d, decay -%d/step to %d, sustain -%d/step, release -%d/step' % (
            v[4], v[2], v[5], v[3], v[6], v[7]),
        '      bytes 8..11 %s (not read by the driver)' % ' '.join('%02X' % x for x in v[8:12])]
    for nm, o in (('pitch LFO', 12), ('volume LFO', 18), ('noise LFO', 24)):
        out.append('      %-10s  %s' % (nm, lfo_text(v[o:o + 6])))
    return out


def ins_text(ins, tr, transpose):
    if ins.name == 'note':
        n = ins.note + transpose if transpose is not None else None
        lt = ('l%d' % ins.length) if ins.op >= 0xB0 else 'L%X=%d' % (ins.op >> 4, ins.length)
        if n is None:
            return 'note  %-8s n%d' % (lt, ins.note)
        if tr.kind == 'FM':
            cl = min(max(n, 0), 0x5F)
        else:
            cl = min(max(n, 0x0C), 0x6B)
        return 'note  %-8s %-4s (%d+%d=%d%s)' % (lt, note_name(cl), ins.note, transpose, n,
                                                 '' if cl == n else ', clamped')
    if ins.name == 'rest':
        return 'rest  %s' % (('l%d' % ins.length) if ins.op >= 0xB0 else 'L%X=%d' % (ins.op >> 4, ins.length))
    a = ins.args
    if ins.name == 'tempo':
        return 'tempo %04X  (NA=%d, tick %.3f ms, quarter = %.1f bpm)' % (
            a[0], timer_a_value(a[0]), tick_seconds(a[0]) * 1000, 60.0 / (48 * tick_seconds(a[0])))
    if ins.name == 'gate':
        return 'gate  %02X  (%s)' % (a[0], GATE_NAMES[(a[0] >> 1) & 7])
    if ins.name == 'jump':
        return 'jump  -> %04X' % ins.target
    if ins.name == 'loop_exit':
        return 'loop_exit  counter %d, %d, -> %04X   (pass %d of the loop jumps)' % (a[0], a[1], ins.target, a[1] + 1)
    if ins.name == 'loop_back':
        return 'loop_back  counter %d, %d, -> %04X   (%s)' % (
            a[0], a[1], ins.target, 'forever' if a[1] == 0 else '%d passes in all' % (a[1] + 1))
    if ins.name == 'nop':
        return 'nop   (undefined command %02X)' % ins.op
    return '%s %s' % (ins.name, ' '.join(str(x) for x in a))


def dump(song, out=sys.stdout):
    d = song.data
    w = lambda s='': print(s, file=out)
    w('== %s  (%d bytes)' % (song.name, song.size))
    w('header: owner/clock word %d, tracks %d, blocks %d' % (song.owner, song.ntracks, song.nblocks))
    for t in song.tracks:
        w('  track %d: channel %d (%s)  priority %d  data +%04X = file %04X..%04X   load-time fields %s'
          % (t.index, t.channel, t.chname, t.priority, t.rel, t.start, t.end,
             ' '.join('%02X' % x for x in t.garbage)))
    for typ, o, ln in song.blocks:
        w('block at %04X: type %d (%s), %d bytes' % (o - 4, typ, 'FM voices' if typ == 0 else 'SSG voices', ln))
        size = FM_VOICE_SIZE if typ == 0 else SSG_VOICE_SIZE
        for k in range(ln // size):
            v = d[o + k * size:o + (k + 1) * size]
            w('   %s voice %d at %04X' % ('FM' if typ == 0 else 'SSG', k, o + k * size))
            for line in (fm_voice_lines(v) if typ == 0 else ssg_voice_lines(v)):
                w(line)
    w('track data: length word %d at %04X, base %04X' % (song.datalen, song.lenword_off, song.base))
    tm = song_timing(song)
    for t in song.tracks:
        f = tm['flows'][t.index]
        if f.ended:
            st = 'ends after %d ticks' % f.total
        elif f.loop_len:
            st = 'loops: %d ticks, then %d ticks repeated' % (f.loop_start, f.loop_len)
        else:
            st = 'stuck' if f.stuck else '?'
        w()
        w('-- track %d  %s  %04X..%04X  %s, %d note events per pass' % (t.index, t.chname, t.start, t.end, st, f.notes))
        targets = set(i.target for i in t.ins if i.target is not None)
        tr = None
        for ins in t.ins:
            if ins.name == 'transpose':
                tr = ins.args[0]
            raw = ' '.join('%02X' % x for x in d[ins.off:ins.off + ins.size])
            w('%s%04X  %-17s %s' % ('>' if ins.off in targets else ' ', ins.off, raw, ins_text(ins, t, tr)))
    w()
    if tm['loops']:
        w('song: intro %d ticks + loop %d ticks; one pass %.2f s, loop %.2f s; tempo words %s' % (
            tm['intro'], tm['loop'], tm['seconds'], tm['loop_seconds'],
            ' '.join('%04X' % x for x in tm['tempos'])))
    else:
        w('song: ends after %d ticks = %.2f s; tempo words %s' % (
            tm['ticks'], tm['seconds'], ' '.join('%04X' % x for x in tm['tempos'])))


def tsv_row(song):
    tm = song_timing(song)
    probs, cov = check(song)
    ch = ''.join(str(t.channel) for t in song.tracks)
    return [song.name, str(song.size), str(song.ntracks), ch,
            str(len(song.fm_voices)), str(len(song.ssg_voices)),
            ' '.join('%04X' % x for x in tm['tempos']),
            '%.3f' % (tick_seconds(tm['first_tempo']) * 1000),
            str(tm['ticks']), str(tm['intro']), str(tm['loop']),
            '%.2f' % tm['seconds'], '%.2f' % tm['loop_seconds'],
            'loop' if tm['loops'] else 'end', 'ok' if not probs else '; '.join(probs)]


TSV_HEAD = ['file', 'bytes', 'tracks', 'channels', 'fm_voices', 'ssg_voices', 'tempo_words',
            'tick_ms', 'ticks', 'intro_ticks', 'loop_ticks', 'seconds', 'loop_seconds', 'kind', 'check']


def stats(songs, out=sys.stdout):
    import collections
    cnt = collections.Counter()
    files = collections.defaultdict(set)
    vals = collections.defaultdict(collections.Counter)
    for s in songs:
        for t in s.tracks:
            for ins in t.ins:
                if ins.name in ('note', 'rest'):
                    key = '%s %s' % (ins.name, 'explicit length (Bx)' if ins.op >= 0xB0 else 'table length')
                else:
                    key = '%02X %s' % (ins.op, ins.name)
                cnt[key] += 1
                files[key].add(s.name)
                if ins.name in ('gate', 'porta', 'detune'):
                    vals[key][ins.args[0]] += 1
                if ins.name in ('loop_exit', 'loop_back'):
                    vals[key]['counter %d' % ins.args[0]] += 1
                if ins.name in ('note', 'rest') and ins.op < 0xB0:
                    vals['length index'][ins.op >> 4] += 1
    print('command\tcount\tfiles\tvalues', file=out)
    for k in sorted(cnt):
        v = ', '.join('%s:%d' % (a, b) for a, b in sorted(vals[k].items(), key=lambda x: str(x[0])))
        print('%s\t%d\t%d\t%s' % (k, cnt[k], len(files[k]), v), file=out)
    print('length index\t\t\t%s' % ', '.join('%X:%d' % (a, b) for a, b in sorted(vals['length index'].items())), file=out)


def load(path):
    with open(path, 'rb') as f:
        return parse(f.read(), os.path.basename(path))


def all_files():
    return [os.path.join(MUSDIR, f) for f in sorted(os.listdir(MUSDIR)) if f.upper().endswith('.USO')]


def write_index(path, files):
    """our own per-song table (no game data: only counts and durations)"""
    with open(path, 'w') as f:
        f.write('# NOVA music/effect files (.USO): generated by re-tools/usoinfo.py --index\n')
        f.write('# ticks = one complete pass (intro + one loop); seconds at the song\'s own tempo\n')
        f.write('name\ttracks\tchannels\tkind\tticks\tintro_ticks\tloop_ticks\ttick_ms\tseconds\tloop_seconds\n')
        for p in files:
            s = load(p)
            tm = song_timing(s)
            f.write('\t'.join([os.path.splitext(s.name)[0], str(s.ntracks),
                               '+'.join(t.chname for t in s.tracks),
                               'loop' if tm['loops'] else 'once', str(tm['ticks']), str(tm['intro']),
                               str(tm['loop']), '%.3f' % (tick_seconds(tm['first_tempo']) * 1000),
                               '%.2f' % tm['seconds'], '%.2f' % tm['loop_seconds']]) + '\n')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('files', nargs='*')
    ap.add_argument('--tsv', action='store_true')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--stats', action='store_true')
    ap.add_argument('--index')
    a = ap.parse_args()
    files = a.files or (all_files() if (a.tsv or a.check or a.stats or a.index) else [])
    if not files:
        ap.error('no files')
    if a.index:
        write_index(a.index, files)
        return 0
    if a.stats:
        stats([load(p) for p in files])
        return 0
    if a.tsv:
        print('\t'.join(TSV_HEAD))
        for p in files:
            print('\t'.join(tsv_row(load(p))))
        return 0
    if a.check:
        bad = 0
        total = 0
        for p in files:
            try:
                s = load(p)
                probs, (n, holes, multi) = check(s)
            except FormatError as e:
                probs, n, holes = [str(e)], 0, 0
            total += n
            bad += bool(probs)
            print('%-12s %5d bytes  %s' % (os.path.basename(p), n,
                                          'all accounted for' if not probs else 'PROBLEMS: ' + '; '.join(probs)))
        print('%d files, %d bytes, %d with problems' % (len(files), total, bad))
        return 1 if bad else 0
    for p in files:
        dump(load(p))
    return 0


if __name__ == '__main__':
    sys.exit(main())
