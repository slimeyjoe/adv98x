#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""usdmodel.py - clean-room Python model of NOVA's music driver (USDdrv / USDtrap V01.02:
the .USO sequencer for the YM2203), written from docs/re/usd-driver.md and
docs/re/usd-sequencer.md - not from the disassembly.  It produces the same stream of OPN
register writes, clock for clock, as the original driver run by usdemu.py.

    usdmodel.py SONG.USO [-o out.vgm] [--log out.tsv] [--loops N] [--seconds S]
    usdmodel.py --check [FILE ...] [--loops N] [--cap S] [--synth N] [--seed N] [-v]
        compare the model with the emulated original (default: all 28 files):
        scenario "play"      = sound "file" / sound 1, intro + N loop passes (default 3),
                               capped at --cap seconds of song time (default 420)
        scenario "fade"      = fade-in start, fade-out, stop, restarts with volume offsets,
                               raw fades, a restart over the playing song
        scenario "chain"     = every file started after the previous one on one driver
                               instance (state a track inherits from the last song)
        scenario "phase"     = four files at different phases of the two timers
        scenario "synthetic" = --synth generated songs (default 400; our own data) that use
                               what NOVA's files do not: loop-exit, all gate modes and LFO
                               shapes, odd values, priorities, timer-B clocked tracks,
                               effect banks, stop-by-priority, fades with a threshold
        --synth-only runs only the last one.  Exit status 1 if anything differs.
    (--check needs unicorn: docs/re/README.md "Tools")

Model API (what an engine needs):
    m = Model()                    state right after AdvBIOS start-up
    m.load(bytes); m.play(); m.fade_in(); m.fade_out(); m.stop(); m.volume(n); m.fade(p, s, f)
    m.load_bank(bytes); m.play_se(i); m.stop_owner(n); m.set_enable(mask)     (unused by NOVA)
    m.run(seconds=...) / m.run(aticks=...)       advance the two OPN timers
    m.writes -> [(clock, reg, val)]              clock in 1/3993600 s
