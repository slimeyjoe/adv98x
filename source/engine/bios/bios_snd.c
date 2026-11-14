/* SPDX-License-Identifier: GPL-3.0-or-later */
/* INT F4h, sound (docs/re/advbios.md §4.6, usd-driver.md): the driver's entry points over the
 * sequencer (snd/usd.c). Files are read as AdvBIOS reads them (INT F2h AH=00h); the sequencer
 * keeps its own copy, as the driver's segment 2B0F holds it. */
#include "ax_internal.h"
#include "bios/bios.h"
#include "snd/snd.h"
#include "snd/usd.h"

static uint8_t filebuf[0x8000];

static long read_song(const char *name)
{
    return bios_file_load(name, filebuf, sizeof filebuf);
}

/* AH=00h: stop everything, read the file; playback starts with AH=01h */
void snd_load_play(const char *name)
{
    long n = read_song(name);
    sys_trace(AX_TR_SOUND, name, 0, 0x00, 0, 0, 0);
    if (n < 0)
        return;
    snd_lock();
    usd_load(snd_usd(), filebuf, (uint32_t)n);
    snd_unlock();
}

void snd_play(void)
{
    sys_trace(AX_TR_SOUND, 0, 0, 0x01, 0, 0, 0);
    snd_lock();
    usd_play(snd_usd());
    snd_unlock();
}

void snd_stop(void)
{
    sys_trace(AX_TR_SOUND, 0, 0, 0x02, 0, 0, 0);
    snd_lock();
    usd_stop(snd_usd());
    snd_unlock();
}

/* AH=03h / 04h: the speed in DL is ignored by the driver (fixed rate, advbios.md §4.6) */
void snd_fade_out(int speed)
{
    sys_trace(AX_TR_SOUND, 0, 0, 0x03, speed, 0, 0);
    snd_lock();
    usd_fade_out(snd_usd());
    snd_unlock();
}

void snd_fade_in(int speed)
{
    sys_trace(AX_TR_SOUND, 0, 0, 0x04, speed, 0, 0);
    snd_lock();
    usd_fade_in(snd_usd());
    snd_unlock();
}

void snd_volume(int offset)
{
    sys_trace(AX_TR_SOUND, 0, 0, 0x07, offset, 0, 0);
    snd_lock();
    usd_volume(snd_usd(), (int)(int16_t)offset);
    snd_unlock();
}

void snd_effect_file(const char *name)
{
    long n = read_song(name);
    sys_trace(AX_TR_SOUND, name, 0, 0x10, 0, 0, 0);
    if (n < 0)
        return;
    snd_lock();
    usd_load_bank(snd_usd(), filebuf, (uint32_t)n);
    snd_unlock();
}

void snd_effect(int n)
{
    sys_trace(AX_TR_SOUND, 0, 0, 0x11, n, 0, 0);
    snd_lock();
    usd_play_se(snd_usd(), n);
    snd_unlock();
}
