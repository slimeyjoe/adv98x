/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Sound output: the USD sequencer (snd/usd.c) driving an OPN core (snd/opn_core.h), rendered
 * in sample time. The original ran the sequencer from the YM2203's timer interrupts,
 * independent of the game; here the sequencer advances with the samples rendered: from the
 * backend's audio thread (pull mode) or from the frame (push mode). */
#ifndef AX_SND_SND_H
#define AX_SND_SND_H

#include <stdint.h>

void snd_init(void);
void snd_shutdown(void);
void snd_reset(void);                   /* the machine's reset: silence, the driver as at start */
void snd_pump(void);                    /* push mode: render what the sink can take */
struct usd *snd_usd(void);              /* the sequencer, for bios_snd.c (lock held) */
uint32_t snd_rate(void);                /* the output rate, 0 without audio */
void snd_lock(void);
void snd_unlock(void);

#endif
