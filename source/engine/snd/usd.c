/* SPDX-License-Identifier: GPL-3.0-or-later */
/* USD music driver (usd.h): a line-by-line port of re-tools/usdmodel.py. Each function names
 * the Python it ports and the section of docs/re/usd-sequencer.md ("seq") or
 * docs/re/usd-driver.md ("drv") it implements; read them side by side. Python's unbounded
 * integers are int32_t here wherever the model does not wrap, and every wrap of the model
 * (s8, s16, & 0xFF, & 0xFFFF) is done explicitly. Where the model raises an exception (data
 * no correct file contains) this port does something defined instead; those places are
 * marked "model: raises". */
#include <string.h>
#include "snd/usd.h"

/* SsgChannel.ENV_* */
enum { USD_ENV_ATTACK, USD_ENV_DECAY, USD_ENV_SUSTAIN, USD_ENV_RELEASE, USD_ENV_OFF };

#define USD_VOL_SILENT (-1024)              /* volume used to mute an FM channel at its end */
#define USD_MASTER_MIN (-64)
#define USD_BANK_BASE USD_SONG_SIZE         /* the bank's offset in usd.mem */

/* ---- tables (seq §5, §8.1, §8.2) ---------------------------------------------------- */
static const uint16_t usd_lengths[11] = { 192, 144, 96, 72, 48, 36, 24, 18, 12, 9, 6 };
/* pitch of the 12 semitones inside an octave, in units of 1/618 of the F-number of C */
static const uint16_t usd_semitone_pitch[12] = {
    0, 37, 76, 117, 161, 207, 256, 308, 363, 422, 484, 549 };
#define USD_OCTAVE_PITCH 618
/* SSG tone periods of note numbers 12..107 (not exact halvings: the whole table is kept) */
static const uint16_t usd_ssg_period[96] = {
    3816, 3602, 3400, 3209, 3029, 2859, 2698, 2547, 2404, 2269, 2142, 2022,
    1908, 1801, 1700, 1604, 1514, 1429, 1349, 1273, 1202, 1135, 1071, 1011,
    954, 900, 850, 802, 757, 715, 675, 637, 601, 567, 535, 505,
    477, 450, 425, 401, 379, 357, 337, 318, 301, 284, 268, 253,
    239, 225, 212, 201, 189, 179, 169, 159, 150, 142, 134, 126,
    119, 113, 106, 100, 95, 89, 84, 80, 75, 71, 67, 63,
    60, 56, 53, 50, 47, 45, 42, 40, 38, 35, 33, 32,
    30, 28, 27, 25, 24, 22, 21, 20, 19, 18, 17, 16 };

/* one track of a bound song: bind()'s (channel, priority, data, position, voice table) */
struct usd_track {
    uint8_t ch, prio;
    uint32_t data, pos, voices;
    uint8_t has_voices;
};

/* ---- integer helpers -------------------------------------------------------------- */
/* s8 */
static int32_t usd_s8(int32_t v)
{
    v = (int32_t)((uint32_t)v & 0xFFu);
    return (v & 0x80) ? v - 0x100 : v;
}

/* s16 */
static int32_t usd_s16(int32_t v)
{
    v = (int32_t)((uint32_t)v & 0xFFFFu);
    return (v & 0x8000) ? v - (int32_t)0x10000 : v;
}

/* min(max(v, lo), hi) */
static int32_t usd_clamp(int32_t v, int32_t lo, int32_t hi)
{
    return v < lo ? lo : v > hi ? hi : v;
}

/* Python's v >> n for a negative v (floor), without C's implementation-defined shift */
static int32_t usd_shr(int32_t v, int n)
{
    return v >= 0 ? v >> n : -((-(v + 1)) >> n) - 1;
}

/* a byte of the music buffer (the song's bytes, read as the original reads its segment;
 * beyond the buffer: 0) */
static uint8_t usd_byte(const struct usd *m, uint32_t addr)
{
    return addr < USD_MEM_SIZE ? m->mem[addr] : 0;
}

/* u16 */
static uint32_t usd_word(const struct usd *m, uint32_t addr)
{
    return (uint32_t)usd_byte(m, addr) | ((uint32_t)usd_byte(m, addr + 1) << 8);
}

/* Model._write: the callback gets the model's clock; the timer-A registers are tracked */
static void usd_write(struct usd *m, int reg, int val)
{
    if (m->write)
        m->write(m->ctx, m->clk, reg, val);
    if (reg == 0x24)
        m->reg24 = (uint8_t)val;
    else if (reg == 0x25)
        m->reg25 = (uint8_t)val;
}

/* Channel.out */
static void usd_out(struct usd *m, int32_t reg, int32_t val)
{
    usd_write(m, (int)((uint32_t)reg & 0xFFu), (int)((uint32_t)val & 0xFFu));
}

/* fm_pitch (seq §8.1): pitch value of FM note number 0..95 */
static int32_t usd_fm_pitch(int32_t note)
{
    return USD_OCTAVE_PITCH * (note / 12) + usd_semitone_pitch[note % 12];
}

