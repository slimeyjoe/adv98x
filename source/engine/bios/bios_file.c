/* SPDX-License-Identifier: GPL-3.0-or-later */
/* INT F2h, files and disks (docs/re/advbios.md §4.4, §8). All files are on one medium: the
 * drive letter and directories of a name are dropped, the drive selection is kept as state but
 * never prompts (docs/re/disks.md §3, the "simpler alternative"). A file of the game is in the
 * pack under its name, scripts in the current language; every other name is a record of the
 * player's (a save, the player's name) in the HAL's storage, which is also where the game
 * writes. */
#include <string.h>
#include "ax.h"
#include "bios/bios.h"

/* the file name without drive and directories, a-z upper-cased */
static void file_name(const char *name, char *out, size_t cap)
{
    const char *p = name, *b = name;
    size_t i = 0;
    for (; *p; p++)
        if (*p == '\\' || *p == '/' || *p == ':')
            b = p + 1;
    for (; *b && i + 1 < cap; b++, i++)
        out[i] = (char)(*b >= 'a' && *b <= 'z' ? *b - 32 : *b);
    out[i] = 0;
}

/* the pack's entry of a file of the game (an entry of one of the engine's types) */
static const struct lrv_pack_entry *game_file(const char *file)
{
    const struct lrv_pack_entry *e = lrv_pack_find(&ax.pack, file, LRV_PT_ANY);
    return e && e->type >= LRV_PT_ENGINE ? e : 0;
}

/* AH=05h: at most `max` bytes; returns the length, -1 when the file cannot be read */
long bios_file_read(const char *name, uint8_t *dst, uint32_t max)
{
    char file[64];
    const struct lrv_pack_entry *e;
    size_t len = 0;
    file_name(name, file, sizeof file);
    e = game_file(file);
    if (e)
        return (long)lrv_pack_read(&ax.pack, e, 0, dst, max);
    if (!file[0] || ax.hal->storage_read(file, dst, max, &len) != LRV_OK)
        return -1;
    return (long)len;
}

/* AH=00h: the whole file (the original has no limit; `cap` is what the destination holds) */
long bios_file_load(const char *name, uint8_t *dst, uint32_t cap)
{
    return bios_file_read(name, dst, cap);
}

/* AH=01h: returns the bytes written, -1 on failure */
long bios_file_write(const char *name, const uint8_t *src, uint32_t n)
{
    char file[64];
    file_name(name, file, sizeof file);
    if (!file[0] || game_file(file)) {
        lrv_log(ax.hal, LRV_LOG_WARN, "file: refusing to write %s", name);
        return -1;
    }
    if (ax.hal->storage_write(file, src, n) != LRV_OK)
        return -1;
    lrv_sys_trace(&ax.sys, AX_TR_SAVE, file, 0, 0, (int)n, 0, 0);
    return (long)n;
}

void bios_select_drive(int slot, int value)
{
    ax.bios.drive[slot & 1] = (uint8_t)value;
}
