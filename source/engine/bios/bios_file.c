/* SPDX-License-Identifier: GPL-3.0-or-later */
/* INT F2h, files and disks (docs/re/advbios.md §4.4, §8). All files are on one medium: the
 * drive letter and directories of a name are dropped, the drive selection is kept as state but
 * never prompts (docs/re/disks.md §3, the "simpler alternative"). FLAG0..FLAG9 and NAME.DEF
 * are the player's records (HAL storage); everything else is read from the pack by base name,
 * the type from the extension, scripts in the current language. */
#include <string.h>
#include "ax_internal.h"
#include "bios/bios.h"

/* base name (no drive, no directories) upper-cased into out; returns the extension or "" */
static const char *base_name(const char *name, char *out, size_t cap)
{
    const char *p = name, *b = name;
    size_t i = 0;
    char *dot;
    for (; *p; p++)
        if (*p == '\\' || *p == '/' || *p == ':')
            b = p + 1;
    for (; *b && i + 1 < cap; b++, i++)
        out[i] = (char)(*b >= 'a' && *b <= 'z' ? *b - 32 : *b);
    out[i] = 0;
    dot = strrchr(out, '.');
    if (!dot)
        return "";
    *dot = 0;
    return dot + 1;
}

static int is_record(const char *base, const char *ext)
{
    if (!strcmp(base, "NAME") && !strcmp(ext, "DEF"))
        return 1;
    return !ext[0] && !strncmp(base, "FLAG", 4) && base[4] >= '0' && base[4] <= '9' && !base[5];
}

static int pack_type(const char *ext)
{
    if (!strcmp(ext, "MES")) return XPAK_T_MES;
    if (!strcmp(ext, "GPC")) return XPAK_T_GPC;
    if (!strcmp(ext, "USO")) return XPAK_T_USO;
    if (!strcmp(ext, "CLM")) return XPAK_T_CLM;
    return XPAK_T_BLOB;
}

static void record_key(const char *base, const char *ext, char *key, size_t cap)
{
    size_t n = strlen(base);
    if (n + 5 > cap)
        n = cap - 5;
    memcpy(key, base, n);
    key[n] = 0;
    if (ext[0]) {
        key[n] = '.';
        strcpy(key + n + 1, ext);
    }
}

/* AH=05h: at most `max` bytes; returns the length, -1 when the file cannot be read */
long bios_file_read(const char *name, uint8_t *dst, uint32_t max)
{
    char base[64], key[72];
    const char *ext = base_name(name, base, sizeof base);
    const struct xpak_entry *e;
    if (is_record(base, ext)) {
        size_t len = 0;
        record_key(base, ext, key, sizeof key);
        if (ax.hal->storage_read(key, dst, max, &len) != 0)
            return -1;
        return (long)len;
    }
    e = xpak_find(&ax.pak, base, pack_type(ext));
    if (!e) {
        sys_log(AX_LOG_WARN, "file: %s not found", name);
        return -1;
    }
    return (long)xpak_read(&ax.pak, e, 0, dst, e->size < max ? e->size : max);
}

/* AH=00h: the whole file (the original has no limit; `cap` is what the destination holds) */
long bios_file_load(const char *name, uint8_t *dst, uint32_t cap)
{
    return bios_file_read(name, dst, cap);
}

/* AH=01h: returns the bytes written, -1 on failure */
long bios_file_write(const char *name, const uint8_t *src, uint32_t n)
{
    char base[64], key[72];
    const char *ext = base_name(name, base, sizeof base);
    if (!is_record(base, ext)) {
        sys_log(AX_LOG_WARN, "file: refusing to write %s", name);
        return -1;
    }
    record_key(base, ext, key, sizeof key);
    if (ax.hal->storage_write(key, src, n) != 0)
        return -1;
    sys_trace(AX_TR_SAVE, key, 0, 0, (int)n, 0, 0);
    return (long)n;
}

void bios_select_drive(int slot, int value)
{
    ax.bios.drive[slot & 1] = (uint8_t)value;
}