The sequencer itself (Sequencer) does not know about time: Sequencer.interrupt(flags)
is called with bit 0 = timer A (note clock), bit 1 = timer B (effect clock) and writes
registers through a callback.  Model adds the two timers and the INT F4h entry points.
"""
import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MUSDIR = os.path.join(ROOT, 'resources', 'original', 'pc98', 'A', 'MUS')

CLOCK = 3993600

# ---- tables (usd-sequencer.md section 5) -------------------------------------------------
LENGTHS = (192, 144, 96, 72, 48, 36, 24, 18, 12, 9, 6)
# pitch of the 12 semitones inside an octave, in units of 1/618 of the F-number of C
SEMITONE_PITCH = (0, 37, 76, 117, 161, 207, 256, 308, 363, 422, 484, 549)
OCTAVE_PITCH = 618
# SSG tone periods of the lowest octave (note numbers 12..23); every higher octave is the
# stored table, which is NOT an exact halving - so the whole table is kept
SSG_PERIOD = (
    3816, 3602, 3400, 3209, 3029, 2859, 2698, 2547, 2404, 2269, 2142, 2022,
    1908, 1801, 1700, 1604, 1514, 1429, 1349, 1273, 1202, 1135, 1071, 1011,
    954, 900, 850, 802, 757, 715, 675, 637, 601, 567, 535, 505,
    477, 450, 425, 401, 379, 357, 337, 318, 301, 284, 268, 253,
    239, 225, 212, 201, 189, 179, 169, 159, 150, 142, 134, 126,
    119, 113, 106, 100, 95, 89, 84, 80, 75, 71, 67, 63,
    60, 56, 53, 50, 47, 45, 42, 40, 38, 35, 33, 32,
    30, 28, 27, 25, 24, 22, 21, 20, 19, 18, 17, 16)

FM_VOICE_SIZE, SSG_VOICE_SIZE = 39, 30
VOL_SILENT = -1024          # volume used to mute an FM channel when its track ends
MASTER_MIN = -64


def s8(v):
    v &= 0xFF
    return v - 256 if v & 0x80 else v


def s16(v):
    v &= 0xFFFF
    return v - 65536 if v & 0x8000 else v


def u16(b, o):
    return b[o] | (b[o + 1] << 8)


def fm_pitch(note):
    """pitch value of FM note number 0..95"""
    return OCTAVE_PITCH * (note // 12) + SEMITONE_PITCH[note % 12]


def fm_fnum(pitch):
    """pitch value -> (register A4h value, register A0h value)"""
    pitch = min(max(pitch, 0), 0x134F)
    block, f = divmod(pitch, OCTAVE_PITCH)
    f += OCTAVE_PITCH
    return (block << 3) | (f >> 8), f & 0xFF


def gate_threshold(mode, length):
    """remaining-tick count below which a note is released (0 = never before its end)"""
    q = (mode >> 1) & 7
    if q == 0:
        return 0
    if q == 1:
        return length - (length >> 3)
    if q == 2:
        return length - (length >> 2)
    if q == 3:
        return (length >> 1) + (length >> 3)
    if q == 4:
        return length >> 1
    if q == 5:
        return (length >> 2) + (length >> 3)
    if q == 6:
        return length >> 2
    return length >> 3


# ---- low-frequency modulators ------------------------------------------------------------
class Lfo:
    """One of the driver's five modulators.  kind: 'pitch' (FM and SSG), 'fmvol', 'ssgvol',
    'noise'.  The six parameter bytes come from the voice record.  step() is called once per
    timer-B interrupt while the modulator is enabled and returns the value to send to the
    chip (an offset for 'pitch' and 'noise', the complete volume for 'fmvol') or None."""

    def __init__(self, kind):
        self.kind = kind
        self.type = self.delay = self.speed = self.count = self.depth = 0
        self.phase = 0          # 0 = not started since the last note-on, else 1 / 2
        self.wait = 0           # remaining delay
        self.speed_ctr = 0
        self.count_ctr = 0
        self.acc = 0

    def configure(self, rec):
        self.type, self.delay, self.speed, self.count = rec[0], rec[1], rec[2], rec[3]
        self.depth = s16(u16(rec, 4))

    def restart(self):
        self.phase = 0
        self.wait = self.delay

    def _speed_elapsed(self):
        self.speed_ctr = (self.speed_ctr - 1) & 0xFF
        return self.speed_ctr == 0

    def _count_elapsed(self):
        self.count_ctr = (self.count_ctr - 1) & 0xFF
        return self.count_ctr == 0

    def step(self, base=0):
        """base: the track volume for 'fmvol' (start value of the accumulator), else unused"""
        if self.wait:
            self.wait -= 1
            return None
        shape = (self.type >> 1) & 3
        home = base if self.kind == 'fmvol' else 0
        if shape == 3:                                  # square
            if self.phase != 0:
                if not self._speed_elapsed():
                    return None
            if self.phase == 1:
                self.phase = 2
                out = home
                if self.kind == 'ssgvol':
                    self.acc = 0
            else:
                self.phase = 1
                out = s16(home + self.depth)
                if self.kind == 'ssgvol':
                    self.acc = self.depth
            self.speed_ctr, self.count_ctr = self.speed, self.count
            return out
        if self.phase == 0:
            self.phase = 1
            self.speed_ctr = self.speed
            self.acc = home
            if shape == 1:
                self.count_ctr = self.count
            elif shape == 2:
                self.count_ctr = (self.count >> 1) or 1
        if not self._speed_elapsed():
            return None
        self.speed_ctr = self.speed
        if shape == 2 and self.kind != 'pitch':
            self.acc = s16(self.acc + (self.depth if self.phase == 1 else -self.depth))
            out = self.acc
        else:
            self.acc = s16(self.acc + self.depth)
            out = self.acc
            if shape == 2 and self.phase == 2:          # 'pitch': mirrored, not reversed
                out = s16(-self.acc)
        if shape and self._count_elapsed():
            self.count_ctr = self.count
            if shape == 1:
                self.acc = home
            else:
                if self.kind in ('pitch', 'noise'):
                    self.acc = 0
                self.phase ^= 3
        return out


# ---- channels ----------------------------------------------------------------------------
class Channel:
    """state and behaviour common to FM and SSG channels (usd-sequencer.md section 3)"""
    is_fm = False

    def __init__(self, seq, number):
        self.seq = seq
        self.number = number        # 0..2 inside its kind
        self.owner = 0              # 0 = idle; else bit 0: clocked by timer A, bit 1: by B
        self.priority = 0
        self.keyed = False          # note sounding (flag bit 0)
        self.porta = False          # bit 1
        self.tie = False            # bit 4 (also: already released by the gate)
        self.note = 0
        self.gate_mode = 0
        self.transpose = 0
        self.detune = 0
        self.porta_step = 0
        self.volume = 0
        self.counter = 0
        self.gate = 0
        self.pitch = 0
        self.target = 0
        self.data = b''
        self.pos = 0
        self.voices = b''
        self.loops = [0, 0, 0, 0]
        self.pitch_lfo = Lfo('pitch')
        self.pitch_lfo_on = False
        self.vol_lfo_on = False

    def out(self, reg, val):
        self.seq.write(reg & 0xFF, val & 0xFF)

    # -- starting / ending a track
    def start(self, owner, priority, data, pos, voices):
        self.priority = priority
        self.data, self.pos, self.voices = data, pos, voices
        self.counter = 1
        self.keyed = self.porta = self.tie = False
        self.pitch_lfo_on = self.vol_lfo_on = False
        self.clear_extra_flags()
        self.detune = 0
        self.loops = [0, 0, 0, 0]
        self.owner = owner & 0xFF

    def clear_extra_flags(self):
        pass

    def end(self):
        """end-of-track command, also used to stop a channel"""
        self.silence()
        self.keyed = self.porta = self.tie = False
        self.pitch_lfo_on = self.vol_lfo_on = False
        self.clear_extra_flags()
        self.owner = 0
        self.target = 0

    # -- note clock
    def clock(self):
        self.counter = (self.counter - 1) & 0xFFFF
        if self.counter:
            if self.tie or self.porta or not self.keyed or self.counter >= self.gate:
                return
            self.release()
            self.keyed = False
            self.tie = True             # "released already": no second release at the end
            return
        if self.keyed and not (self.tie or self.porta):
            self.release()
        self.keyed = False
        self.tie = False
        self.counter = 1
        self.row()

    def fetch(self):
        b = self.data[self.pos]
        self.pos = (self.pos + 1) & 0xFFFF
        return b

    def fetch16(self):
        lo = self.fetch()
        return lo | (self.fetch() << 8)

    def row(self):
        """execute commands up to and including the next note or rest"""
        while True:
            b = self.fetch()
            if b < 0xC0:
                if b < 0xB0:
                    length = LENGTHS[b >> 4]
                else:
                    length = self.fetch()
                    if length & 0x80:
                        length = ((length << 8) | self.fetch()) & 0x7FFF
                if b & 15:
                    self.note_on(b & 15, length)
                else:
                    self.rest()
                    self.counter = length
                return
            if b == 0xFF:
                self.end()
                return
            if b == 0xFE:
                self.transpose = self.fetch()
            elif b == 0xFD:
                self.volume = s8(self.fetch())
            elif b == 0xFC:
                self.detune = s8(self.fetch())
            elif b == 0xFB:
                self.seq.set_tempo(self.fetch16(), self.owner)
            elif b == 0xF8:
                self.gate_mode = self.fetch()
            elif b == 0xF7:
                self.tie = True
            elif b == 0xF6:
                v = self.fetch()
                if v:
                    self.porta_step = v
                    self.target = 0
                    self.porta = True
                else:
                    self.porta = False
            elif b == 0xF5:
                self.jump()
            elif b == 0xF4:                     # leave the loop on the last pass
                n, c = self.fetch(), self.fetch()
                if self.loops[n] == 0:
                    self.loops[n] = c
                    self.pos = (self.pos + 2) & 0xFFFF
                else:
                    self.loops[n] -= 1
                    if self.loops[n]:
                        self.pos = (self.pos + 2) & 0xFFFF
                    else:
                        self.jump()
            elif b == 0xF3:                     # repeat
                n, c = self.fetch(), self.fetch()
                if self.loops[n] == 0:
                    self.loops[n] = c
                    self.jump()
                else:
                    self.loops[n] -= 1
                    if self.loops[n]:
                        self.jump()
                    else:
                        self.pos = (self.pos + 2) & 0xFFFF
            elif b == 0xE1:
                self.seq.fm_voice(self, self.fetch())
            elif b == 0xE0:
                self.seq.ssg_voice(self, self.fetch())
            # every other byte C0..FF: no operation, no operand

    def jump(self):
        d = self.fetch16()
        self.pos = (self.pos + d) & 0xFFFF

    def note_on(self, nibble, length):
        n = s8(nibble + self.transpose)
        self.note = n
        new = self.note_pitch(n)
        self.counter = length
        self.gate = gate_threshold(self.gate_mode, length)
        new = s16(new + self.detune)
        if self.porta:
            if self.target == 0:
                self.pitch = new
            self.target = new
        else:
            self.pitch = new
        self.strike()

    def slide(self):
        """portamento: move pitch towards target by porta_step (unsigned comparison)"""
        cur, tgt = self.pitch & 0xFFFF, self.target & 0xFFFF
        if cur > tgt:
            cur = (cur - self.porta_step) & 0xFFFF
            if cur < tgt:
                cur = tgt
        elif cur < tgt:
            cur = (cur + self.porta_step) & 0xFFFF
            if cur > tgt:
                cur = tgt
        self.pitch = s16(cur)

    def effects_pitch(self):
        """timer-B work on the pitch: portamento and pitch modulator"""
        if self.porta:
            self.slide()
            if not self.pitch_lfo_on:
                self.write_pitch(self.pitch)
        if self.pitch_lfo_on:
            off = self.pitch_lfo.step()
            if off is not None:
                self.write_pitch(s16(self.pitch + off))


class FmChannel(Channel):
    is_fm = True

    def __init__(self, seq, number):
        super().__init__(seq, number)
        self.voice = bytes(FM_VOICE_SIZE)
        self.vol_lfo = Lfo('fmvol')

    def note_pitch(self, n):
        return fm_pitch(min(max(n, 0), 0x5F))

    def write_pitch(self, pitch):
        hi, lo = fm_fnum(pitch)
        self.out(0xA4 + self.number, hi)
        self.out(0xA0 + self.number, lo)

    def write_levels(self, volume):
        """total level of the slots selected by the voice's volume mask"""
        if self.priority >= self.seq.fade_priority:
            volume += self.seq.master
        for slot in range(4):
            if self.voice[25] >> slot & 1:
                tl = s8(self.voice[4 + slot]) - volume
                self.out(0x40 + self.number + 4 * slot, min(max(tl, 0), 0x7F))

    def key_off(self):
        self.out(0x28, self.number)

    def release(self):
        self.key_off()

    def silence(self):
        self.key_off()
        self.write_levels(VOL_SILENT)

    def rest(self):
        self.key_off()
        self.keyed = False

    def strike(self):
        self.write_pitch(self.pitch)
        if self.pitch_lfo_on:
            self.pitch_lfo.restart()
        if self.vol_lfo_on:
            self.vol_lfo.restart()
        if self.keyed:
            self.key_off()
        self.write_levels(self.volume)
        self.out(0x28, (self.voice[26] & 0xF0) | self.number)
        self.keyed = True

    def load_voice(self, rec):
        self.voice = bytes(rec)
        for i in range(24):
            self.out(0x30 + self.number + 4 * i, rec[i])
        for i in range(4):
            self.out(0x90 + self.number + 4 * i, 0)
        self.out(0xB0 + self.number, rec[24])
        self.pitch_lfo.configure(rec[27:33])
        self.vol_lfo.configure(rec[33:39])
        self.pitch_lfo_on = rec[27] != 0
        self.vol_lfo_on = rec[33] != 0

    def effects(self):
        self.effects_pitch()
        if self.vol_lfo_on:
            v = self.vol_lfo.step(self.volume)
            if v is not None:
                self.write_levels(v)


