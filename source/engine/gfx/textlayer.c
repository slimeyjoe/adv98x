/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The text layer and the curtain (textlayer.h); apiF6_0F_TextCurtain 0000:0DA6. */
#include <string.h>
#include "ax.h"
#include "gfx/textlayer.h"

/* text VRAM A000:0000 (codes, 2 bytes per cell) and A000:2000 (attributes) */
static uint8_t vram[0x4000];
static uint8_t cover_colour;                    /* DS:01B0 */
static uint8_t saved[4][AX_PLANE_BYTES];
static int saved_valid;
static int was_active;

void tl_init(void)
{
    memset(vram, 0, sizeof vram);
    cover_colour = 0;
    saved_valid = 0;
    was_active = 0;
}

const uint8_t *tl_vram(void)
{
    return vram;
}

/* curtain_cell 0000:0E56: the bit of grid cell `di` and the address of its character */
static int cell(unsigned di, const uint8_t r[4], unsigned *bx)
{
    static const uint8_t bits[8] = { 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80 };
    unsigned row = di / 160, col = di % 160;
    if (row < r[1] || row > r[3] || col < r[0] || col > r[2])
        return 0;
    *bx = (row & 0xFC) * 0x28 + (col & 0xFE);
    return bits[(col & 1) * 4 + (row & 3)];
}

void tl_curtain(int al, int ch, int cl, int dh, int dl)
{
    uint8_t r[4];
    unsigned si, di, bx;
    uint8_t attr;
    int cover = (al & 0xFF) <= 7;
    r[0] = (uint8_t)ch; r[1] = (uint8_t)cl; r[2] = (uint8_t)dh; r[3] = (uint8_t)dl;
    if (cover)
        cover_colour = (uint8_t)al;
    attr = (uint8_t)((cover_colour << 5) | 0x11);
    for (si = 0; si < 31; si++) {
        int pass;
        lrv_sys_frame_wait(&ax.sys);   /* wait for the start of a VSYNC */
        for (pass = 0; pass < 2; pass++) {
            for (di = pass ? 62 - si - 1 : si; di < 0x3E80; di += 62) {
                int b = cell(di, r, &bx);
                if (!b)
                    continue;
                vram[bx + 0x2000] = attr;
                if (cover)
                    vram[bx] |= (uint8_t)b;
                else
                    vram[bx] &= (uint8_t)~b;
            }
        }
    }
}

static int nearest_index(int colour)
{
    int i, best = 0, bestd = 1 << 30;
    int tr = (colour & 2) ? 15 : 0, tg = (colour & 4) ? 15 : 0, tb = (colour & 1) ? 15 : 0;
    for (i = 0; i < 16; i++) {
        const uint8_t *dac = &ax.screen.rgb[i * 3];
        int dr = dac[0] - tr, dg = dac[1] - tg, db = dac[2] - tb;
        int d = dr * dr + dg * dg + db * db;
        if (d < bestd) {
            bestd = d;
            best = i;
        }
    }
    return best;
}

void tl_apply(void *unused, struct lrv_surface *pg, struct lrv_rect *dirty)
{
    int crow, ccol, p, active = 0;
    (void)unused;
    saved_valid = 0;
    for (crow = 0; crow < 25 && !active; crow++)
        for (ccol = 0; ccol < 80; ccol++) {
            unsigned o = (unsigned)(crow * 160 + ccol * 2);
            if (vram[o] && (vram[o + 0x2000] & 0x11) == 0x11) {
                active = 1;
                break;
            }
        }
    if (!active) {
        if (was_active)
            lrv_rect_add(dirty, 0, 0, LRV_PC98_STRIDE, LRV_PC98_H);
        was_active = 0;
        return;
    }
    for (p = 0; p < 4; p++)
        memcpy(saved[p], pg->plane[p], AX_PLANE_BYTES);
    saved_valid = 1;
    for (crow = 0; crow < 25; crow++)
        for (ccol = 0; ccol < 80; ccol++) {
            unsigned o = (unsigned)(crow * 160 + ccol * 2), b;
            uint8_t code = vram[o], attr = vram[o + 0x2000];
            int idx;
            if (!code || (attr & 0x11) != 0x11)
                continue;
            idx = nearest_index(attr >> 5);
            for (b = 0; b < 8; b++) {
                int x0 = ccol * 8 + (int)(b >> 2) * 4, y0 = crow * 16 + (int)(b & 3) * 4, y;
                uint8_t mask = (uint8_t)(x0 & 4 ? 0x0F : 0xF0);
                if (!(code & (1u << b)))
                    continue;
                for (y = y0; y < y0 + 4; y++)
                    for (p = 0; p < 4; p++) {
                        uint8_t *d = &pg->plane[p][y * LRV_PC98_STRIDE + (x0 >> 3)];
                        *d = (uint8_t)((idx >> p) & 1 ? (*d | mask) : (*d & ~mask));
                    }
            }
        }
    lrv_rect_add(dirty, 0, 0, LRV_PC98_STRIDE, LRV_PC98_H);
    was_active = 1;
}

void tl_restore(void *unused, struct lrv_surface *pg, struct lrv_rect *dirty)
{
    int p;
    (void)unused;
    if (!saved_valid)
        return;
    for (p = 0; p < 4; p++)
        memcpy(pg->plane[p], saved[p], AX_PLANE_BYTES);
    lrv_rect_add(dirty, 0, 0, LRV_PC98_STRIDE, LRV_PC98_H);
    saved_valid = 0;
}