/* gate_threshold (seq §7.1): remaining-tick count below which a note is released */
static uint16_t usd_gate_threshold(uint32_t mode, uint32_t length)
{
    switch ((mode >> 1) & 7) {
    case 0:
        return 0;
    case 1:
        return (uint16_t)(length - (length >> 3));
    case 2:
        return (uint16_t)(length - (length >> 2));
    case 3:
        return (uint16_t)((length >> 1) + (length >> 3));
    case 4:
        return (uint16_t)(length >> 1);
    case 5:
        return (uint16_t)((length >> 2) + (length >> 3));
    case 6:
        return (uint16_t)(length >> 2);
    default:
        return (uint16_t)(length >> 3);
    }
}

/* ---- low-frequency modulators (seq §10) -------------------------------------------- */
/* Lfo.configure: the six parameter bytes of the voice record */
static void usd_lfo_configure(struct usd_lfo *l, const uint8_t *rec)
{
    l->type = rec[0];
    l->delay = rec[1];
    l->speed = rec[2];
    l->count = rec[3];
    l->depth = (int16_t)usd_s16((int32_t)rec[4] | ((int32_t)rec[5] << 8));
}

/* Lfo.restart */
static void usd_lfo_restart(struct usd_lfo *l)
{
    l->phase = 0;
    l->wait = l->delay;
}

/* Lfo._speed_elapsed */
static int usd_lfo_speed_elapsed(struct usd_lfo *l)
{
    l->speed_ctr = (uint8_t)(l->speed_ctr - 1);
    return l->speed_ctr == 0;
}

/* Lfo._count_elapsed */
static int usd_lfo_count_elapsed(struct usd_lfo *l)
{
    l->count_ctr = (uint8_t)(l->count_ctr - 1);
    return l->count_ctr == 0;
}

/* Lfo.step: once per effect tick while enabled. Returns 0 for the model's None, else 1 with
 * the value for the chip in *out (an offset for pitch and noise, the complete volume for
 * fmvol). base: the track volume for fmvol (start value of the accumulator), else unused. */
static int usd_lfo_step(struct usd_lfo *l, int32_t base, int32_t *out)
{
    int shape;
    int32_t home;
    if (l->wait) {
        l->wait--;
        return 0;
    }
    shape = (l->type >> 1) & 3;
    home = l->kind == USD_LFO_FMVOL ? base : 0;
    if (shape == 3) {                                   /* square */
        if (l->phase != 0 && !usd_lfo_speed_elapsed(l))
            return 0;
        if (l->phase == 1) {
            l->phase = 2;
            *out = home;
            if (l->kind == USD_LFO_SSGVOL)
                l->acc = 0;
        } else {
            l->phase = 1;
            *out = usd_s16(home + l->depth);
            if (l->kind == USD_LFO_SSGVOL)
                l->acc = l->depth;
        }
        l->speed_ctr = l->speed;
        l->count_ctr = l->count;
        return 1;
    }
    if (l->phase == 0) {
        l->phase = 1;
        l->speed_ctr = l->speed;
        l->acc = (int16_t)home;
        if (shape == 1)
            l->count_ctr = l->count;
        else if (shape == 2)
            l->count_ctr = (uint8_t)((l->count >> 1) ? (l->count >> 1) : 1);
    }
    if (!usd_lfo_speed_elapsed(l))
        return 0;
    l->speed_ctr = l->speed;
    if (shape == 2 && l->kind != USD_LFO_PITCH) {
        l->acc = (int16_t)usd_s16((int32_t)l->acc + (l->phase == 1 ? l->depth : -(int32_t)l->depth));
        *out = l->acc;
    } else {
        l->acc = (int16_t)usd_s16((int32_t)l->acc + l->depth);
        *out = l->acc;
        if (shape == 2 && l->phase == 2)                /* pitch: mirrored, not reversed */
            *out = usd_s16(-(int32_t)l->acc);
    }
    if (shape && usd_lfo_count_elapsed(l)) {
        l->count_ctr = l->count;
        if (shape == 1) {
            l->acc = (int16_t)home;
        } else {
            if (l->kind == USD_LFO_PITCH || l->kind == USD_LFO_NOISE)
                l->acc = 0;
            l->phase ^= 3;
        }
    }
    return 1;
}

/* ---- FM channels (seq §8.1, §8.3, §9.1) ---------------------------------------------- */
/* FmChannel.write_pitch + fm_fnum: pitch value -> A4h+n (block, F-number high), A0h+n */
static void usd_fm_write_pitch(struct usd *m, struct usd_channel *c, int32_t pitch)
{
    int32_t block, f;
    pitch = usd_clamp(pitch, 0, 0x134F);
    block = pitch / USD_OCTAVE_PITCH;
    f = pitch % USD_OCTAVE_PITCH + USD_OCTAVE_PITCH;
    usd_out(m, 0xA4 + c->number, (block << 3) | (f >> 8));
    usd_out(m, 0xA0 + c->number, f & 0xFF);
}

