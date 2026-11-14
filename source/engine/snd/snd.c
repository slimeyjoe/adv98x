/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Sound output (snd.h), after Xenon's snd_api.c. The sequencer stamps each register write with
 * its OPN clock (1/3 993 600 s); rendering maps the clocks to output samples and applies each
 * write before the sample it falls on. Writes of one timer interrupt come at one clock; they
 * reach the core at least one chip sample (72 master clocks) apart, as the bus allows on the
 * board, so that a key-off and a key-on of the same channel re-attack. */
#include <string.h>
#include "ax_internal.h"
#include "snd/snd.h"
#include "snd/usd.h"
#include "snd/opn_core.h"

#define WQ_SIZE 2048
#define RENDER_MAX 2048

static struct usd g_usd;
static const struct opn_core_ops *g_ops;
static struct opn_core *g_core;
static uint32_t g_rate;
static int g_audio;                     /* audio output open */
static uint64_t g_clock0;               /* sequencer clock of output sample 0 */
static uint64_t g_samples;              /* output samples rendered */
static uint64_t g_bus;                  /* 16.16 absolute sample: the bus is free from here */
static uint32_t g_cost;                 /* 16.16 samples per register write (rate / 55 467) */
static int32_t g_gain = 256;            /* cfg.volume as x/256 (music and effects: one chip) */
static struct { uint64_t clock; uint8_t reg, val; } g_wq[WQ_SIZE];
static unsigned g_head, g_tail;
static int16_t g_buf[RENDER_MAX];

#define LOCK()   do { if (ax.hal->audio_lock) ax.hal->audio_lock(); } while (0)
#define UNLOCK() do { if (ax.hal->audio_unlock) ax.hal->audio_unlock(); } while (0)

void snd_lock(void) { LOCK(); }
void snd_unlock(void) { UNLOCK(); }

struct usd *snd_usd(void)
{
    return &g_usd;
}

uint32_t snd_rate(void)
{
    return g_audio ? g_rate : 0;
}

static void on_write(void *ctx, uint64_t clock, int reg, int val)
{
    unsigned next = (g_tail + 1) % WQ_SIZE;
    (void)ctx;
    if (next == g_head) {               /* full: apply the oldest now */
        if (g_core)
            g_ops->write(g_core, g_wq[g_head].reg, g_wq[g_head].val);
        g_head = (g_head + 1) % WQ_SIZE;
    }
    g_wq[g_tail].clock = clock;
    g_wq[g_tail].reg = (uint8_t)reg;
    g_wq[g_tail].val = (uint8_t)val;
    g_tail = next;
}

/* the output sample (16.16, absolute) a sequencer clock falls on */
static uint64_t sample_of(uint64_t clock)
{
    if (clock <= g_clock0)
        return 0;
    return ((clock - g_clock0) * (uint64_t)g_rate << 16) / USD_CLOCK;
}

static void render(int16_t *pcm, int frames)
{
    uint64_t end = g_samples + (uint64_t)frames;
    int pos = 0;
    usd_run_until(&g_usd, g_clock0 + (end * USD_CLOCK + g_rate - 1) / g_rate);
    while (pos < frames) {
        int upto = frames;
        if (g_head != g_tail) {
            uint64_t at = sample_of(g_wq[g_head].clock);
            if (at < g_bus)
                at = g_bus;
            if ((at >> 16) < end) {
                int k = (int)((at >> 16) - g_samples);
                if (k <= pos) {
                    if (g_core)
                        g_ops->write(g_core, g_wq[g_head].reg, g_wq[g_head].val);
                    g_head = (g_head + 1) % WQ_SIZE;
                    g_bus = at + g_cost;
                    continue;
                }
                upto = k;
            }
        }
        if (g_core) {
            g_ops->render(g_core, pcm + pos, upto - pos);
            if (g_gain != 256) {
                int i;
                for (i = pos; i < upto; i++)
                    pcm[i] = (int16_t)(((int32_t)pcm[i] * g_gain) / 256);
            }
        } else {
            memset(pcm + pos, 0, sizeof(int16_t) * (size_t)(upto - pos));
        }
        pos = upto;
    }
    g_samples = end;
}

void ax_audio_render(int16_t *pcm, int frames)
{
    LOCK();
    if (g_audio)
        render(pcm, frames);
    else
        memset(pcm, 0, (size_t)frames * sizeof *pcm);
    UNLOCK();
}

/* what AdvBIOS's start-up wrote before the model takes over (usd-driver.md §3: SSG outputs
 * off, FM keys off, timers A and B programmed and started) */
static void boot_writes(void)
{
    static const uint8_t boot[][2] = {
        { 0x07, 0xBF }, { 0x28, 0x00 }, { 0x28, 0x01 }, { 0x28, 0x02 },
        { 0x24, 0x47 }, { 0x25, 0x03 }, { 0x26, 0xDF }, { 0x27, 0x0F }
    };
    unsigned i;
    for (i = 0; i < sizeof boot / sizeof boot[0]; i++)
        g_ops->write(g_core, boot[i][0], boot[i][1]);
}

void snd_init(void)
{
    uint32_t rate = 0;
    g_audio = 0;
    g_core = 0;
    g_head = g_tail = 0;
    usd_init(&g_usd, on_write, 0);
    if (ax.cfg.audio_rate <= 0)
        return;
#ifdef AX_HAVE_YMFM
    g_ops = &opn_ymfm_ops;
#else
    g_ops = &opn_lite_ops;
#endif
    g_core = g_ops->create(USD_CLOCK, (uint32_t)ax.cfg.audio_rate, &rate);
    if (!g_core)
        return;
    boot_writes();
    g_gain = ax.cfg.volume > 0 && ax.cfg.volume <= 100 ? ax.cfg.volume * 256 / 100 :
             ax.cfg.volume < 0 ? 0 : 256;
    g_rate = (uint32_t)ax.hal->audio_open((int)rate);
    if (!g_rate) {
        g_ops->destroy(g_core);
        g_core = 0;
        return;
    }
    g_cost = (uint32_t)(((uint64_t)g_rate << 16) / (USD_CLOCK / 72));
    g_clock0 = usd_clock(&g_usd);
    g_samples = 0;
    g_bus = 0;
    g_audio = 1;
}

/* the machine's reset: the chip and the sequencer as at start-up, the output stays open */
void snd_reset(void)
{
    LOCK();
    g_head = g_tail = 0;
    usd_init(&g_usd, on_write, 0);
    if (g_core) {
        g_ops->reset(g_core);
        boot_writes();
    }
    g_clock0 = usd_clock(&g_usd);
    g_samples = 0;
    g_bus = 0;
    UNLOCK();
}

void snd_shutdown(void)
{
    if (g_audio)
        ax.hal->audio_close();
    if (g_core)
        g_ops->destroy(g_core);
    g_core = 0;
    g_audio = 0;
}

/* push mode: what the sink can take now */
void snd_pump(void)
{
    int n;
    if (!g_audio || ax.hal->audio_lock || !ax.hal->audio_space)
        return;
    while ((n = ax.hal->audio_space()) > 0) {
        if (n > RENDER_MAX)
            n = RENDER_MAX;
        render(g_buf, n);
        ax.hal->audio_push(g_buf, n);
    }
}
