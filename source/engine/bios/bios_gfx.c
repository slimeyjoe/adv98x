/* SPDX-License-Identifier: GPL-3.0-or-later */
/* INT F3h, pictures and palette (docs/re/advbios.md §4.3, §5.3, §5.7). */
#include <string.h>
#include "ax_internal.h"
#include "bios/bios.h"
#include "gfx/gfx.h"
#include "gfx/gpc.h"

/* AH=01h, 0290:00AE: the picture into the access page; palette flags as the parameter block */
int bg_draw_gpc(const uint8_t *data, uint32_t size, unsigned xb, unsigned y, int masked,
                int flags)
{
    struct gpc_info g;
    struct ax_rect w;
    if (gpc_parse(data, size, &g) != 0)
        return -1;
    if (gpc_draw(data, size, gfx_access(), xb == 0xFFFFu ? -1 : (int)xb, (int)y, masked, &w) != 0)
        return -1;
    gfx_mark_planes(gfx_access(), &w);
    if (flags & 1)
        gfx_set_palette(g.palette);
    if (flags & 2)
        bg_set_brightness(ax.brightness);
    return 0;
}

/* AH=00h: the GPC load buffer 04E9:0454, F800h bytes */
uint8_t *bg_picture_buffer(uint32_t *cap)
{
    if (!ax.bios.picbuf)
        ax.bios.picbuf = sys_alloc(0xF800);
    *cap = 0xF800;
    return ax.bios.picbuf;
}

/* the animation cells (§5.4), unused by NOVA: the mode switch and the 2-tick step arrive with
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
    gfx_set_palette(gfx_default_palette);
}

/* AH=11h, 0290:038A: store, wait for VSYNC, program all 16 colours */
void bg_set_brightness(int level)
{
    ax.brightness = level & 15;
    sys_frame_wait();
    gfx_set_brightness(ax.brightness);
    sys_trace(AX_TR_PALETTE, 0, 0, ax.brightness, 0, 0, 0);
}

int bg_brightness(void)
{
    return ax.brightness;
}

void bg_set_palette(const uint16_t pal[16], int al)
{
    gfx_set_palette(pal);
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
    ax.palette[i & 15] = (uint16_t)grb;
    if ((cl & 0xFF) != 0xFF)
        gfx_program_colour(i & 15, cl & 15);
}

unsigned bg_get_entry(int i)
{
    return ax.palette[i & 15];
}

uint16_t *bg_mailbox(void)
{
    return ax.mailbox;
}
