/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Sound output (snd.h). The sequencer stamps each register write with its OPN clock
 * (1/3 993 600 s); the write queue maps the clocks to output samples and applies each write
 * before the sample it falls on. Writes of one timer interrupt come at one clock; they reach
 * the core at least one chip sample (72 master clocks) apart, as the bus allows on the board,
 * so that a key-off and a key-on of the same channel re-attack. */
#include <string.h>
#include "ax.h"
#include "snd/snd.h"

#define WQ_SIZE 2048

static void on_write(void *ctx, uint64_t clock, int reg, int val)
{
    (void)ctx;
    lrv_opnq_write_at(&ax.opnq, clock, (uint8_t)reg, (uint8_t)val);
}

static void run_until(void *ctx, uint64_t clock)
{
    (void)ctx;
    usd_run_until(&ax.usd, clock);
}

/* The driver as at start-up and the chip as AdvBIOS's start-up left it before the model takes
 * over (usd-driver.md §3: SSG outputs off, FM keys off, timers A and B programmed and started);
 * output sample 0 is the driver's clock now. */
static void boot(void)
{
    static const uint8_t writes[][2] = {
        { 0x07, 0xBF }, { 0x28, 0x00 }, { 0x28, 0x01 }, { 0x28, 0x02 },
        { 0x24, 0x47 }, { 0x25, 0x03 }, { 0x26, 0xDF }, { 0x27, 0x0F }
    };
    unsigned i;
    usd_init(&ax.usd, on_write, 0);
    for (i = 0; i < sizeof writes / sizeof writes[0]; i++)
        lrv_opnq_poke(&ax.opnq, writes[i][0], writes[i][1]);
    lrv_opnq_set_clock0(&ax.opnq, usd_clock(&ax.usd));
}

/* the write queue in front of a core (ops NULL: no chip) that renders at `rate` if it can */
static void chip(const struct lrv_opn_ops *ops, uint32_t rate)
{
    struct lrv_opnq_cfg qc;
    memset(&qc, 0, sizeof qc);
    qc.ops = ops;
    qc.clock_hz = USD_CLOCK;
    qc.rate = rate;
    qc.bus_clocks = LRV_OPN_FM_DIV;
    qc.queue_size = WQ_SIZE;
    qc.seq.run_until = run_until;
    if (lrv_opnq_init(&ax.opnq, ax.hal, &qc) != LRV_OK)
        lrv_fatal(ax.hal, "cannot create the sound chip");
}

void snd_open(const struct lrv_run_cfg *cfg, int device)
{
    struct lrv_mixer_cfg mc;
    uint32_t rate;

    memset(&mc, 0, sizeof mc);
    mc.render = lrv_opnq_render;
    mc.skip = lrv_opnq_skip;
    mc.ctx = &ax.opnq;
    lrv_mixer_init(&ax.mixer, ax.hal, &mc);
    /* a core may insist on its own rate (ymfm: the chip's, 55 466 Hz): the device is asked
     * for that; a device that insists on another gets the core that renders at any rate */
    chip(cfg->audio_rate > 0 ? lrv_opn_select(cfg->opn_core) : 0, (uint32_t)cfg->audio_rate);
    rate = lrv_opnq_rate(&ax.opnq);
    if (device && rate) {
        uint32_t got = (uint32_t)lrv_mixer_open(&ax.mixer, (int)rate);
        if (!got || (got != rate && lrv_opnq_set_rate(&ax.opnq, got) != got)) {
            lrv_opnq_free(&ax.opnq);
            chip(got ? &lrv_opn_lite_ops : 0, got);
        }
        rate = lrv_opnq_rate(&ax.opnq);
    }
    lrv_mixer_set_volume(&ax.mixer, cfg->volume < 0 ? 0 : cfg->volume ? cfg->volume : 100);
    boot();
    if (rate)
        lrv_mixer_start(&ax.mixer, rate);
}

void snd_reset(void)
{
    lrv_mixer_lock(&ax.mixer);
    lrv_opnq_reset(&ax.opnq);
    boot();
    lrv_mixer_unlock(&ax.mixer);
}

void snd_close(void)
{
    lrv_mixer_close(&ax.mixer);         /* first: the sequencer is not called after it */
    lrv_opnq_free(&ax.opnq);
}