class SsgChannel(Channel):
    ENV_ATTACK, ENV_DECAY, ENV_SUSTAIN, ENV_RELEASE, ENV_OFF = range(5)

    def __init__(self, seq, number):
        super().__init__(seq, number)
        self.voice = bytes(SSG_VOICE_SIZE)
        self.mixer = 0                  # mixer bits the voice opens; none until a voice is loaded
        self.vol_lfo = Lfo('ssgvol')
        self.noise_lfo = Lfo('noise')
        self.noise_lfo_on = False
        self.env_state = 0
        self.env_level = 0

    def clear_extra_flags(self):
        self.noise_lfo_on = False

    def note_pitch(self, n):
        return SSG_PERIOD[min(max(n, 0x0C), 0x6B) - 0x0C]

    def write_pitch(self, period, clamp=True):
        if clamp:
            period = min(max(period, 0), 0x0FFF)
        self.out(2 * self.number, period)
        self.out(2 * self.number + 1, period >> 8)

    def key_off(self):
        self.seq.mixer |= self.mixer
        self.out(0x07, self.seq.mixer)
        self.keyed = False
        self.out(0x08 + self.number, 0)

    def release(self):
        self.env_state = self.ENV_RELEASE

    def silence(self):
        self.key_off()

    def rest(self):
        self.key_off()

    def strike(self):
        self.write_pitch(self.pitch, clamp=False)
        if self.pitch_lfo_on:
            self.pitch_lfo.restart()
        if self.vol_lfo_on:
            self.vol_lfo.restart()
        if self.noise_lfo_on:
            self.noise_lfo.restart()
        if self.keyed:
            self.key_off()
        self.vol_lfo.acc = 0
        self.env_level = 0
        self.env_state = self.ENV_ATTACK
        self.envelope()
        self.seq.mixer = (self.seq.mixer | (0x09 << self.number)) & ~self.mixer & 0xFF
        self.out(0x07, self.seq.mixer)
        self.keyed = True

    def load_voice(self, rec):
        self.voice = bytes(rec)
        self.pitch_lfo.configure(rec[12:18])
        self.vol_lfo.configure(rec[18:24])
        self.noise_lfo.configure(rec[24:30])
        self.pitch_lfo_on = self.vol_lfo_on = self.noise_lfo_on = False
        if rec[0] & 8:
            self.out(0x06, rec[1])
            self.noise_lfo_on = rec[24] != 0
        self.pitch_lfo_on = rec[12] != 0
        self.vol_lfo_on = rec[18] != 0
        self.mixer = (rec[0] << self.number) & 0xFF

    def envelope(self):
        """one step of the software envelope, then the volume register"""
        v = self.voice
        st = self.env_state
        if st == self.ENV_ATTACK:
            self.env_level += v[4]
            if self.env_level >= v[2]:
                self.env_level = v[2]
                self.env_state = self.ENV_DECAY
        elif st == self.ENV_DECAY:
            self.env_level -= v[5]
            if self.env_level <= v[3]:
                self.env_state = self.ENV_SUSTAIN
        elif st in (self.ENV_SUSTAIN, self.ENV_RELEASE):
            self.env_level -= v[6] if st == self.ENV_SUSTAIN else v[7]
            if self.env_level <= 0:
                self.env_state = self.ENV_OFF
                self.env_level = 0
                self.key_off()
        level = 0 if st == self.ENV_OFF else self.env_level
        if self.priority >= self.seq.fade_priority:
            level += 2 * self.seq.master
        level += self.volume + self.vol_lfo.acc
        self.out(0x08 + self.number, min(max(level >> 4, 0), 15))

    def write_noise(self, off):
        n = s16((off >> 4) + self.voice[1])
        self.out(0x06, min(max(n, 0), 0x1F))

    def effects(self):
        self.effects_pitch()
        if self.vol_lfo_on:
            self.vol_lfo.step()
        if self.noise_lfo_on:
            n = self.noise_lfo.step()
            if n is not None:
                self.write_noise(n)
        self.envelope()


