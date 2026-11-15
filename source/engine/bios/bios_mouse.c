/* SPDX-License-Identifier: GPL-3.0-or-later */
/* INT 33h, AdvBIOS's mouse driver (docs/re/advbios.md §4.5, §6.2). The driver ran from a
 * 120 Hz interrupt: it read the bus mouse, or, with keyboard emulation on and no movement from
 * the hardware, moved the pointer by held cursor keys (1 pixel per interrupt, 4 with SHIFT) and
 * took Return/Space as the left button and ESC/TAB as the right one (01AB:0AC6-0BD4). Here the
 * host pointer is absolute (lrv_sys keeps it); the emulation runs from a frame hook at the same
 * rate, and the buttons are read when asked. Drawing the pointer is cursor.c's. */
#include "ax.h"
#include "bios/bios.h"

static int any_down(int a, int b)
{
    return bios_key_down(a) || bios_key_down(b);
}

/* mouse_read_dx / dy with the key emulation: once per 120 Hz interrupt */
static void mouse_irq(void)
{
    int dx = 0, dy = 0;
    if (!ax.bios.mouse_emu)
        return;
    if (any_down(LRV_PC98_K_RIGHT, LRV_PC98_K_KP6)) dx = 1;
    else if (any_down(LRV_PC98_K_LEFT, LRV_PC98_K_KP4)) dx = -1;
    if (any_down(LRV_PC98_K_DOWN, LRV_PC98_K_KP2)) dy = 1;
    else if (any_down(LRV_PC98_K_UP, LRV_PC98_K_KP8)) dy = -1;
    if (bios_key_down(LRV_PC98_K_SHIFT)) {
        dx *= 4;
        dy *= 4;
    }
    if (dx || dy)
        lrv_sys_mouse_set(&ax.sys, ax.sys.mouse_x + dx, ax.sys.mouse_y + dy);
}

void mouse_frame(void *unused)
{
    (void)unused;
    ax.bios.mouse_irq_acc += 12000;                 /* 120 Hz / 56.42 Hz, in 1/5642 units */
    while (ax.bios.mouse_irq_acc >= 5642) {
        ax.bios.mouse_irq_acc -= 5642;
        mouse_irq();
    }
}

void mouse_init(void)
{
    ax.bios.mouse_emu = 0;
    mouse_reset();
}

/* AX=0, mouse_reset 01AB:0206: hide, full range, position (639, 399) */
void mouse_reset(void)
{
    mouse_show(0);
    lrv_sys_mouse_set(&ax.sys, 639, 399);
}

void mouse_show(int on)
{
    ax.bios.mouse_shown = on;
}

void mouse_state(unsigned *x, unsigned *y)
{
    *x = (unsigned)ax.sys.mouse_x;
    *y = (unsigned)ax.sys.mouse_y;
}

void mouse_set_pos(unsigned x, unsigned y)
{
    lrv_sys_mouse_set(&ax.sys, (int)(x & 0xFFFF) > 639 ? 639 : (int)x,
                      (int)(y & 0xFFFF) > 399 ? 399 : (int)y);
}

/* mouse_read_buttons 01AB:0B8E */
unsigned mouse_left(void)
{
    if (lrv_sys_mouse_buttons(&ax.sys) & LRV_BTN_L)
        return 1;
    return ax.bios.mouse_emu && any_down(LRV_PC98_K_RETURN, LRV_PC98_K_SPACE);
}

unsigned mouse_right(void)
{
    if (lrv_sys_mouse_buttons(&ax.sys) & LRV_BTN_R)
        return 1;
    return ax.bios.mouse_emu && any_down(LRV_PC98_K_ESC, LRV_PC98_K_TAB);
}

unsigned mouse_buttons(void)
{
    return mouse_left() | (mouse_right() << 8);
}

/* AX=0Dh, 01AB:036E: set, then wait 4 (on) / 2 (off) mouse interrupts */
void mouse_set_emulation(unsigned cx)
{
    ax.bios.mouse_emu = (int)(cx & 0xFFFF);
    lrv_sys_frame_wait(&ax.sys);
    if (ax.bios.mouse_emu)
        lrv_sys_frame_wait(&ax.sys);
}

unsigned mouse_emulation(void)
{
    return (unsigned)ax.bios.mouse_emu;
}
