/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The mouse pointer (cursor.h). Shape: byte 0 width in bytes (1..5), byte 1 height (1..40),
 * then the AND mask and the image, row by row; pixels whose mask bit is 0 are drawn, white (15)
 * where the image bit is 1, black (0) where it is 0; hot spot (0, 0) after a reset. */
#include <string.h>
#include "ax_internal.h"
#include "gfx/cursor.h"
#include "gfx/gfx.h"

#define MAXW 6                              /* bytes touched per row: shape + 1 for the shift */
#define MAXH 40

static uint8_t *shape;
static uint32_t shape_size;
static int sw, sh;
static uint8_t saved[4][MAXH][MAXW];
static int saved_x, saved_y, saved_w, saved_h, saved_page = -1;

void cursor_init(void)
{
    const struct xpak_entry *e = xpak_find(&ax.pak, "cursor", XPAK_T_BLOB);
    shape = 0;
    if (e && (shape = xpak_load(&ax.pak, e, &shape_size)) != 0) {
        sw = shape[0];
        sh = shape[1];
        if (sw < 1 || sw > 5 || sh < 1 || sh > MAXH || shape_size < 2u + 2u * (uint32_t)(sw * sh)) {
            xpak_free(&ax.pak, shape, shape_size);
            shape = 0;
        }
    }
    if (!shape)
        sys_log(AX_LOG_WARN, "pack: no mouse pointer shape");
    saved_page = -1;
}

void cursor_shutdown(void)
{
    if (shape)
        xpak_free(&ax.pak, shape, shape_size);
    shape = 0;
}

void cursor_apply(int page)
{
    struct ax_planes *pg = &ax.page[page];
    int x = ax.mouse_x, y = ax.mouse_y, xb = x >> 3, shift = x & 7, r, b, p;
    saved_page = -1;
    if (!shape || !ax.bios.mouse_shown)
        return;
    saved_x = xb;
    saved_y = y;
    saved_w = sw + (shift ? 1 : 0);
    saved_h = sh;
    for (r = 0; r < sh; r++) {
        const uint8_t *mrow = shape + 2 + r * sw, *irow = shape + 2 + sw * sh + r * sw;
        int yy = y + r;
        for (b = 0; b < saved_w; b++) {
            int col = xb + b;
            unsigned m16, i16;
            uint8_t draw, ink;
            if (yy >= AX_SCREEN_H || col >= AX_PLANE_STRIDE)
                continue;
            for (p = 0; p < 4; p++)
                saved[p][r][b] = pg->p[p][yy * AX_PLANE_STRIDE + col];
            /* the shape's bits shifted right by the pixel offset (mask padded with 1s) */
            m16 = ((b > 0 ? (unsigned)mrow[b - 1] : 0xFFu) << 8 | (b < sw ? mrow[b] : 0xFFu)) >> shift;
            i16 = ((b > 0 ? (unsigned)irow[b - 1] : 0u) << 8 | (b < sw ? irow[b] : 0u)) >> shift;
            draw = (uint8_t)~m16;
            ink = (uint8_t)i16;
            for (p = 0; p < 4; p++) {
                uint8_t *d = &pg->p[p][yy * AX_PLANE_STRIDE + col];
                *d = (uint8_t)((*d & ~draw) | (ink & draw));
            }
        }
    }
    gfx_mark_dirty(page, xb, y, xb + saved_w, y + sh);
    saved_page = page;
}

void cursor_restore(int page)
{
    struct ax_planes *pg = &ax.page[page];
    int r, b, p;
    if (saved_page != page)
        return;
    for (r = 0; r < saved_h; r++)
        for (b = 0; b < saved_w; b++) {
            int yy = saved_y + r, col = saved_x + b;
            if (yy >= AX_SCREEN_H || col >= AX_PLANE_STRIDE)
                continue;
            for (p = 0; p < 4; p++)
                pg->p[p][yy * AX_PLANE_STRIDE + col] = saved[p][r][b];
        }
    gfx_mark_dirty(page, saved_x, saved_y, saved_x + saved_w, saved_y + saved_h);
    saved_page = -1;
}