# ---- the sequencer -----------------------------------------------------------------------
class Sequencer:
    """the six channels, the master volume / fade state and the interrupt routine"""

    def __init__(self, write):
        self.write = write
        self.channels = [FmChannel(self, i) for i in range(3)] + [SsgChannel(self, i) for i in range(3)]
        self.mixer = 0xBF               # shadow of SSG register 07h
        self.master = 0                 # volume offset, 0 (full) .. -64
        self.fade_period = 0
        self.fade_count = 0
        self.fade_step = 0
        self.fade_priority = 0
        self.tempo_request = None       # timer-A word waiting for the next interrupt

    # -- services
    def start(self, owner, tracks):
        """tracks: [(channel 0..5, priority, data, position, voice table)]"""
        tracks = tracks[:6]
        for ch, prio, *_ in tracks:
            c = self.channels[ch]
            if prio and c.owner and prio < c.priority:
                return False
        for ch, *_ in tracks:
            if self.channels[ch].owner:
                self.channels[ch].end()
        for ch, prio, data, pos, voices in tracks:
            self.channels[ch].start(owner, prio, data, pos, voices)
        return True

    def stop(self, owner=0):
        for c in reversed(self.channels):
            if c.owner and (owner == 0 or (owner & 0xFF) >= c.priority):
                c.end()

    def set_fade(self, period, step, priority=0):
        self.fade_period = self.fade_count = period & 0xFFFF
        if period:
            self.fade_step = s16(step)
            self.fade_priority = priority & 0xFF
        else:
            self.master = s16(step)

    def set_tempo(self, word, owner):
        if owner & 1:
            self.tempo_request = word & 0x03FF
        # tracks not clocked by timer A store the word in a variable nothing reads

    def fm_voice(self, ch, index):
        rec = ch.voices[index * FM_VOICE_SIZE:(index + 1) * FM_VOICE_SIZE]
        if not ch.is_fm or len(rec) != FM_VOICE_SIZE:
            raise ValueError('FM voice %d not available on this track' % index)
        ch.load_voice(rec)

    def ssg_voice(self, ch, index):
        rec = ch.voices[index * SSG_VOICE_SIZE:(index + 1) * SSG_VOICE_SIZE]
        if ch.is_fm or len(rec) != SSG_VOICE_SIZE:
            raise ValueError('SSG voice %d not available on this track' % index)
        ch.load_voice(rec)

    # -- interrupt
    def interrupt(self, flags):
        """flags: bit 0 = timer A overflowed, bit 1 = timer B overflowed"""
        if self.tempo_request is not None:
            self.write(0x24, self.tempo_request & 0xFF)
            self.write(0x25, self.tempo_request >> 8)
            self.tempo_request = None
        self.write(0x27, (flags << 4) | 0x0F)
        for c in self.channels:
            if c.owner & flags:
                c.clock()
        if not flags & 2:
            return
        for c in self.channels:
            if c.owner:
                c.effects()
        if self.fade_period:
            self.fade_count = (self.fade_count - 1) & 0xFFFF
            if self.fade_count == 0:
                self.fade_count = self.fade_period
                if self.fade_step > 0:
                    self.master += self.fade_step
                    if self.master >= 0:
                        self.master = 0
                        self.fade_period = 0
                elif self.fade_step < 0:
                    self.master += self.fade_step
                    if self.master <= MASTER_MIN:
                        self.master = MASTER_MIN
                        self.fade_period = 0
                else:
                    self.fade_period = 0


