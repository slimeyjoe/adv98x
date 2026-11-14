/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The PC-98 kanji ROM as AdvBIOS reads it (INT 18h AH=14h, docs/re/advbios.md §5.2), from the
 * pack's glyph tables: font16 (JIS X 0208, 16x16, keyed by JIS code) and font8 (half-width
 * 8x16, keyed by the JIS X 0201 byte). */
#ifndef AX_TEXT_FONT_H
#define AX_TEXT_FONT_H

#include <stdint.h>

void font_init(void);
void font_shutdown(void);

/* INT 18h AH=14h: the glyph of JIS code `jis` into rows (16 rows of `width` bytes, left byte
 * first); returns the width in bytes. Rows 29h and 2Ah are the half-width characters (29xx =
 * the JIS X 0201 roman byte xx, 2Axx = the katakana byte xx + 80h), row 2Bh is half-width and
 * blank here; everything else is full-width. A code without a glyph is blank. */
int font_rom_glyph(unsigned jis, uint8_t rows[32]);

#endif
