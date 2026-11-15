/* SPDX-License-Identifier: GPL-3.0-or-later */
/* INT F4h, sound (docs/re/advbios.md §4.6, usd-driver.md): the driver's entry points over the
 * sequencer (snd/usd.c). Files are read as AdvBIOS reads them (INT F2h AH=00h); the sequencer
 * keeps its own copy, as the driver's segment 2B0F holds it. */
#include "ax.h"
#include "bios/bios.h"

static uint8_t filebuf[0x8000];

static long read_song(const char *name)
{
    return bios_file_load(name, filebuf, sizeof filebuf);
}

/* AH=00h: stop everything, read the file; playback starts with AH=01h */
void snd_load_play(const char *name)
{
    long n = read_song(name);
    lrv_sys_trace(&ax.sys, AX_TR_SOUND, name, 0, 0x00, 0, 0, 0);
    if (n < 0)
        return;
    lrv_mixer_lock(&ax.mixer);
    usd_load(&ax.usd, filebuf, (uint32_t)n);
    lrv_mixer_unlock(&ax.mixer);
}

void snd_play(void)
{
    lrv_sys_trace(&ax.sys, AX_TR_SOUND, 0, 0, 0x01, 0, 0, 0);
    lrv_mixer_lock(&ax.mixer);
    usd_play(&ax.usd);
    lrv_mixer_unlock(&ax.mixer);
}

void snd_stop(void)
{
    lrv_sys_trace(&ax.sys, AX_TR_SOUND, 0, 0, 0x02, 0, 0, 0);
    lrv_mixer_lock(&ax.mixer);
    usd_stop(&ax.usd);
    lrv_mixer_unlock(&ax.mixer);
}

/* AH=03h / 04h: the speed in DL is ignored by the driver (fixed rate, advbios.md §4.6) */
void snd_fade_out(int speed)
{
    lrv_sys_trace(&ax.sys, AX_TR_SOUND, 0, 0, 0x03, speed, 0, 0);
    lrv_mixer_lock(&ax.mixer);
    usd_fade_out(&ax.usd);
    lrv_mixer_unlock(&ax.mixer);
}

void snd_fade_in(int speed)
{
    lrv_sys_trace(&ax.sys, AX_TR_SOUND, 0, 0, 0x04, speed, 0, 0);
    lrv_mixer_lock(&ax.mixer);
    usd_fade_in(&ax.usd);
    lrv_mixer_unlock(&ax.mixer);
}

void snd_volume(int offset)
{
    lrv_sys_trace(&ax.sys, AX_TR_SOUND, 0, 0, 0x07, offset, 0, 0);
    lrv_mixer_lock(&ax.mixer);
    usd_volume(&ax.usd, (int)(int16_t)offset);
    lrv_mixer_unlock(&ax.mixer);
}

void snd_effect_file(const char *name)
{
    long n = read_song(name);
    lrv_sys_trace(&ax.sys, AX_TR_SOUND, name, 0, 0x10, 0, 0, 0);
    if (n < 0)
        return;
    lrv_mixer_lock(&ax.mixer);
    usd_load_bank(&ax.usd, filebuf, (uint32_t)n);
    lrv_mixer_unlock(&ax.mixer);
}

void snd_effect(int n)
{
    lrv_sys_trace(&ax.sys, AX_TR_SOUND, 0, 0, 0x11, n, 0, 0);
    lrv_mixer_lock(&ax.mixer);
    usd_play_se(&ax.usd, n);
    lrv_mixer_unlock(&ax.mixer);
}