def bind(data):
    """.USO file -> (owner, [(channel, priority, data, position, voice table)])"""
    ntracks, nblocks = u16(data, 2), u16(data, 4)
    if not 1 <= ntracks <= 6:
        return None
    p = 6 + 10 * ntracks
    fm = ssg = b''
    for _ in range(nblocks):
        typ, ln = u16(data, p), u16(data, p + 2)
        if typ == 0:
            fm = data[p + 4:p + 4 + ln]
        else:
            ssg = data[p + 4:p + 4 + ln]
        p += 4 + ln
    base = p + 2
    tracks = []
    for i in range(ntracks):
        r = 6 + 10 * i
        ch = data[r]
        tracks.append((ch, data[r + 1], data, base + u16(data, r + 2), fm if ch < 3 else ssg))
    return u16(data, 0), tracks


# ---- timers + INT F4h services -----------------------------------------------------------
class Model:
    """Sequencer + the two YM2203 timers + the INT F4h music services.
    clk / phase describe the machine at the moment the model takes over: `phase` =
    (clocks until the next timer-A overflow, until the next timer-B overflow).  The defaults
    are what usdemu.py's start-up leaves; any other values are equally legitimate."""

    def __init__(self, clk=4246760, phase=(5920, 11032), tempo=0x0347):
        self.clk = clk
        self.writes = []
        self.reg24, self.reg25, self.reg26 = tempo & 0xFF, (tempo >> 8) & 3, 0xDF
        self.next_a = clk + phase[0]
        self.next_b = clk + phase[1]
        self.seq = Sequencer(self._write)
        self.song = None
        self.bank = None
        self.enable = 3
        self.atick = 0
        self.a_clk = []
        self.t0 = clk

    def _write(self, reg, val):
        self.writes.append((self.clk, reg, val))
        if reg == 0x24:
            self.reg24 = val
        elif reg == 0x25:
            self.reg25 = val

    def period_a(self):
        return 72 * (1024 - ((self.reg24 << 2) | (self.reg25 & 3)))

    def period_b(self):
        return 1152 * (256 - self.reg26)

    # -- INT F4h
    def _full_volume(self):
        self.seq.set_fade(0, 0)

    def _start(self):
        if self.song is None:
            return False
        b = bind(self.song)
        if b is None:
            return False
        self.t0, self.atick, self.a_clk = self.clk, 0, []
        self.seq.start(*b)
        return True

    def stop(self):                         # AH=02h
        self.seq.stop(0)
        self._full_volume()

    def stop_owner(self, owner):            # AH=84h (internal): DX = 0 all, else priority limit
        self.seq.stop(owner)
        self._full_volume()

    def load(self, data):                   # AH=00h
        self.stop()
        self.song = bytes(data)

    def load_bank(self, data):              # AH=10h
        self.stop()
        self.bank = bytes(data)

    def play_se(self, index):               # AH=11h
        if not self.enable & 2 or self.bank is None or index >= u16(self.bank, 0):
            return False
        b = bind(self.bank[2 + u16(self.bank, 2 + 2 * index):])
        if b is None:
            return False
        self.seq.start(*b)
        return True

    def play(self):                         # AH=01h
        if self.enable & 1:
            self._full_volume()
            return self._start()
        return False

    def volume(self, offset):               # AH=07h
        if self.enable & 1:
            self.seq.set_fade(0, offset)
            return self._start()
        return False

    def fade_out(self):                     # AH=03h
        self._full_volume()
        self.seq.set_fade(7, -1, 0)

    def fade_in(self):                      # AH=04h
        if self.enable & 1:
            self.seq.set_fade(0, MASTER_MIN)
            self._start()
            self.seq.set_fade(7, 1, 0)

    def fade(self, period, step, priority=0):   # AH=05h
        self.seq.set_fade(period, step, priority)

    def set_enable(self, mask):             # AH=06h, AL=0
        old, self.enable = self.enable, mask & 3
        if not self.enable & 1:
            self.stop()
        return old

    # -- time
    def step(self):
        t = min(self.next_a, self.next_b)
        flags = 0
        if self.next_a == t:
            self.next_a += self.period_a()
            flags |= 1
        if self.next_b == t:
            self.next_b += self.period_b()
            flags |= 2
        self.clk = t
        if flags & 1:
            self.atick += 1
            self.a_clk.append(t)
        self.seq.interrupt(flags)
        return flags

    def run(self, seconds=None, aticks=None):
        end = self.clk + int(round(seconds * CLOCK)) if seconds is not None else None
        target = self.atick + aticks if aticks is not None else None
        while True:
            if target is not None and self.atick >= target:
                break
            if end is not None and min(self.next_a, self.next_b) > end:
                self.clk = end
                break
            self.step()

    def active(self):
        return [c.owner for c in self.seq.channels]


# ---- command line ------------------------------------------------------------------------
def all_files():
    return [os.path.join(MUSDIR, f) for f in sorted(os.listdir(MUSDIR)) if f.upper().endswith('.USO')]