/* FmChannel.write_levels (seq §8.3): total level of the slots selected by the volume mask */
static void usd_fm_write_levels(struct usd *m, struct usd_channel *c, int32_t volume)
{
    int slot;
    if (c->priority >= m->fade_priority)
        volume += m->master;
    for (slot = 0; slot < 4; slot++)
        if ((c->voice[25] >> slot) & 1) {
            int32_t tl = usd_s8(c->voice[4 + slot]) - volume;
            usd_out(m, 0x40 + c->number + 4 * slot, usd_clamp(tl, 0, 0x7F));
        }
}

/* FmChannel.key_off */
static void usd_fm_key_off(struct usd *m, struct usd_channel *c)
{
    usd_out(m, 0x28, c->number);
}

/* ---- SSG channels (seq §8.2, §9.2) --------------------------------------------------- */
/* SsgChannel.write_pitch: the tone period, clamped to 0..0FFFh except at a note-on */
static void usd_ssg_write_pitch(struct usd *m, struct usd_channel *c, int32_t period, int clamp)
{
    if (clamp)
        period = usd_clamp(period, 0, 0x0FFF);
    usd_out(m, 2 * c->number, period);
    usd_out(m, 2 * c->number + 1, (int32_t)(((uint32_t)period >> 8) & 0xFFu));
}

/* SsgChannel.key_off */
static void usd_ssg_key_off(struct usd *m, struct usd_channel *c)
{
    m->mixer = (uint8_t)(m->mixer | c->mixer);
    usd_out(m, 0x07, m->mixer);
    c->keyed = 0;
    usd_out(m, 0x08 + c->number, 0);
}

/* SsgChannel.envelope (seq §8.2): one step of the software envelope, then the volume */
static void usd_ssg_envelope(struct usd *m, struct usd_channel *c)
{
    const uint8_t *v = c->voice;
    int st = c->env_state;
    int32_t level;
    if (st == USD_ENV_ATTACK) {
        level = c->env_level + v[4];
        if (level >= v[2]) {
            level = v[2];
            c->env_state = USD_ENV_DECAY;
        }
        c->env_level = (int16_t)level;
    } else if (st == USD_ENV_DECAY) {
        level = c->env_level - v[5];
        c->env_level = (int16_t)level;
        if (level <= v[3])
            c->env_state = USD_ENV_SUSTAIN;
    } else if (st == USD_ENV_SUSTAIN || st == USD_ENV_RELEASE) {
        level = c->env_level - (st == USD_ENV_SUSTAIN ? v[6] : v[7]);
        c->env_level = (int16_t)level;
        if (level <= 0) {
            c->env_state = USD_ENV_OFF;
            c->env_level = 0;
            usd_ssg_key_off(m, c);
        }
    }
    level = st == USD_ENV_OFF ? 0 : c->env_level;
    if (c->priority >= m->fade_priority)
        level += 2 * (int32_t)m->master;
    level += (int32_t)c->volume + c->vol_lfo.acc;
    usd_out(m, 0x08 + c->number, usd_clamp(usd_shr(level, 4), 0, 15));
}

/* SsgChannel.write_noise: noise period = voice's + LFO offset / 16 */
static void usd_ssg_write_noise(struct usd *m, struct usd_channel *c, int32_t off)
{
    int32_t n = usd_s16(usd_shr(off, 4) + c->voice[1]);
    usd_out(m, 0x06, usd_clamp(n, 0, 0x1F));
}

/* ---- Channel: FM / SSG dispatch ---------------------------------------------------- */
/* Channel.write_pitch (FmChannel / SsgChannel with clamp) */
static void usd_ch_write_pitch(struct usd *m, struct usd_channel *c, int32_t pitch)
{
    if (c->is_fm)
        usd_fm_write_pitch(m, c, pitch);
    else
        usd_ssg_write_pitch(m, c, pitch, 1);
}

/* FmChannel.release / SsgChannel.release (seq §4) */
static void usd_ch_release(struct usd *m, struct usd_channel *c)
{
    if (c->is_fm)
        usd_fm_key_off(m, c);
    else
        c->env_state = USD_ENV_RELEASE;
}

/* FmChannel.silence / SsgChannel.silence (drv §5.2) */
static void usd_ch_silence(struct usd *m, struct usd_channel *c)
{
    if (c->is_fm) {
        usd_fm_key_off(m, c);
        usd_fm_write_levels(m, c, USD_VOL_SILENT);
    } else {
        usd_ssg_key_off(m, c);
    }
}

/* FmChannel.rest / SsgChannel.rest (seq §5) */
static void usd_ch_rest(struct usd *m, struct usd_channel *c)
{
    if (c->is_fm) {
        usd_fm_key_off(m, c);
        c->keyed = 0;
    } else {
        usd_ssg_key_off(m, c);
    }
}

/* Channel.clear_extra_flags / SsgChannel.clear_extra_flags */
static void usd_ch_clear_extra_flags(struct usd_channel *c)
{
    if (!c->is_fm)
        c->noise_lfo_on = 0;
}

