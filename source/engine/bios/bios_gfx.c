/* SPDX-License-Identifier: GPL-3.0-or-later */
/* INT F3h, pictures and palette (docs/re/advbios.md §4.3, §5.3, §5.7). The palette buffer
 * (04E9:0022, 0GRB words) and the brightness (04E9:0042) are AdvBIOS's; the DAC is the
 * screen's: every colour component v is programmed as T[brightness][v]. */
#include <string.h>
#include "ax.h"
#include "bios/bios.h"
#include "gfx/gpc.h"

/* INT F3h AH=10h, 0290:047C */
static const uint16_t default_palette[16] = {
    0x000, 0x007, 0x070, 0x077, 0x700, 0x707, 0x770, 0x777,
    0x333, 0x00F, 0x0F0, 0x0FF, 0xF00, 0xF0F, 0xFF0, 0xFFF
};

void bg_load_palette(const uint16_t pal[16])
{
    memcpy(ax.palette, pal, sizeof ax.palette);
}

/* hardware colour i from the buffer: out A8h,i; AAh,T[g]; ACh,T[r]; AEh,T[b]. T is the
 * 16 x 16 table at 0290:049C: T[L][v] = round(v * L / 15), halves rounded up (verified against
 * all 256 entries), which is lrv_pal_bright */
void bg_program_colour(int i, int level)
{
    uint16_t w = ax.palette[i & 15];
    if (level < 0) level = 0;
    if (level > 15) level = 15;
    lrv_screen_set_colour(&ax.screen, i & 15, lrv_pal_bright((w >> 4) & 15, level, 15),
                          lrv_pal_bright((w >> 8) & 15, level, 15),
                          lrv_pal_bright(w & 15, level, 15));
}

void bg_program(int level)
{
    int i;
    if (level < 0) level = 0;
    if (level > 15) level = 15;
    ax.brightness = level;
    for (i = 0; i < 16; i++)
        bg_program_colour(i, level);
}

void bg_init(void)
{
    bg_load_palette(default_palette);
    bg_program(15);
}

/* AH=01h, 0290:00AE: the picture into the access page; palette flags as the parameter block */
int bg_draw_gpc(const uint8_t *data, uint32_t size, unsigned xb, unsigned y, int masked,
                int flags)
{
    struct lrv_surface *page = lrv_screen_access(&ax.screen);
    struct gpc_info g;
    struct lrv_rect w;
    if (gpc_parse(data, size, &g) != 0)
        return -1;
    if (gpc_draw(data, size, page, xb == 0xFFFFu ? -1 : (int)xb, (int)y, masked, &w) != 0)
        return -1;
    lrv_screen_mark_surface(&ax.screen, page, &w);
    if (flags & 1)
        bg_load_palette(g.palette);
    if (flags & 2)
        bg_set_brightness(ax.brightness);
    return 0;
}

/* AH=00h: the GPC load buffer 04E9:0454, F800h bytes */
uint8_t *bg_picture_buffer(uint32_t *cap)
{
    if (!ax.bios.picbuf)
        ax.bios.picbuf = lrv_xalloc(ax.hal, 0xF800);
    *cap = 0xF800;
    return ax.bios.picbuf;
}

/* the animation cells (§5.4), not implemented yet: the mode switch and the 2-tick step arrive with
 * M5 together with the cell services */
void bg_anim_mode(int on)
{
    (void)on;
}

void bg_anim_poll(void)
{
}

void bg_default_palette(void)
{
    bg_load_palette(default_palette);
}

/* AH=11h, 0290:038A: store, wait for VSYNC, program all 16 colours */
void bg_set_brightness(int level)
{
    ax.brightness = level & 15;
    lrv_sys_frame_wait(&ax.sys);
    bg_program(ax.brightness);
    lrv_sys_trace(&ax.sys, AX_TR_PALETTE, 0, 0, ax.brightness, 0, 0, 0);
}

int bg_brightness(void)
{
    return ax.brightness;
}

void bg_set_palette(const uint16_t pal[16], int al)
{
    if (LRV_TRACING(&ax.sys)) {
        int w[16], i;
        for (i = 0; i < 16; i++)
            w[i] = pal[i];
        lrv_sys_trace_ints(&ax.sys, AX_TR_PALETTE, "set", w, 16, al & 0xFF);
    }
    bg_load_palette(pal);
    if ((al & 0xFF) != 0xFF)
        bg_set_brightness(al);
}

void bg_get_palette(uint16_t pal[16])
{
    memcpy(pal, ax.palette, sizeof ax.palette);
}

/* AH=15h, 0290:0404: one entry; unless CL = FFh the colour is programmed at once (no VSYNC
 * wait) with brightness row CL, the stored brightness unchanged */
void bg_set_entry(int i, unsigned grb, int cl)
{
    if (LRV_TRACING(&ax.sys)) {
        int w[3];
        w[0] = i & 0xFF; w[1] = (int)(grb & 0xFFFF); w[2] = cl & 0xFF;
        lrv_sys_trace_ints(&ax.sys, AX_TR_PALETTE, "entry", w, 3, 0);
    }
    ax.palette[i & 15] = (uint16_t)grb;
    if ((cl & 0xFF) != 0xFF)
        bg_program_colour(i & 15, cl & 15);
}

unsigned bg_get_entry(int i)
{
    return ax.palette[i & 15];
}

uint16_t *bg_mailbox(void)
{
    return ax.mailbox;
}
