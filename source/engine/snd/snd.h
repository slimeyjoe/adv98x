/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Sound output: the USD sequencer (snd/usd.c) in front of an OPN core, rendered in sample time
 * by lrvne (lrvne/opnq.h, lrvne/mixer.h). The original ran the sequencer from the YM2203's
 * timer interrupts, independent of the game; here it advances with the samples rendered: from
 * the backend's audio thread where the backend pulls, from the frame where it is pushed. Every
 * call into the sequencer (ax.usd) from the game is therefore bracketed with lrv_mixer_lock /
 * lrv_mixer_unlock on ax.mixer (bios/bios_snd.c). */
#ifndef AX_SND_SND_H
#define AX_SND_SND_H

#include "lrvne/app.h"

/* The chip, the driver as AdvBIOS's start-up leaves it, and the output: the backend's audio
 * stream when `device` is set, else none (the mixer then only renders, for ax_render_music).
 * Without audio (cfg->audio_rate 0, or no device to be had) there is no chip and the driver's
 * clock stands still. */
void snd_open(const struct lrv_run_cfg *cfg, int device);
void snd_close(void);
void snd_reset(void);                   /* the machine's reset: silence, the driver as at start */

#endif
