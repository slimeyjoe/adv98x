/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Glyph tables (XFNT, tools/xfont.py) and the kanji ROM read (font.h). From Xenon's font.c. */
#include <string.h>
#include "ax_internal.h"
#include "text/font.h"
#include "util/endian.h"

struct xfnt {
    uint8_t *data;
    uint32_t size;
    int cell_w, cell_h, count, glyph_bytes;
    const uint8_t *codes;               /* count x u16 LE, sorted */
    const uint8_t *glyphs;
};

static struct xfnt font16, font8;

static int font_load(struct xfnt *f, const char *name, int cell_w)
{
    const struct xpak_entry *e = xpak_find(&ax.pak, name, XPAK_T_FONT);
    if (!e)
        return 0;
    f->data = xpak_load(&ax.pak, e, &f->size);
    if (!f->data || f->size < 12 || memcmp(f->data, "XFNT", 4) != 0)
        return 0;
    f->cell_w = f->data[5];
    f->cell_h = f->data[6];
    f->count = rd16le(f->data + 8);
    f->codes = f->data + 12;
    f->glyph_bytes = f->cell_h * f->cell_w / 8;
    f->glyphs = f->codes + 2 * f->count;
    if (f->cell_w != cell_w || f->cell_h != 16 ||
        12u + (uint32_t)f->count * (2u + (uint32_t)f->glyph_bytes) > f->size)
        return 0;
    return 1;
}

static const uint8_t *font_glyph(const struct xfnt *f, unsigned code)
{
    int lo = 0, hi = f->count - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        unsigned c = rd16le(f->codes + 2 * mid);
        if (c == code)
            return f->glyphs + mid * f->glyph_bytes;
        if (c < code)
            lo = mid + 1;
        else
            hi = mid - 1;
    }
    return 0;
}

void font_init(void)
{
    if (!font_load(&font16, "font16", 16))
        sys_fatal("font16 missing from the pack");
    if (!font_load(&font8, "font8", 8))
        sys_fatal("font8 missing from the pack");
}

void font_shutdown(void)
{
    if (font16.data)
        xpak_free(&ax.pak, font16.data, font16.size);
    if (font8.data)
        xpak_free(&ax.pak, font8.data, font8.size);
    memset(&font16, 0, sizeof font16);
    memset(&font8, 0, sizeof font8);
}

int font_rom_glyph(unsigned jis, uint8_t rows[32])
{
    unsigned row = (jis >> 8) & 0xFF, cell = jis & 0xFF;
    const uint8_t *g;
    memset(rows, 0, 32);
    if (row == 0x29 || row == 0x2A || row == 0x2B) {
        g = row == 0x2B ? 0 : font_glyph(&font8, row == 0x29 ? cell : (cell + 0x80) & 0xFF);
        if (g)
            memcpy(rows, g, 16);
        return 1;
    }
    g = font_glyph(&font16, jis & 0xFFFF);
    if (g)
        memcpy(rows, g, 32);
    return 2;
}
