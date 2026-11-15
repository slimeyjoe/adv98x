/* SPDX-License-Identifier: GPL-3.0-or-later */
/* USDdrv / USDtrap V01.02, AdvBIOS's music driver for the YM2203: the .USO sequencer, the two OPN
 * timers and the INT F4h music services. The C port of the verified clean-room model
 * re-tools/usdmodel.py (Lfo, Channel, FmChannel, SsgChannel, Sequencer, bind, Model), which
 * produces the original driver's register writes write for write and clock for clock
 * (docs/re/usd-sequencer.md, docs/re/usd-driver.md; tests/check_usd.py checks this port
 * against the model and the original's recordings).
 *
 * The model does not render sound: it calls `write` for every OPN register write, stamped with
 * its clock in OPN master clocks (USD_CLOCK per second). Time only moves in usd_step /
 * usd_run_until; the services (usd_play, ...) act at the current clock. Everything lives in
 * struct usd (no allocation, no globals, no pointers into itself: it may be copied). */
#ifndef AX_SND_USD_H
#define AX_SND_USD_H

#include <stdint.h>

#define USD_CLOCK 3993600u                  /* OPN master clocks per second */

#define USD_SONG_SIZE 0x3000u               /* AdvBIOS's music buffer D:0000 (AH=00h) */
#define USD_BANK_SIZE 0x2000u               /* the effect bank D:3000 (AH=10h) */
#define USD_MEM_SIZE (USD_SONG_SIZE + USD_BANK_SIZE)
#define USD_FM_VOICE_SIZE 39
#define USD_SSG_VOICE_SIZE 30
#define USD_CHANNELS 6                      /* 0..2 FM 1-3, 3..5 SSG 1-3 */

/* the state usdemu.py's AdvBIOS start-up leaves (Model() defaults) */
#define USD_START_CLK 4246760u
#define USD_START_PHASE_A 5920u
#define USD_START_PHASE_B 11032u
#define USD_START_TEMPO 0x0347u

typedef void (*usd_write_fn)(void *ctx, uint64_t clock, int reg, int val);

/* Lfo: one of the five modulators (usd-sequencer.md §10) */
enum { USD_LFO_PITCH, USD_LFO_FMVOL, USD_LFO_SSGVOL, USD_LFO_NOISE };

struct usd_lfo {
    uint8_t kind;                           /* USD_LFO_* */
    uint8_t type, delay, speed, count;      /* parameters from the voice record */
    int16_t depth;
    uint8_t phase;                          /* 0 = not started since the last note-on, else 1 / 2 */
    uint8_t wait;                           /* remaining delay */
    uint8_t speed_ctr, count_ctr;
    int16_t acc;
};

/* Channel / FmChannel / SsgChannel (usd-sequencer.md §3) */
struct usd_channel {
    uint8_t is_fm;
    uint8_t number;                         /* 0..2 inside its kind */
    uint8_t owner;                          /* 0 = idle; bit 0: clocked by timer A, bit 1: by B */
    uint8_t priority;
    uint8_t keyed;                          /* note sounding (flag bit 0) */
    uint8_t porta;                          /* bit 1 */
    uint8_t tie;                            /* bit 4 (also: already released by the gate) */
    int8_t note;
    uint8_t gate_mode;
    uint8_t transpose;
    int8_t detune;
    uint8_t porta_step;
    int8_t volume;
    uint16_t counter;
    uint16_t gate;
    int16_t pitch;
    int16_t target;
    uint32_t data;                          /* the song image: offset in usd.mem */
    uint32_t pos;                           /* next byte, relative to `data` (16-bit wrap) */
    uint32_t voices;                        /* the track's voice table: offset in usd.mem */
    uint8_t has_voices;                     /* 0: the file has no block of this kind */
    uint8_t loops[4];
    struct usd_lfo pitch_lfo, vol_lfo, noise_lfo;     /* noise_lfo: SSG only */
    uint8_t pitch_lfo_on, vol_lfo_on, noise_lfo_on;
    uint8_t voice[USD_FM_VOICE_SIZE];       /* the record last loaded (SSG: the first 30 bytes) */
    uint8_t mixer;                          /* SSG: mixer bits the voice opens */
    uint8_t env_state;                      /* SSG envelope: USD_ENV_* (usd.c) */
    int16_t env_level;
};

