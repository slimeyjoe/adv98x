/* SPDX-License-Identifier: GPL-3.0-or-later */
/* INT F4h, sound (docs/re/advbios.md §4.6, usd-driver.md). The USD sequencer and the OPN
 * output arrive with milestone M4; until then the calls are traced and do nothing. */
#include "ax_internal.h"
#include "bios/bios.h"

void snd_load_play(const char *name) { sys_trace(AX_TR_SOUND, name, 0, 0x00, 0, 0, 0); }
void snd_play(void) { sys_trace(AX_TR_SOUND, 0, 0, 0x01, 0, 0, 0); }
void snd_stop(void) { sys_trace(AX_TR_SOUND, 0, 0, 0x02, 0, 0, 0); }
void snd_fade_out(int speed) { sys_trace(AX_TR_SOUND, 0, 0, 0x03, speed, 0, 0); }
void snd_fade_in(int speed) { sys_trace(AX_TR_SOUND, 0, 0, 0x04, speed, 0, 0); }
void snd_volume(int offset) { sys_trace(AX_TR_SOUND, 0, 0, 0x07, offset, 0, 0); }
void snd_effect_file(const char *name) { sys_trace(AX_TR_SOUND, name, 0, 0x10, 0, 0, 0); }
void snd_effect(int n) { sys_trace(AX_TR_SOUND, 0, 0, 0x11, n, 0, 0); }
