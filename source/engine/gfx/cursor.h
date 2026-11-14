/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The mouse pointer, drawn by the engine as AdvBIOS's driver draws it (docs/re/advbios.md §6.2):
 * the default shape from the pack, pixel-exact at the pointer position. The driver drew into
 * VRAM with save-under; the engine draws it only into the presented frame (cursor_apply before
 * the present, cursor_restore after), so the page itself never contains it. */
#ifndef AX_GFX_CURSOR_H
#define AX_GFX_CURSOR_H

void cursor_init(void);
void cursor_shutdown(void);
void cursor_apply(int page);        /* draw at the pointer if it is shown, saving what is under */
void cursor_restore(int page);

#endif