/* FmChannel.strike / SsgChannel.strike: the sound part of a note-on (seq §5) */
static void usd_ch_strike(struct usd *m, struct usd_channel *c)
{
    if (c->is_fm) {
        usd_fm_write_pitch(m, c, c->pitch);
        if (c->pitch_lfo_on)
            usd_lfo_restart(&c->pitch_lfo);
        if (c->vol_lfo_on)
            usd_lfo_restart(&c->vol_lfo);
        if (c->keyed)
            usd_fm_key_off(m, c);
        usd_fm_write_levels(m, c, c->volume);
        usd_out(m, 0x28, (c->voice[26] & 0xF0) | c->number);
        c->keyed = 1;
        return;
    }
    usd_ssg_write_pitch(m, c, c->pitch, 0);
    if (c->pitch_lfo_on)
        usd_lfo_restart(&c->pitch_lfo);
    if (c->vol_lfo_on)
        usd_lfo_restart(&c->vol_lfo);
    if (c->noise_lfo_on)
        usd_lfo_restart(&c->noise_lfo);
    if (c->keyed)
        usd_ssg_key_off(m, c);
    c->vol_lfo.acc = 0;
    c->env_level = 0;
    c->env_state = USD_ENV_ATTACK;
    usd_ssg_envelope(m, c);
    m->mixer = (uint8_t)((m->mixer | (0x09 << c->number)) & ~c->mixer & 0xFF);
    usd_out(m, 0x07, m->mixer);
    c->keyed = 1;
}

/* FmChannel.load_voice (seq §9.1) */
static void usd_fm_load_voice(struct usd *m, struct usd_channel *c, const uint8_t *rec)
{
    int i;
    memcpy(c->voice, rec, USD_FM_VOICE_SIZE);
    for (i = 0; i < 24; i++)
        usd_out(m, 0x30 + c->number + 4 * i, rec[i]);
    for (i = 0; i < 4; i++)
        usd_out(m, 0x90 + c->number + 4 * i, 0);
    usd_out(m, 0xB0 + c->number, rec[24]);
    usd_lfo_configure(&c->pitch_lfo, rec + 27);
    usd_lfo_configure(&c->vol_lfo, rec + 33);
    c->pitch_lfo_on = rec[27] != 0;
    c->vol_lfo_on = rec[33] != 0;
}

/* SsgChannel.load_voice (seq §9.2) */
static void usd_ssg_load_voice(struct usd *m, struct usd_channel *c, const uint8_t *rec)
{
    memcpy(c->voice, rec, USD_SSG_VOICE_SIZE);
    usd_lfo_configure(&c->pitch_lfo, rec + 12);
    usd_lfo_configure(&c->vol_lfo, rec + 18);
    usd_lfo_configure(&c->noise_lfo, rec + 24);
    c->pitch_lfo_on = c->vol_lfo_on = c->noise_lfo_on = 0;
    if (rec[0] & 8) {
        usd_out(m, 0x06, rec[1]);
        c->noise_lfo_on = rec[24] != 0;
    }
    c->pitch_lfo_on = rec[12] != 0;
    c->vol_lfo_on = rec[18] != 0;
    c->mixer = (uint8_t)((rec[0] << c->number) & 0xFF);
}

/* Sequencer.fm_voice / Sequencer.ssg_voice (seq §6 E1 / E0). Model: raises for E1 on an SSG
 * track or E0 on an FM track, for a file without a table of that kind and for a record not
 * wholly inside the table. Here the first two are ignored (the original would corrupt its
 * work area / use a default pointer), and a record is read wherever the voice number puts it,
 * as the original does (voice numbers are not range-checked). */
static void usd_seq_voice(struct usd *m, struct usd_channel *c, int fm, uint32_t index)
{
    uint8_t rec[USD_FM_VOICE_SIZE];
    uint32_t size = fm ? USD_FM_VOICE_SIZE : USD_SSG_VOICE_SIZE, i;
    if (c->is_fm != fm || !c->has_voices)
        return;
    for (i = 0; i < size; i++)
        rec[i] = usd_byte(m, c->voices + index * size + i);
    if (fm)
        usd_fm_load_voice(m, c, rec);
    else
        usd_ssg_load_voice(m, c, rec);
}

/* Sequencer.set_tempo (drv §4.2): tracks not clocked by timer A store the word in a variable
 * nothing reads */
static void usd_seq_set_tempo(struct usd *m, uint32_t word, uint8_t owner)
{
    if (owner & 1) {
        m->tempo_request = (uint16_t)(word & 0x03FF);
        m->tempo_pending = 1;
    }
}

/* ---- Channel: common behaviour (seq §3-§7) ------------------------------------------- */
/* Channel.start (drv §5.1 step 3): transpose, volume, gate, porta step, pitch, voice, LFO
 * and envelope state are kept from the previous track */
static void usd_ch_start(struct usd_channel *c, uint8_t owner, const struct usd_track *t)
{
    c->priority = t->prio;
    c->data = t->data;
    c->pos = t->pos;
    c->voices = t->voices;
    c->has_voices = t->has_voices;
    c->counter = 1;
    c->keyed = c->porta = c->tie = 0;
    c->pitch_lfo_on = c->vol_lfo_on = 0;
    usd_ch_clear_extra_flags(c);
    c->detune = 0;
    memset(c->loops, 0, sizeof c->loops);
    c->owner = owner;
}

