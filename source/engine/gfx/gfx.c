/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Graphics: VRAM pages and the palette with brightness (gfx.h). */
#include <string.h>
#include "ax_internal.h"
#include "gfx/gfx.h"

#define STRIDE AX_PLANE_STRIDE

/* INT F3h AH=10h, 0290:047C */
const uint16_t gfx_default_palette[16] = {
    0x000, 0x007, 0x070, 0x077, 0x700, 0x707, 0x770, 0x777,
    0x333, 0x00F, 0x0F0, 0x0FF, 0xF00, 0xF0F, 0xFF0, 0xFFF
};

void gfx_init(void)
{
    int p;
    ax.planemem = sys_alloc(2 * 4 * AX_PLANE_BYTES);
    for (p = 0; p < 4; p++) {
        ax.page[0].p[p] = ax.planemem + (0 * 4 + p) * AX_PLANE_BYTES;
        ax.page[1].p[p] = ax.planemem + (1 * 4 + p) * AX_PLANE_BYTES;
    }
    ax_rect_clear(&ax.dirty[0]);
    ax_rect_clear(&ax.dirty[1]);
    ax.access_page = 0;
    ax.display_page = 0;
    ax.page_switched = 1;
    ax.graphics_on = 1;
    memcpy(ax.palette, gfx_default_palette, sizeof ax.palette);
    ax.brightness = 15;
    gfx_set_brightness(15);
}

void gfx_shutdown(void)
{
    sys_free(ax.planemem, 2 * 4 * AX_PLANE_BYTES);
    ax.planemem = 0;
}

void gfx_set_access_page(int p)
{
    ax.access_page = p ? 1 : 0;
}

void gfx_set_display_page(int p)
{
    p = p ? 1 : 0;
    if (p != ax.display_page) {
        ax.display_page = p;
        ax.page_switched = 1;
    }
}

void gfx_graph_on(int on)
{
    if (on != ax.graphics_on)
        ax.page_switched = 1;
    ax.graphics_on = on;
}

struct ax_planes *gfx_access(void)
{
    return &ax.page[ax.access_page];
}

void gfx_mark_dirty(int page, int x0, int y0, int x1, int y1)
{
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 > STRIDE) x1 = STRIDE;
    if (y1 > AX_SCREEN_H) y1 = AX_SCREEN_H;
    ax_rect_add(&ax.dirty[page], x0, y0, x1, y1);
}

/* a rectangle written into planes that may be a VRAM page */
void gfx_mark_planes(const struct ax_planes *pl, const struct ax_rect *r)
{
    int pg;
    for (pg = 0; pg < 2; pg++)
        if (pl->p[0] == ax.page[pg].p[0] && !ax_rect_empty(r))
            gfx_mark_dirty(pg, r->x0, r->y0, r->x1, r->y1);
}

void gfx_clear_page(void)
{
    struct ax_planes *pg = gfx_access();
    int p;
    for (p = 0; p < 4; p++)
        memset(pg->p[p], 0, AX_PLANE_BYTES);
    gfx_mark_dirty(ax.access_page, 0, 0, STRIDE, AX_SCREEN_H);
}

/* ---- palette and brightness (advbios.md §5.7) ------------------------------------------- */

/* the 16 x 16 table at 0290:049C: T[L][v] = round(v * L / 15), halves rounded up (verified
 * against all 256 entries) */
int gfx_bright(int v, int level)
{
    return (v * level * 2 + 15) / 30;
}

void gfx_set_palette(const uint16_t pal[16])
{
    memcpy(ax.palette, pal, sizeof ax.palette);
}

/* hardware colour i from the buffer: out A8h,i; AAh,T[g]; ACh,T[r]; AEh,T[b] */
void gfx_program_colour(int i, int level)
{
    uint16_t w = ax.palette[i & 15];
    int r = (w >> 4) & 15, g = (w >> 8) & 15, b = w & 15;
    if (level < 0) level = 0;
    if (level > 15) level = 15;
    ax.dac[(i & 15) * 3] = (uint8_t)gfx_bright(r, level);
    ax.dac[(i & 15) * 3 + 1] = (uint8_t)gfx_bright(g, level);
    ax.dac[(i & 15) * 3 + 2] = (uint8_t)gfx_bright(b, level);
    ax.dac_changed = 1;
}

/* INT F3h AH=11h without its VSYNC wait (the caller waits a frame where the original did) */
void gfx_set_brightness(int level)
{
    int i;
    if (level < 0) level = 0;
    if (level > 15) level = 15;
    ax.brightness = level;
    for (i = 0; i < 16; i++)
        gfx_program_colour(i, level);
}

void gfx_update_dac(void)
{
    ax.dac_changed = 0;
}
