/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The PC-98 text layer, as far as AdvBIOS uses it: the semigraphic "curtain" (INT F6h AH=0Fh,
 * docs/re/advbios.md §5.6). Text VRAM is modelled as 80x25 character codes and attributes; a
 * cell with attribute bits SG (10h) and ST (01h) shows its code as 2x4 blocks of 4x4 pixels in
 * the attribute's colour (bits 5-7: B, R, G at full intensity). A frame has no text plane, so
 * the layer is an overlay of the screen (lrvne/gfx.h, like the pointer): the blocks are drawn
 * into the presented frame in the palette entry whose DAC colour is closest, which is exact
 * where the curtain is drawn in white over an all-white palette. */
#ifndef AX_GFX_TEXTLAYER_H
#define AX_GFX_TEXTLAYER_H

#include <stdint.h>
#include "lrvne/gfx.h"

void tl_init(void);
void tl_apply(void *unused, struct lrv_surface *page, struct lrv_rect *dirty);
void tl_restore(void *unused, struct lrv_surface *page, struct lrv_rect *dirty);
/* INT F6h AH=0Fh: AL <= 7 cover cells (CH,CL)-(DH,DL) of the 160x100 grid in colour AL,
 * AL > 7 uncover; 31 phases, one VSYNC each */
void tl_curtain(int al, int ch, int cl, int dh, int dl);
const uint8_t *tl_vram(void);        /* 25 x 80 x {code, 0} then 25 x 80 x {attr, 0}, as A000h */

#endif