/* Channel.end: end-of-track command, also used to stop a channel (drv §5.2) */
static void usd_ch_end(struct usd *m, struct usd_channel *c)
{
    usd_ch_silence(m, c);
    c->keyed = c->porta = c->tie = 0;
    c->pitch_lfo_on = c->vol_lfo_on = 0;
    usd_ch_clear_extra_flags(c);
    c->owner = 0;
    c->target = 0;
}

/* Channel.fetch */
static uint32_t usd_ch_fetch(const struct usd *m, struct usd_channel *c)
{
    uint32_t b = usd_byte(m, c->data + c->pos);
    c->pos = (c->pos + 1) & 0xFFFFu;
    return b;
}

/* Channel.fetch16 */
static uint32_t usd_ch_fetch16(const struct usd *m, struct usd_channel *c)
{
    uint32_t lo = usd_ch_fetch(m, c);
    return lo | (usd_ch_fetch(m, c) << 8);
}

/* Channel.jump (seq §6 F5): position += signed word */
static void usd_ch_jump(const struct usd *m, struct usd_channel *c)
{
    uint32_t d = usd_ch_fetch16(m, c);
    c->pos = (c->pos + d) & 0xFFFFu;
}

/* Channel.note_on (seq §5) */
static void usd_ch_note_on(struct usd *m, struct usd_channel *c, uint32_t nibble, uint32_t length)
{
    int32_t n = usd_s8((int32_t)(nibble + c->transpose)), p;
    c->note = (int8_t)n;
    if (c->is_fm)                                       /* FmChannel / SsgChannel.note_pitch */
        p = usd_fm_pitch(usd_clamp(n, 0, 0x5F));
    else
        p = usd_ssg_period[usd_clamp(n, 0x0C, 0x6B) - 0x0C];
    c->counter = (uint16_t)length;
    c->gate = usd_gate_threshold(c->gate_mode, length);
    p = usd_s16(p + c->detune);
    if (c->porta) {
        if (c->target == 0)
            c->pitch = (int16_t)p;
        c->target = (int16_t)p;
    } else {
        c->pitch = (int16_t)p;
    }
    usd_ch_strike(m, c);
}

/* Channel.row (seq §5, §6): execute commands up to and including the next note or rest */
static void usd_ch_row(struct usd *m, struct usd_channel *c)
{
    for (;;) {
        uint32_t b = usd_ch_fetch(m, c), v, n, cnt;
        if (b < 0xC0) {
            uint32_t length;
            if (b < 0xB0) {
                length = usd_lengths[b >> 4];
            } else {
                length = usd_ch_fetch(m, c);
                if (length & 0x80)
                    length = ((length << 8) | usd_ch_fetch(m, c)) & 0x7FFF;
            }
            if (b & 15) {
                usd_ch_note_on(m, c, b & 15, length);
            } else {
                usd_ch_rest(m, c);
                c->counter = (uint16_t)length;
            }
            return;
        }
        switch (b) {
        case 0xFF:                                      /* end */
            usd_ch_end(m, c);
            return;
        case 0xFE:                                      /* transpose */
            c->transpose = (uint8_t)usd_ch_fetch(m, c);
            break;
        case 0xFD:                                      /* volume */
            c->volume = (int8_t)usd_s8((int32_t)usd_ch_fetch(m, c));
            break;
        case 0xFC:                                      /* detune */
            c->detune = (int8_t)usd_s8((int32_t)usd_ch_fetch(m, c));
            break;
        case 0xFB:                                      /* tempo */
            usd_seq_set_tempo(m, usd_ch_fetch16(m, c), c->owner);
            break;
        case 0xF8:                                      /* gate */
            c->gate_mode = (uint8_t)usd_ch_fetch(m, c);
            break;
        case 0xF7:                                      /* tie */
            c->tie = 1;
            break;
        case 0xF6:                                      /* portamento */
            v = usd_ch_fetch(m, c);
            if (v) {
                c->porta_step = (uint8_t)v;
                c->target = 0;
                c->porta = 1;
            } else {
                c->porta = 0;
            }
            break;
        case 0xF5:                                      /* jump */
            usd_ch_jump(m, c);
            break;
        case 0xF4:              /* loop exit: leave the loop on the last pass. Model: raises
                                 * for a counter index > 3; here it is taken modulo 4 */
            n = usd_ch_fetch(m, c) & 3;
            cnt = usd_ch_fetch(m, c);
            if (c->loops[n] == 0) {
                c->loops[n] = (uint8_t)cnt;
                c->pos = (c->pos + 2) & 0xFFFFu;
            } else if (--c->loops[n]) {
                c->pos = (c->pos + 2) & 0xFFFFu;
            } else {
                usd_ch_jump(m, c);
            }
            break;
        case 0xF3:                                      /* repeat (index as for F4) */
            n = usd_ch_fetch(m, c) & 3;
            cnt = usd_ch_fetch(m, c);
            if (c->loops[n] == 0) {
                c->loops[n] = (uint8_t)cnt;
                usd_ch_jump(m, c);
            } else if (--c->loops[n]) {
                usd_ch_jump(m, c);
            } else {
                c->pos = (c->pos + 2) & 0xFFFFu;
            }
            break;
        case 0xE1:                                      /* FM voice */
            usd_seq_voice(m, c, 1, usd_ch_fetch(m, c));
            break;
        case 0xE0:                                      /* SSG voice */
            usd_seq_voice(m, c, 0, usd_ch_fetch(m, c));
            break;
        default:                                        /* C0..FF otherwise: no operation */
            break;
        }
    }
}