def render(path, out=None, log=None, loops=2, seconds=60.0):
    sys.path.insert(0, HERE)
    import usoinfo
    data = open(path, 'rb').read()
    tm = usoinfo.song_timing(usoinfo.parse(data, os.path.basename(path)))
    m = Model()
    m.stop()
    m.load(data)
    m.play()
    loop_clk = None
    if tm['loops'] and tm['loop'] <= 40000:
        n = max(loops, 1)
        want = tm['intro'] + n * tm['loop'] + 1
        m.run(aticks=want)
        end_clk = m.a_clk[want - 1]
        loop_clk = m.a_clk[tm['intro'] + (n - 1) * tm['loop']]
    elif tm['loops']:
        m.run(seconds=seconds)
        end_clk = m.clk
    else:
        while any(m.active()) and m.clk - m.t0 < seconds * 10 * CLOCK:
            m.step()
        m.run(seconds=0.25)
        end_clk = m.clk
    if out:
        import usdemu       # only for the VGM writer (needs unicorn to import)
        usdemu.write_vgm(out, [(c, 'M', 0, 0, r, v) for c, r, v in m.writes], m.t0, end_clk, loop_clk)
    if log:
        with open(log, 'w') as f:
            f.write('clock\tseconds\treg\tval\n')
            for c, r, v in m.writes:
                f.write('%d\t%.6f\t%02X\t%02X\n' % (c, (c - m.t0) / CLOCK, r, v))
    return m, end_clk, loop_clk


class Pair:
    """the emulated original and the model, driven with the same calls"""

    def __init__(self, phase=None):
        import usdemu
        self.e = usdemu.USDEmu()
        if phase:
            self.e.set_phase(*phase)        # clocks to the next timer-A / timer-B overflow
        self.m_phase = self.e.phase()
        self.m = Model(self.e.clk, self.m_phase, self.e.snd_w(0x0574))
        self.skip = len(self.e.writes)

    def load(self, path):
        data = open(path, 'rb').read()
        self.e.load_data(data, os.path.basename(path))     # INT F4h AH=02h, then AH=00h
        self.m.stop()
        self.m.load(data)

    def call(self, name, *args):
        getattr(self.e, name)(*args)
        getattr(self.m, name)(*args)

    def run(self, **kw):
        self.e.run(**kw)
        self.m.run(**kw)

    def compare(self):
        """-> (number of writes compared, None) or (index, description of first difference)"""
        ew = [(w[0], w[4], w[5]) for w in self.e.writes[self.skip:]]
        mw = self.m.writes
        n = min(len(ew), len(mw))
        for i in range(n):
            if ew[i] != mw[i]:
                ctx = []
                for j in range(max(0, i - 6), min(n, i + 6)):
                    ctx.append('   %s %10d  orig %02X=%02X   model %10d %02X=%02X' % (
                        '>>' if j == i else '  ', ew[j][0], ew[j][1], ew[j][2], mw[j][0], mw[j][1], mw[j][2]))
                return i, 'write %d at %.4f s differs\n%s' % (i, (ew[i][0] - self.e.t0) / CLOCK, '\n'.join(ctx))
        if len(ew) != len(mw):
            return n, 'original made %d writes, model %d (first %d equal)' % (len(ew), len(mw), n)
        if self.e.clk != self.m.clk:
            return n, 'clocks differ at the end: %d / %d' % (self.e.clk, self.m.clk)
        return n, None


def check(files, loops=3, cap=420.0, verbose=False, synth=400):
    sys.path.insert(0, HERE)
    import usoinfo
    bad = 0
    total = 0
    print('scenario play: sound "file", sound 1; intro + %d loops (cap %.0f s)' % (loops, cap))
    for path in files:
        name = os.path.basename(path)
        tm = usoinfo.song_timing(usoinfo.load(path))
        p = Pair()
        p.load(path)
        p.call('play')
        if tm['loops']:
            ticks = tm['intro'] + loops * tm['loop'] + 1 if tm['loop'] <= 40000 else None
            if ticks is not None and tm['seconds'] / tm['ticks'] * ticks <= cap:
                p.run(aticks=ticks)
            else:
                p.run(seconds=min(cap, 120.0) if ticks is None else cap)
        else:
            p.run(aticks=tm['ticks'] + 2)
            p.run(seconds=0.5)
        n, err = p.compare()
        total += n
        bad += err is not None
        print('  %-12s %7.1f s %6d ticks %8d writes  %s' % (
            name, (p.e.clk - p.e.t0) / CLOCK, p.e.atick, n, 'identical' if err is None else 'DIFFERENT'))
        if err:
            print(err)
    print('scenario fade: fade-in, fade-out, stop, volume offsets, raw fade, restart over a playing song')
    for path in files:
        name = os.path.basename(path)
        p = Pair()
        p.load(path)
        p.call('fade_in')
        p.run(seconds=6.0)
        p.call('fade_out')
        p.run(seconds=2.0)
        p.call('fade_in')               # restart while fading out
        p.run(seconds=1.3)
        p.call('fade_out')
        p.run(seconds=5.5)
        p.call('stop')
        p.run(seconds=0.3)
        p.call('volume', -20)
        p.run(seconds=3.0)
        p.call('volume', -64)
        p.run(seconds=1.0)
        p.call('fade', 3, 2, 0)         # raw: +2 every 3 effect ticks
        p.run(seconds=2.0)
        p.call('fade', 1, -5, 0)
        p.run(seconds=0.7)
        p.call('play')                  # restart over the playing song, full volume
        p.run(seconds=4.0)
        p.call('stop')
        p.run(seconds=0.2)
        n, err = p.compare()
        total += n
        bad += err is not None
        print('  %-12s %7.1f s %8d writes  %s' % (
            name, (p.e.clk - p.e.writes[p.skip][0]) / CLOCK, n, 'identical' if err is None else 'DIFFERENT'))
        if err:
            print(err)
    print('scenario chain: all files, forwards then backwards, on one driver instance (1.7 - 5.1 s each)')
    p = Pair()
    for i, path in enumerate(files + files[::-1]):
        p.load(path)
        p.call('play' if i % 3 else 'fade_in')
        p.run(seconds=4.0 if i % 4 else 1.7)
        if i % 5 == 0:
            p.call('play')              # start again over itself: channels are active
            p.run(seconds=1.1)
    n, err = p.compare()
    total += n
    bad += err is not None
    print('  %d songs, %.1f s, %d writes  %s' % (2 * len(files), (p.e.clk - p.e.writes[p.skip][0]) / CLOCK,
                                               n, 'identical' if err is None else 'DIFFERENT'))
    if err:
        print(err)
    print('scenario phase: 4 files x 4 timer phases at the start call (one with both timers coinciding), 25 s')
    import random
    rng = random.Random(11)
    both = 0
    pbad = 0
    for name in ('NV08', 'NV14', 'NVSE01', 'NV10'):
        path = [f for f in all_files() if os.path.basename(f).upper() == name + '.USO']
        if not path:
            continue
        for k in range(4):
            p = Pair(phase=(38016, 38016) if k == 0 else (rng.randrange(1, 53064), rng.randrange(1, 38016)))
            p.load(path[0])
            p.call('play')
            p.run(seconds=25.0)
            n, err = p.compare()
            total += n
            pbad += err is not None
            both += sum(1 for _t, kind in p.e.irq_log if kind == 'AB')
            if err:
                print('  %s phase %s DIFFERENT\n%s' % (name, p.m_phase, err))
    bad += pbad
    print('  16 runs, %d interrupts served both timers  %s' % (both, 'identical' if not pbad else 'see above'))
    print('scenario synthetic: %d generated songs (all commands, all modulator shapes, priorities, timer-B clocked tracks)' % synth)
    n, b = check_synthetic(synth, verbose=verbose)
    total += n
    bad += b
    print('  %d writes  %s' % (n, 'identical' if not b else '%d groups DIFFERENT' % b))
    print('%d register writes compared, %d scenario runs differ' % (total, bad))
    return bad


