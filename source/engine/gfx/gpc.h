/* SPDX-License-Identifier: GPL-3.0-or-later */
/* GPC pictures (docs/re/graphics-formats.md §2-4, advbios.md §5.3): the C port of the verified
 * decoder source/tools/gpc.py, drawing like AdvBIOS's INT F3h AH=01h. */
#ifndef AX_GFX_GPC_H
#define AX_GFX_GPC_H

#include <stdint.h>
#include "gfx/planes.h"

struct gpc_info {
    int w, h;                   /* pixels */
    int x, y;                   /* the file's position, pixels */
    int interleave;             /* N: rows stored in N passes (0, 1 = natural order) */
    int has_palette;
    uint16_t palette[16];       /* 0GRB words */
    uint32_t stream;            /* file offset of the packed rows */
};

/* Parse the header. Returns 0, or -1 if the data is not a usable GPC file. */
int gpc_parse(const uint8_t *data, uint32_t size, struct gpc_info *g);

/* Decode the picture into the pixel rows of the original's row pipeline (unpack, horizontal
 * XOR, vertical XOR, interleave): `rows` gets h rows of 4 * ceil(w / 8) bytes, the four bit
 * planes side by side (plane 0 first), in screen order. `rows` must hold gpc_rows_size(g)
 * bytes. Returns 0, or -1 when out of memory. */
uint32_t gpc_rows_size(const struct gpc_info *g);
int gpc_decode_rows(const uint8_t *data, uint32_t size, const struct gpc_info *g, uint8_t *rows);

/* Draw as INT F3h AH=01h: xb (byte column) and y, or xb < 0 for the file's (x >> 3, y);
 * masked = 0 opaque, else colour 0 leaves the destination unchanged. Rows are 80 bytes apart
 * and the offset is y * 80 + xb as in the original (a row wider than the screen continues on
 * the next line); nothing is written beyond the planes. `written` (may be NULL) receives the
 * rectangle touched, in byte columns x lines. Returns 0, or -1 on a bad file. Palette flags
 * are the caller's (bios_gfx). */
int gpc_draw(const uint8_t *data, uint32_t size, struct ax_planes *dst, int xb, int y,
             int masked, struct ax_rect *written);

#endif