/* Channel.clock (seq §4): the note clock */
static void usd_ch_clock(struct usd *m, struct usd_channel *c)
{
    c->counter = (uint16_t)(c->counter - 1);
    if (c->counter) {
        if (c->tie || c->porta || !c->keyed || c->counter >= c->gate)
            return;
        usd_ch_release(m, c);
        c->keyed = 0;
        c->tie = 1;             /* "released already": no second release at the end */
        return;
    }
    if (c->keyed && !(c->tie || c->porta))
        usd_ch_release(m, c);
    c->keyed = 0;
    c->tie = 0;
    c->counter = 1;
    usd_ch_row(m, c);
}

/* Channel.slide (seq §8.4): portamento, move pitch towards target (unsigned comparison) */
static void usd_ch_slide(struct usd_channel *c)
{
    uint32_t cur = (uint16_t)c->pitch, tgt = (uint16_t)c->target;
    if (cur > tgt) {
        cur = (cur - c->porta_step) & 0xFFFFu;
        if (cur < tgt)
            cur = tgt;
    } else if (cur < tgt) {
        cur = (cur + c->porta_step) & 0xFFFFu;
        if (cur > tgt)
            cur = tgt;
    }
    c->pitch = (int16_t)usd_s16((int32_t)cur);
}

/* Channel.effects_pitch: timer-B work on the pitch, portamento and pitch modulator */
static void usd_ch_effects_pitch(struct usd *m, struct usd_channel *c)
{
    int32_t off;
    if (c->porta) {
        usd_ch_slide(c);
        if (!c->pitch_lfo_on)
            usd_ch_write_pitch(m, c, c->pitch);
    }
    if (c->pitch_lfo_on && usd_lfo_step(&c->pitch_lfo, 0, &off))
        usd_ch_write_pitch(m, c, usd_s16(c->pitch + off));
}

/* FmChannel.effects / SsgChannel.effects (seq §4, effect clock) */
static void usd_ch_effects(struct usd *m, struct usd_channel *c)
{
    int32_t v;
    usd_ch_effects_pitch(m, c);
    if (c->is_fm) {
        if (c->vol_lfo_on && usd_lfo_step(&c->vol_lfo, c->volume, &v))
            usd_fm_write_levels(m, c, v);
        return;
    }
    if (c->vol_lfo_on)
        usd_lfo_step(&c->vol_lfo, 0, &v);
    if (c->noise_lfo_on && usd_lfo_step(&c->noise_lfo, 0, &v))
        usd_ssg_write_noise(m, c, v);
    usd_ssg_envelope(m, c);
}

/* ---- the sequencer ------------------------------------------------------------------ */
/* Sequencer.start (drv §5.1): priority check, silence, bind. Model: raises for a channel
 * byte > 5; such a track is skipped here. */
static int usd_seq_start(struct usd *m, uint8_t owner, const struct usd_track *t, int n)
{
    int i;
    for (i = 0; i < n; i++)
        if (t[i].ch < USD_CHANNELS) {
            const struct usd_channel *c = &m->ch[t[i].ch];
            if (t[i].prio && c->owner && t[i].prio < c->priority)
                return 0;
        }
    for (i = 0; i < n; i++)
        if (t[i].ch < USD_CHANNELS && m->ch[t[i].ch].owner)
            usd_ch_end(m, &m->ch[t[i].ch]);
    for (i = 0; i < n; i++)
        if (t[i].ch < USD_CHANNELS)
            usd_ch_start(&m->ch[t[i].ch], owner, &t[i]);
    return 1;
}

/* Sequencer.stop (drv §5.2): channels 5 down to 0; owner 0 = all, else priority limit */
static void usd_seq_stop(struct usd *m, int owner)
{
    int i;
    for (i = USD_CHANNELS - 1; i >= 0; i--) {
        struct usd_channel *c = &m->ch[i];
        if (c->owner && (owner == 0 || ((unsigned)owner & 0xFFu) >= c->priority))
            usd_ch_end(m, c);
    }
}

/* Sequencer.set_fade (drv §6): period != 0 starts a fade, 0 sets the master volume */
static void usd_seq_set_fade(struct usd *m, int32_t period, int32_t step, int32_t priority)
{
    m->fade_period = m->fade_count = (uint16_t)((uint32_t)period & 0xFFFFu);
    if (period) {
        m->fade_step = (int16_t)usd_s16(step);
        m->fade_priority = (uint8_t)((uint32_t)priority & 0xFFu);
    } else {
        m->master = (int16_t)usd_s16(step);
    }
}

/* Sequencer.interrupt (seq §4, drv §4.3, §6): flags bit 0 = timer A overflowed (note clock),
 * bit 1 = timer B (effect clock) */