# ---- synthetic test songs (our own data; exercise what NOVA's files do not) --------------
def synth_song(rng, se=False):
    """a random but well-formed .USO file using every command, every modulator shape, odd
    parameter values, priorities and all three clocking modes"""
    def lfo(small=True):
        typ = rng.choice([0, 0, 0x80, 0x82, 0x84, 0x86, 0x80, 0x82, 0x84, 0x86, 1, 2, 4, 6, 0x7F, 0x41])
        step = rng.randint(-40, 40) if small or rng.random() < 0.8 else rng.randint(-3000, 3000)
        return bytes([typ, rng.choice([0, 0, 1, 2, 5, 12]), rng.choice([1, 1, 1, 2, 3, 5, 0]),
                      rng.choice([1, 2, 3, 4, 7, 0, 9])]) + struct.pack('<h', step)

    nfm, nssg = rng.randint(1, 4), rng.randint(1, 4)
    fm = b''
    for _ in range(nfm):
        regs = bytes(rng.randrange(256) for _ in range(24))
        tl = bytes(rng.randrange(128) if rng.random() < 0.9 else rng.randrange(256) for _ in range(4))
        fm += regs[:4] + tl + regs[8:] + bytes([rng.randrange(64), rng.choice([15, 8, 12, 14, 0, 5, rng.randrange(16)]),
                                                rng.choice([0xF0, 0xF0, 0xF0, 0x80, 0x5A, 0x0F])])
        fm += lfo(False) + lfo()
    ssg = b''
    for _ in range(nssg):
        ssg += bytes([rng.choice([1, 1, 1, 8, 9, 9, 0]), rng.randrange(32),
                      rng.randrange(256), rng.randrange(256),
                      rng.choice([255, 255, rng.randrange(256)]), rng.randrange(40),
                      rng.randrange(24), rng.randrange(40)])
        ssg += bytes(rng.randrange(256) for _ in range(4))
        ssg += lfo(False) + lfo() + lfo()

    def note():
        n = rng.randrange(16) if rng.random() < 0.85 else 0
        r = rng.random()
        if r < 0.55:
            return bytes([(rng.choice([6, 7, 8, 9, 10, 10, 10, 5, 4]) << 4) | n])
        if r < 0.97:
            return bytes([0xB0 | n, rng.randint(1, 40)])
        return bytes([0xB0 | n, 0x80, rng.randint(1, 60)])

    def simple(is_fm):
        r = rng.random()
        if r < 0.18:
            return bytes([0xFE, rng.choice([rng.randint(10, 80), rng.randint(0, 110), rng.randrange(256)])])
        if r < 0.36:
            return bytes([0xFD, rng.choice([rng.randint(0xD0, 0xFF), rng.randint(0, 20), rng.randrange(256)])])
        if r < 0.44:
            return bytes([0xFC, rng.choice([rng.randint(0, 6), rng.randint(0xF8, 0xFF), rng.randrange(256)])])
        if r < 0.49:
            return bytes([0xFB, rng.randint(0x90, 0xF8), rng.randrange(4)])
        if r < 0.59:
            return bytes([0xF8, rng.choice([0, 2, 4, 6, 8, 10, 12, 14, 14, rng.randrange(256)])])
        if r < 0.66:
            return bytes([0xF7])
        if r < 0.74:
            return bytes([0xF6, rng.choice([0, 0, 1, 3, 8, 40, 200])])
        if r < 0.90:
            return bytes([0xE1, rng.randrange(nfm)]) if is_fm else bytes([0xE0, rng.randrange(nssg)])
        return bytes([rng.choice([0xC0, 0xDF, 0xD3, 0xF9, 0xFA, 0xF2, 0xE2, 0xEA])])

    def block(is_fm, depth, counters):
        out = b''
        for _ in range(rng.randint(2, 7)):
            r = rng.random()
            if r < 0.12 and depth < 3 and counters:
                c = counters[0]
                body = block(is_fm, depth + 1, counters[1:]) + note()
                if rng.random() < 0.4 and len(counters) > 1:
                    # loop_exit in the body (jumping behind the repeat), with its own counter
                    # or - nonsensically, but legal - sharing the repeat's
                    tail = note() + simple(is_fm)
                    n2 = rng.choice([counters[-1], counters[-1], c])
                    body = body + bytes([0xF4, n2, rng.randint(0, 3)]) + struct.pack('<h', len(tail) + 5) + tail
                out += body + bytes([0xF3, c, rng.randint(1, 3)]) + struct.pack('<h', -(len(body) + 5))
            elif r < 0.55:
                out += simple(is_fm)
            else:
                out += note()
        return out

    ntr = rng.randint(1, 3) if se else rng.randint(1, 6)
    chans = rng.sample(range(6), ntr)
    tracks = []
    for ch in chans:
        is_fm = ch < 3
        head = bytes([0xFE, rng.randint(20, 70)]) if rng.random() < 0.8 else b''
        if rng.random() < 0.7:
            head += bytes([0xFB, rng.randint(0xA0, 0xF8), rng.randrange(4)])
        if rng.random() < 0.9:
            head += bytes([0xE1, rng.randrange(nfm)]) if is_fm else bytes([0xE0, rng.randrange(nssg)])
        intro = block(is_fm, 0, [0, 1, 2, 3])
        loop = block(is_fm, 0, [0, 1, 2, 3]) + note()
        if rng.random() < 0.75:
            code = head + intro + loop + bytes([0xF5]) + struct.pack('<h', -(len(loop) + 3)) + b'\xFF'
        else:
            code = head + intro + loop + b'\xFF'
        tracks.append(code)
    hdr = struct.pack('<HHH', rng.choice([2, 2, 2, 1, 3] if se else [1, 1, 1, 1, 2, 3, 0x0101]), ntr, 2)
    off = 0
    prio_mode = 1.0 if se else rng.random()
    for ch, code in zip(chans, tracks):
        prio = 0 if prio_mode < 0.6 else rng.randrange(4)
        hdr += struct.pack('<BBH', ch, prio, off) + bytes(rng.randrange(256) for _ in range(6))
        off += len(code)
    data = b''.join(tracks)
    return (hdr + struct.pack('<HH', 0, len(fm)) + fm + struct.pack('<HH', 3, len(ssg)) + ssg
            + struct.pack('<H', len(data)) + data)