struct usd {
    /* Model: the two YM2203 timers and the INT F4h services */
    usd_write_fn write;
    void *ctx;
    uint64_t clk;                           /* current time, master clocks */
    uint64_t next_a, next_b;                /* next timer-A / timer-B overflow */
    uint64_t t0;                            /* clock of the last song start */
    uint32_t atick;                         /* timer-A interrupts since the last song start */
    uint8_t reg24, reg25, reg26;            /* the timer registers as the chip holds them */
    uint8_t enable;                         /* AH=06h mask: bit 0 music, bit 1 effects */
    uint8_t song_loaded, bank_loaded;
    /* Sequencer */
    struct usd_channel ch[USD_CHANNELS];
    uint8_t mixer;                          /* shadow of SSG register 07h */
    int16_t master;                         /* volume offset, 0 (full) .. -64 */
    uint16_t fade_period, fade_count;
    int16_t fade_step;
    uint8_t fade_priority;
    uint8_t tempo_pending;                  /* tempo_request is not None */
    uint16_t tempo_request;                 /* timer-A word waiting for the next interrupt */
    /* the song (AH=00h) at 0, the effect bank (AH=10h) at USD_SONG_SIZE, as AdvBIOS holds
     * them in its music segment; a load overwrites only the bytes it copies */
    uint8_t mem[USD_MEM_SIZE];
};

/* Model(): clk 4246760, phase (5920, 11032), tempo 0x0347 - the state after AdvBIOS start-up
 * (its built-in init sequence has run: the model writes nothing here) */
void usd_init(struct usd *m, usd_write_fn write_fn, void *ctx);
/* Model(clk, phase=(phase_a, phase_b), tempo): `phase_*` = clocks until the next overflow of
 * timer A / timer B, `tempo` = the timer-A word in force */
void usd_init_at(struct usd *m, usd_write_fn write_fn, void *ctx, uint64_t clk, uint32_t phase_a,
                 uint32_t phase_b, unsigned tempo);
/* AH=00h load (copies up to 0x3000 bytes into the model's own buffer, as AdvBIOS's music
 * buffer holds them), AH=10h load_bank (up to 0x2000 bytes); both stop everything first */
void usd_load(struct usd *m, const uint8_t *data, uint32_t size);
void usd_load_bank(struct usd *m, const uint8_t *data, uint32_t size);
int usd_play(struct usd *m);                /* AH=01h, returns the Python's bool */
int usd_volume(struct usd *m, int offset);  /* AH=07h */
void usd_fade_out(struct usd *m);           /* AH=03h */
void usd_fade_in(struct usd *m);            /* AH=04h */
void usd_fade(struct usd *m, int period, int step, int priority);  /* AH=05h */
void usd_stop(struct usd *m);               /* AH=02h */
void usd_stop_owner(struct usd *m, int owner);  /* AH=84h: 0 = all, else priority limit */
int usd_play_se(struct usd *m, int index);  /* AH=11h */
int usd_set_enable(struct usd *m, int mask);    /* AH=06h AL=0, returns the old mask */
uint64_t usd_clock(const struct usd *m);    /* Model.clk */
uint64_t usd_next_event(const struct usd *m);   /* min(next_a, next_b) */
int usd_step(struct usd *m);                /* Model.step(): one timer event, returns flags */
/* Model.run(seconds=...) generalised: run every event with time <= `until`, then clk = until */
void usd_run_until(struct usd *m, uint64_t until);
uint32_t usd_aticks(const struct usd *m);   /* Model.atick */
int usd_active(const struct usd *m);        /* any channel with an owner (Model.active()) */

#endif