static void usd_seq_interrupt(struct usd *m, int flags)
{
    int i;
    if (m->tempo_pending) {
        usd_write(m, 0x24, m->tempo_request & 0xFF);
        usd_write(m, 0x25, m->tempo_request >> 8);
        m->tempo_pending = 0;
    }
    usd_write(m, 0x27, (flags << 4) | 0x0F);
    for (i = 0; i < USD_CHANNELS; i++)
        if (m->ch[i].owner & flags)
            usd_ch_clock(m, &m->ch[i]);
    if (!(flags & 2))
        return;
    for (i = 0; i < USD_CHANNELS; i++)
        if (m->ch[i].owner)
            usd_ch_effects(m, &m->ch[i]);
    if (m->fade_period) {
        m->fade_count = (uint16_t)(m->fade_count - 1);
        if (m->fade_count == 0) {
            int32_t master = (int32_t)m->master + m->fade_step;
            m->fade_count = m->fade_period;
            if (m->fade_step > 0) {
                if (master >= 0) {
                    master = 0;
                    m->fade_period = 0;
                }
                m->master = (int16_t)master;
            } else if (m->fade_step < 0) {
                if (master <= USD_MASTER_MIN) {
                    master = USD_MASTER_MIN;
                    m->fade_period = 0;
                }
                m->master = (int16_t)master;
            } else {
                m->fade_period = 0;
            }
        }
    }
}

/* bind (seq §2, drv §5.1): the .USO image at `img` in the buffer -> owner (low byte) and the
 * tracks; returns their number, 0 if the file is refused (track count 0 or > 6). Model:
 * raises when the voice blocks run beyond the data; here the walk stops at the end of the
 * buffer. */
static int usd_bind(const struct usd *m, uint32_t img, uint8_t *owner, struct usd_track *tr)
{
    uint32_t ntracks = usd_word(m, img + 2), nblocks = usd_word(m, img + 4), p, i, base;
    uint32_t fm = 0, ssg = 0;
    uint8_t has_fm = 0, has_ssg = 0;
    if (ntracks < 1 || ntracks > 6)
        return 0;
    p = 6 + 10 * ntracks;
    for (i = 0; i < nblocks && img + p < USD_MEM_SIZE; i++) {
        uint32_t typ = usd_word(m, img + p), ln = usd_word(m, img + p + 2);
        if (typ == 0) {
            fm = img + p + 4;
            has_fm = 1;
        } else {
            ssg = img + p + 4;
            has_ssg = 1;
        }
        p += 4 + ln;
    }
    base = p + 2;
    for (i = 0; i < ntracks; i++) {
        uint32_t r = img + 6 + 10 * i;
        tr[i].ch = usd_byte(m, r);
        tr[i].prio = usd_byte(m, r + 1);
        tr[i].data = img;
        tr[i].pos = base + usd_word(m, r + 2);
        tr[i].voices = tr[i].ch < 3 ? fm : ssg;
        tr[i].has_voices = tr[i].ch < 3 ? has_fm : has_ssg;
    }
    *owner = usd_byte(m, img);
    return (int)ntracks;
}

/* ---- Model: timers + INT F4h services (drv §4.2, §5) ---------------------------------- */
/* Model.__init__ + Sequencer.__init__ + Channel.__init__ */
void usd_init_at(struct usd *m, usd_write_fn write_fn, void *ctx, uint64_t clk, uint32_t phase_a,
                 uint32_t phase_b, unsigned tempo)
{
    int i;
    memset(m, 0, sizeof *m);
    m->write = write_fn;
    m->ctx = ctx;
    m->clk = clk;
    m->reg24 = (uint8_t)(tempo & 0xFF);
    m->reg25 = (uint8_t)((tempo >> 8) & 3);
    m->reg26 = 0xDF;
    m->next_a = clk + phase_a;
    m->next_b = clk + phase_b;
    m->enable = 3;
    m->t0 = clk;
    for (i = 0; i < USD_CHANNELS; i++) {
        struct usd_channel *c = &m->ch[i];
        c->is_fm = i < 3;
        c->number = (uint8_t)(i < 3 ? i : i - 3);
        c->pitch_lfo.kind = USD_LFO_PITCH;
        c->vol_lfo.kind = (uint8_t)(c->is_fm ? USD_LFO_FMVOL : USD_LFO_SSGVOL);
        c->noise_lfo.kind = USD_LFO_NOISE;
        c->env_state = USD_ENV_ATTACK;
    }
    m->mixer = 0xBF;
}

/* Model() */
void usd_init(struct usd *m, usd_write_fn write_fn, void *ctx)
{
    usd_init_at(m, write_fn, ctx, USD_START_CLK, USD_START_PHASE_A, USD_START_PHASE_B,
                USD_START_TEMPO);
}

/* Model.period_a / period_b (drv §4.2) */
static uint64_t usd_period_a(const struct usd *m)
{
    return 72u * (uint64_t)(1024 - (((unsigned)m->reg24 << 2) | (m->reg25 & 3u)));
}

static uint64_t usd_period_b(const struct usd *m)
{
    return 1152u * (uint64_t)(256u - m->reg26);
}

/* Model._full_volume */
static void usd_full_volume(struct usd *m)
{
    usd_seq_set_fade(m, 0, 0, 0);
}