def check_synthetic(count, seed=1993, verbose=False):
    import random
    rng = random.Random(seed)
    bad = 0
    total = 0
    p = None
    nbank = 0
    for i in range(count):
        if p is None or i % 8 == 0:
            nbank = 0
            if p is not None:
                n, err = p.compare()
                total += n
                if err:
                    bad += 1
                    print('  synthetic group ending at song %d: DIFFERENT\n%s' % (i, err))
            p = Pair()
        data = synth_song(rng)
        name = 'SYN%04d.USO' % i
        if rng.random() < 0.8:
            p.e.int_f4(0x02)
            p.m.stop()
        p.e.files[name] = data
        p.e.int_f4(0x00, bx=p.e._name(name))
        p.m.load(data)
        r = rng.random()
        if r < 0.5:
            p.call('play')
        elif r < 0.75:
            p.call('fade_in')
        else:
            p.call('volume', rng.randint(-70, 5))
        if rng.random() < 0.3:
            # an effect bank: 1-3 songs behind a count word and an offset table (offsets are
            # relative to the table); loading it stops the music, so start that again
            entries = [synth_song(rng, se=True) for _ in range(rng.randint(1, 3))]
            bank = struct.pack('<H', len(entries))
            off = 2 * len(entries)
            for en in entries:
                bank += struct.pack('<H', off)
                off += len(en)
            bank += b''.join(entries)
            p.e.load_bank(bank, 'BNK%04d.USO' % i)
            p.m.load_bank(bank)
            p.call('play')
            nbank = len(entries)
        for _ in range(rng.randint(1, 4)):
            p.run(seconds=rng.uniform(0.2, 1.6))
            if nbank and rng.random() < 0.6:
                p.call('play_se', rng.randint(0, nbank))
                p.run(seconds=rng.uniform(0.1, 0.8))
            r = rng.random()
            if r < 0.15:
                p.call('fade_out')
            elif r < 0.30:
                p.call('fade', rng.randint(0, 4), rng.randint(-9, 9), rng.randint(0, 3))
            elif r < 0.40:
                p.call('stop_owner', rng.randint(1, 3))
            elif r < 0.50:
                p.call('play')
            elif r < 0.55:
                p.call('fade_in')
        if verbose:
            print('  %s %d bytes, t=%.1f s, active %s' % (name, len(data), p.e.clk / CLOCK, p.e.active()))
    n, err = p.compare()
    total += n
    if err:
        bad += 1
        print('  synthetic group (last): DIFFERENT\n%s' % err)
    return total, bad


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('files', nargs='*')
    ap.add_argument('-o', '--out')
    ap.add_argument('--log')
    ap.add_argument('--loops', type=int)
    ap.add_argument('--seconds', type=float, default=60.0)
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--cap', type=float, default=420.0)
    ap.add_argument('--synth', type=int, default=400, help='number of synthetic songs (--check)')
    ap.add_argument('--synth-only', action='store_true')
    ap.add_argument('--seed', type=int, default=1993)
    ap.add_argument('-v', '--verbose', action='store_true')
    a = ap.parse_args()
    if a.check:
        if a.synth_only:
            n, b = check_synthetic(a.synth, a.seed, a.verbose)
            print('%d writes compared, %d groups differ' % (n, b))
            return 1 if b else 0
        return 1 if check(a.files or all_files(), a.loops or 3, a.cap, a.verbose, a.synth) else 0
    if not a.files:
        ap.error('need a file or --check')
    for path in a.files:
        if not os.path.exists(path):
            path = os.path.join(MUSDIR, path if path.upper().endswith('.USO') else path + '.USO')
        m, end_clk, loop_clk = render(path, a.out, a.log, a.loops or 2, a.seconds)
        print('%s: %.2f s, %d writes, %d timer-A ticks%s' % (
            os.path.basename(path), (end_clk - m.t0) / CLOCK, len(m.writes), m.atick,
            ', loop %.2f s' % ((end_clk - loop_clk) / CLOCK) if loop_clk else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
