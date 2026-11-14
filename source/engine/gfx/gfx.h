/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Graphics: VRAM pages, dirty tracking, palette buffer and brightness (docs/re/advbios.md §5.1,
 * §5.7). The planes are plain memory (gfx/planes.h); every write marks a dirty region on its
 * page so the backend uploads only what changed. */
#ifndef AX_GFX_GFX_H
#define AX_GFX_GFX_H

#include <stdint.h>
#include "gfx/planes.h"

void gfx_init(void);
void gfx_reset(void);                            /* as at start-up (the reset button) */
void gfx_shutdown(void);

/* pages and the graphics layer */
void gfx_set_access_page(int p);
void gfx_set_display_page(int p);
void gfx_graph_on(int on);
struct ax_planes *gfx_access(void);              /* planes of the access page */
void gfx_mark_dirty(int page, int x0, int y0, int x1, int y1);   /* byte cols, lines */
void gfx_mark_planes(const struct ax_planes *pl, const struct ax_rect *r);
void gfx_clear_page(void);                       /* the access page to colour 0 */

/* palette buffer (04E9:0022) and brightness (04E9:0042). Palette words are 0GRB. The DAC is
 * what the hardware shows: every colour component v as T[brightness][v] = round(v * L / 15). */
extern const uint16_t gfx_default_palette[16];  /* INT F3h AH=10h */
void gfx_set_palette(const uint16_t pal[16]);    /* the buffer only */
void gfx_set_brightness(int level);              /* store and program all 16 colours */
void gfx_program_colour(int i, int level);       /* one colour from the buffer at `level` */
void gfx_update_dac(void);                       /* before present: nothing to do now */
int  gfx_bright(int v, int level);               /* the table T[level][v] */

#endif
