/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The mouse pointer, drawn by the engine as AdvBIOS's driver draws it (docs/re/advbios.md §6.2):
 * the default shape from the pack, pixel-exact at the pointer position. The driver drew into
 * VRAM with save-under; here it is an overlay of the screen (lrvne/gfx.h), drawn only into the
 * presented frame: cursor_apply before the present, cursor_restore after, so the page itself
 * never contains it. */
#ifndef AX_GFX_CURSOR_H
#define AX_GFX_CURSOR_H

#include "lrvne/gfx.h"

void cursor_init(void);
void cursor_reset(void);            /* forget the save-under (the pages were cleared) */
void cursor_shutdown(void);
/* the overlay: draw at the pointer if it is shown, keeping what is under; put that back */
void cursor_apply(void *unused, struct lrv_surface *page, struct lrv_rect *dirty);
void cursor_restore(void *unused, struct lrv_surface *page, struct lrv_rect *dirty);

#endif
