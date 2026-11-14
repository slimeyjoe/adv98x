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
    int quit_flag;                      /* DS:06BE: the player confirmed quitting */
    uint8_t clickmap[50][80];           /* DS:0EF9, region numbers of 8x8 cells */
    unsigned pitch;                     /* beeper pitch (AH=06h) */
    /* INT 33h, the mouse driver (segment 01AB) */
    int mouse_shown;                    /* 042A */
    int mouse_emu;                      /* 0428: keyboard emulation */
    unsigned mouse_btn;                 /* 0404: bit 0 left, bit 8 right (as read at the last poll) */
    uint32_t mouse_irq_acc;             /* 120 Hz interrupts owed to the frame clock */
    /* INT F2h */
    uint8_t drive[2];                   /* AH=04h: the disk selected per drive slot */
    /* INT F3h: the GPC load buffer 04E9:0454 (F800h bytes) */
    uint8_t *picbuf;
    uint32_t piclen;
};

void bios_init(void);

/* ---- INT F1h: system and waits (bios_sys.c) ---- */
unsigned bios_random(void);                         /* AH=01h: 0..7FFFh */
int  bios_skip_held(void);                          /* SHIFT held or right button down */
void bios_wait_input(void);                         /* AH=07h: Return, Space or left button */
void bios_wait_input_timeout(unsigned ticks, int skippable);   /* AH=08h */
void bios_delay(unsigned ticks, int skippable);     /* AH=09h: plain delay */
void bios_delay_anim(unsigned ticks, int skippable);    /* AH=0Ah: delay, animations run */
void bios_beep(int on);                             /* AH=04h / 05h */
void bios_set_pitch(unsigned dx);                   /* AH=06h */
int  bios_load_clickmap(const char *name);          /* AH=0Ch: 0, -1 on error */
unsigned bios_click_wait(int flags);                /* AH=0Dh: region number, 0 = none */
int  bios_quit_poll(void);                          /* AH=0Fh AL=0: non-zero = quit */
int  bios_quit_flag(void);                          /* AH=0Fh AL=1 */

/* ---- INT 33h: the mouse (bios_mouse.c) ---- */
void mouse_init(void);
void mouse_reset(void);                             /* AX=0 */
void mouse_show(int on);                            /* AX=1 / 2 */
void mouse_state(unsigned *x, unsigned *y);         /* AX=3: position */
void mouse_set_pos(unsigned x, unsigned y);         /* AX=4 */
unsigned mouse_left(void);                          /* AX=5 */
unsigned mouse_right(void);                         /* AX=6 */
unsigned mouse_buttons(void);                       /* AX=7: AL left, AH right */
void mouse_set_emulation(unsigned cx);              /* AX=0Dh */
unsigned mouse_emulation(void);                     /* AX=0Eh */

/* ---- INT F2h: files and disks (bios_file.c) ---- */
/* Names as the scripts give them ("B:\GPC\NV03.GPC", "A:\FLAG0", "MAP1.CLM"); the drive
 * letter and directories are dropped: pictures, songs, maps and scripts come from the pack by
 * name, FLAGn and NAME.DEF from the storage records (docs/engine-plan.md design point 8). */
long bios_file_load(const char *name, uint8_t *dst, uint32_t cap);      /* AH=00h, -1 = CF */
long bios_file_read(const char *name, uint8_t *dst, uint32_t max);      /* AH=05h */
long bios_file_write(const char *name, const uint8_t *src, uint32_t n); /* AH=01h */
void bios_select_drive(int slot, int value);        /* AH=04h: no prompt, ever */

/* ---- INT F4h: sound (bios_snd.c; the music arrives with M4) ---- */
void snd_load_play(const char *name);               /* AH=00h */
void snd_play(void);                                /* AH=01h */
void snd_stop(void);                                /* AH=02h */
void snd_fade_out(int speed);                       /* AH=03h */
void snd_fade_in(int speed);                        /* AH=04h */
void snd_volume(int offset);                        /* AH=07h */
void snd_effect_file(const char *name);             /* AH=10h */
void snd_effect(int n);                             /* AH=11h */

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
void bt_scroll(int dir, unsigned steps);            /* AH=10h: 0 up 1 down 2 left 3 right */
void bt_scroll_rect(const uint16_t rect[4], int dir, unsigned steps);   /* AH=11h */
int  bt_bold(int al);                               /* AH=13h: 0/1 set, >1 get */
unsigned bios_sjis_to_jis(unsigned dx);             /* 0000:024C, no validation */

/* ---- INT F3h: pictures and palette (bios_gfx.c) ---- */
/* AH=01h: draw a GPC file. xb = FFFFh takes the file's position; masked = colour 0
 * transparent; flags bit 0 = take the file's palette into the buffer, bit 1 = then program
 * the hardware at the current brightness. Returns 0, -1 on a bad file. */
int  bg_draw_gpc(const uint8_t *data, uint32_t size, unsigned xb, unsigned y, int masked,
                 int flags);
uint8_t *bg_picture_buffer(uint32_t *cap);          /* AH=00h: the GPC load buffer */
void bg_anim_mode(int on);                          /* AX=0AFFh / 0A00h around the waits */
void bg_anim_poll(void);                            /* the 2-tick animation step (§5.4) */
void bg_default_palette(void);                      /* AH=10h */
void bg_set_brightness(int level);                  /* AH=11h (waits one frame) */
int  bg_brightness(void);                           /* AH=12h */
void bg_set_palette(const uint16_t pal[16], int al); /* AH=13h: al != FFh -> AH=11h al */
void bg_get_palette(uint16_t pal[16]);              /* AH=14h */
void bg_set_entry(int i, unsigned grb, int cl);     /* AH=15h: cl != FFh programs it now */
unsigned bg_get_entry(int i);                       /* AH=16h */
uint16_t *bg_mailbox(void);                         /* AH=FFh: the shared 16-word buffer */

#endif