/* Model._start: bind the loaded song and start it (drv §5.1). The result of the priority
 * check does not matter, as in the original */
static int usd_start_song(struct usd *m)
{
    struct usd_track t[6];
    uint8_t owner;
    int n;
    if (!m->song_loaded)
        return 0;
    n = usd_bind(m, 0, &owner, t);
    if (!n)
        return 0;
    m->t0 = m->clk;
    m->atick = 0;
    usd_seq_start(m, owner, t, n);
    return 1;
}

/* Model.stop: AH=02h */
void usd_stop(struct usd *m)
{
    usd_seq_stop(m, 0);
    usd_full_volume(m);
}

/* Model.stop_owner: AH=84h (internal), DX = 0 all, else priority limit */
void usd_stop_owner(struct usd *m, int owner)
{
    usd_seq_stop(m, owner);
    usd_full_volume(m);
}

/* Model.load: AH=00h; the bytes beyond `size` keep what the buffer held, as in AdvBIOS */
void usd_load(struct usd *m, const uint8_t *data, uint32_t size)
{
    usd_stop(m);
    if (size > USD_SONG_SIZE)
        size = USD_SONG_SIZE;
    if (size)
        memcpy(m->mem, data, size);
    m->song_loaded = 1;
}

/* Model.load_bank: AH=10h (drv §7) */
void usd_load_bank(struct usd *m, const uint8_t *data, uint32_t size)
{
    usd_stop(m);
    if (size > USD_BANK_SIZE)
        size = USD_BANK_SIZE;
    if (size)
        memcpy(m->mem + USD_BANK_BASE, data, size);
    m->bank_loaded = 1;
}

/* Model.play_se: AH=11h (drv §7); the index is BX, a 16-bit unsigned value */
int usd_play_se(struct usd *m, int index)
{
    struct usd_track t[6];
    uint32_t i = (uint32_t)index & 0xFFFFu;
    uint8_t owner;
    int n;
    if (!(m->enable & 2) || !m->bank_loaded || i >= usd_word(m, USD_BANK_BASE))
        return 0;
    n = usd_bind(m, USD_BANK_BASE + 2 + usd_word(m, USD_BANK_BASE + 2 + 2 * i), &owner, t);
    if (!n)
        return 0;
    usd_seq_start(m, owner, t, n);
    return 1;
}

/* Model.play: AH=01h */
int usd_play(struct usd *m)
{
    if (m->enable & 1) {
        usd_full_volume(m);
        return usd_start_song(m);
    }
    return 0;
}

/* Model.volume: AH=07h */
int usd_volume(struct usd *m, int offset)
{
    if (m->enable & 1) {
        usd_seq_set_fade(m, 0, offset, 0);
        return usd_start_song(m);
    }
    return 0;
}

/* Model.fade_out: AH=03h */
void usd_fade_out(struct usd *m)
{
    usd_full_volume(m);
    usd_seq_set_fade(m, 7, -1, 0);
}

/* Model.fade_in: AH=04h */
void usd_fade_in(struct usd *m)
{
    if (m->enable & 1) {
        usd_seq_set_fade(m, 0, USD_MASTER_MIN, 0);
        usd_start_song(m);
        usd_seq_set_fade(m, 7, 1, 0);
    }
}

/* Model.fade: AH=05h */
void usd_fade(struct usd *m, int period, int step, int priority)
{
    usd_seq_set_fade(m, period, step, priority);
}

/* Model.set_enable: AH=06h, AL=0 */
int usd_set_enable(struct usd *m, int mask)
{
    int old = m->enable;
    m->enable = (uint8_t)((unsigned)mask & 3u);
    if (!(m->enable & 1))
        usd_stop(m);
    return old;
}

uint64_t usd_clock(const struct usd *m)
{
    return m->clk;
}

uint64_t usd_next_event(const struct usd *m)
{
    return m->next_a < m->next_b ? m->next_a : m->next_b;
}

/* Model.step: advance to the next timer overflow and run the interrupt (both timers in one
 * interrupt when they coincide) */
int usd_step(struct usd *m)
{
    uint64_t t = usd_next_event(m);
    int flags = 0;
    if (m->next_a == t) {
        m->next_a += usd_period_a(m);
        flags |= 1;
    }
    if (m->next_b == t) {
        m->next_b += usd_period_b(m);
        flags |= 2;
    }
    m->clk = t;
    if (flags & 1)
        m->atick++;
    usd_seq_interrupt(m, flags);
    return flags;
}

/* Model.run(seconds=...): every event with time <= until, then the clock is `until` (never
 * moved backwards; the model's end is never before its clock) */
void usd_run_until(struct usd *m, uint64_t until)
{
    while (usd_next_event(m) <= until)
        usd_step(m);
    if (until > m->clk)
        m->clk = until;
}

uint32_t usd_aticks(const struct usd *m)
{
    return m->atick;
}

/* any(Model.active()) */
int usd_active(const struct usd *m)
{
    int i;
    for (i = 0; i < USD_CHANNELS; i++)
        if (m->ch[i].owner)
            return 1;
    return 0;
}
