/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The mouse pointer (cursor.h). Shape: byte 0 width in bytes (1..5), byte 1 height (1..40),
 * then the AND mask and the image, row by row; pixels whose mask bit is 0 are drawn, white (15)
 * where the image bit is 1, black (0) where it is 0; hot spot (0, 0) after a reset. */
#include <string.h>
#include "ax.h"
#include "gfx/cursor.h"

#define MAXW 6                              /* bytes touched per row: shape + 1 for the shift */
#define MAXH 40

static uint8_t *shape;
static uint32_t shape_size;
static int sw, sh;
static uint8_t saved[4][MAXH][MAXW];
static int saved_x, saved_y, saved_w, saved_h, saved_valid;

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
        lrv_log(ax.hal, LRV_LOG_WARN, "pack: no mouse pointer shape");
    saved_valid = 0;
}

void cursor_reset(void)
{
    saved_valid = 0;
}

void cursor_shutdown(void)
{
    if (shape)
        xpak_free(&ax.pak, shape, shape_size);
    shape = 0;
}

static void mark(const struct lrv_surface *pg, struct lrv_rect *dirty)
{
    struct lrv_rect r;
    r.x0 = saved_x; r.y0 = saved_y; r.x1 = saved_x + saved_w; r.y1 = saved_y + saved_h;
    lrv_rect_clip(&r, pg);
    lrv_rect_union(dirty, &r);
}

void cursor_apply(void *unused, struct lrv_surface *pg, struct lrv_rect *dirty)
{
    int x = ax.sys.mouse_x, y = ax.sys.mouse_y, xb = x >> 3, shift = x & 7, r, b, p;
    (void)unused;
    saved_valid = 0;
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
            if (yy >= LRV_PC98_H || col >= LRV_PC98_STRIDE)
                continue;
            for (p = 0; p < 4; p++)
                saved[p][r][b] = pg->plane[p][yy * LRV_PC98_STRIDE + col];
            /* the shape's bits shifted right by the pixel offset (mask padded with 1s) */
            m16 = ((b > 0 ? (unsigned)mrow[b - 1] : 0xFFu) << 8 | (b < sw ? mrow[b] : 0xFFu)) >> shift;
            i16 = ((b > 0 ? (unsigned)irow[b - 1] : 0u) << 8 | (b < sw ? irow[b] : 0u)) >> shift;
            draw = (uint8_t)~m16;
            ink = (uint8_t)i16;
            for (p = 0; p < 4; p++) {
                uint8_t *d = &pg->plane[p][yy * LRV_PC98_STRIDE + col];
                *d = (uint8_t)((*d & ~draw) | (ink & draw));
            }
        }
    }
    mark(pg, dirty);
    saved_valid = 1;
}

void cursor_restore(void *unused, struct lrv_surface *pg, struct lrv_rect *dirty)
{
    int r, b, p;
    (void)unused;
    if (!saved_valid)
        return;
    for (r = 0; r < saved_h; r++)
        for (b = 0; b < saved_w; b++) {
            int yy = saved_y + r, col = saved_x + b;
            if (yy >= LRV_PC98_H || col >= LRV_PC98_STRIDE)
                continue;
            for (p = 0; p < 4; p++)
                pg->plane[p][yy * LRV_PC98_STRIDE + col] = saved[p][r][b];
        }
    mark(pg, dirty);
    saved_valid = 0;
}
