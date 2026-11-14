/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The AdvBIOS service layer (docs/re/advbios.md §4-8): a C API with the original semantics,
 * called by the interpreter and the plug-in modules. Each function names the service it is
 * (INT xxh AH=yyh). Coordinates are AdvBIOS's: x in byte columns (8 pixels), y in lines. */
#ifndef AX_BIOS_H
#define AX_BIOS_H

#include <stdint.h>

/* the state AdvBIOS keeps in its DGROUP and in 04E9 (advbios.md §5) */
struct ax_bios {
    /* INT F6h, DS:0198.. */
    uint16_t win[4];                    /* text window x0, y0, x1, y1 (0198) */
    uint16_t cur_x, cur_y;              /* text cursor (01A0, 01A2) */
    uint8_t colour;                     /* 01A4 */
    uint8_t bold;                       /* 01A5 */
    uint16_t delay;                     /* ticks per character (01A6) */
    uint16_t delay_skip;                /* the delay may be skipped (01A8) */
    uint16_t beep;                      /* beep ticks per character (01AA) */
    uint16_t last_char;                 /* JIS code of the last character drawn (17FE) */
    /* animation lip-sync hooks (§5.4): trigger colours (0182/0183) and counters (0184/0186) */
    uint8_t lip_colour[2];
    uint16_t lip_count[2];
    /* INT F1h */
    uint32_t rng;                       /* DS:00FE */
};

void bios_init(void);

/* ---- INT F1h: system and waits (bios_sys.c) ---- */
int  bios_skip_held(void);                          /* SHIFT held or right button down */
void bios_delay(unsigned ticks, int skippable);     /* AH=09h: plain delay */
void bios_beep(int on);                             /* AH=04h / 05h */

/* ---- INT F6h: text and simple drawing (bios_text.c) ---- */
void bt_set_window(const uint16_t rect[4]);         /* AH=01h: clamped and sorted */
void bt_get_window(uint16_t rect[4]);               /* AH=02h */
void bt_set_colour(int c);                          /* AH=03h */
int  bt_colour(void);                               /* AH=04h */
void bt_set_cursor(unsigned x, unsigned y);         /* AH=05h */
void bt_cursor(unsigned *x, unsigned *y);           /* AH=06h */
void bt_set_delay(unsigned ticks, int al);          /* AH=07h: al sign-extended = skippable */
void bt_set_beep(unsigned ticks);                   /* AH=08h */
void bt_draw_char(unsigned dx);                     /* AH=09h: DH != 0 = Shift-JIS */
void bt_draw_string(const uint8_t *s);              /* AH=0Ah: ends at 00h or FFh */
void bt_fill_window(int c);                         /* AH=0Bh: fill, cursor home */
void bt_fill_page(int c);                           /* AH=0Ch */
void bt_fill_rect(const uint16_t rect[4], int c);   /* AH=0Dh */
void bt_invert_rect(const uint16_t rect[4]);        /* AH=0Eh */
int  bt_bold(int al);                               /* AH=13h: 0/1 set, >1 get */
unsigned bios_sjis_to_jis(unsigned dx);             /* 0000:024C, no validation */

/* ---- INT F3h: pictures and palette (bios_gfx.c) ---- */
/* AH=01h: draw a GPC file. xb = FFFFh takes the file's position; masked = colour 0
 * transparent; flags bit 0 = take the file's palette into the buffer, bit 1 = then program
 * the hardware at the current brightness. Returns 0, -1 on a bad file. */
int  bg_draw_gpc(const uint8_t *data, uint32_t size, unsigned xb, unsigned y, int masked,
                 int flags);
void bg_default_palette(void);                      /* AH=10h */
void bg_set_brightness(int level);                  /* AH=11h (waits one frame) */
int  bg_brightness(void);                           /* AH=12h */
void bg_set_palette(const uint16_t pal[16], int al); /* AH=13h: al != FFh -> AH=11h al */
void bg_get_palette(uint16_t pal[16]);              /* AH=14h */
void bg_set_entry(int i, unsigned grb, int cl);     /* AH=15h: cl != FFh programs it now */
unsigned bg_get_entry(int i);                       /* AH=16h */
uint16_t *bg_mailbox(void);                         /* AH=FFh: the shared 16-word buffer */

#endif
