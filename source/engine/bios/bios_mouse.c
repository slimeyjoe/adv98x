/* SPDX-License-Identifier: GPL-3.0-or-later */
/* INT 33h, AdvBIOS's mouse driver (docs/re/advbios.md §4.5, §6.2). The driver ran from a
 * 120 Hz interrupt: it read the bus mouse, or, with keyboard emulation on and no movement from
 * the hardware, moved the pointer by held cursor keys (1 pixel per interrupt, 4 with SHIFT) and
 * took Return/Space as the left button and ESC/TAB as the right one (01AB:0AC6-0BD4). Here the
 * host pointer is absolute (sys.c keeps it); the emulation runs from a frame hook at the same
 * rate, and the buttons are read when asked. Drawing the pointer is cursor.c's (M3). */
#include "ax_internal.h"
#include "bios/bios.h"

static int any_down(int a, int b)
{
    return sys_key_down(a) || sys_key_down(b);
}

/* mouse_read_dx / dy with the key emulation: once per 120 Hz interrupt */
static void mouse_irq(void)
{
    int dx = 0, dy = 0;
    if (!ax.bios.mouse_emu)
        return;
    if (any_down(AX_K_RIGHT, AX_K_KP6)) dx = 1;
    else if (any_down(AX_K_LEFT, AX_K_KP4)) dx = -1;
    if (any_down(AX_K_DOWN, AX_K_KP2)) dy = 1;
    else if (any_down(AX_K_UP, AX_K_KP8)) dy = -1;
    if (sys_key_down(AX_K_SHIFT)) {
        dx *= 4;
        dy *= 4;
    }
    if (dx || dy)
        sys_mouse_set_pos(ax.mouse_x + dx, ax.mouse_y + dy);
}

static void mouse_frame(void)
{
    ax.bios.mouse_irq_acc += 12000;                 /* 120 Hz / 56.42 Hz, in 1/5642 units */
    while (ax.bios.mouse_irq_acc >= 5642) {
        ax.bios.mouse_irq_acc -= 5642;
        mouse_irq();
    }
}

void mouse_init(void)
{
    static int hooked;
    if (!hooked) {
        sys_add_frame_hook(mouse_frame);
        hooked = 1;
    }
    ax.bios.mouse_emu = 0;
    mouse_reset();
}

/* AX=0, mouse_reset 01AB:0206: hide, full range, position (639, 399) */
void mouse_reset(void)
{
    mouse_show(0);
    sys_mouse_set_pos(639, 399);
}

void mouse_show(int on)
{
    ax.bios.mouse_shown = on;
}

void mouse_state(unsigned *x, unsigned *y)
{
    *x = (unsigned)ax.mouse_x;
    *y = (unsigned)ax.mouse_y;
}

void mouse_set_pos(unsigned x, unsigned y)
{
    sys_mouse_set_pos((int)(x & 0xFFFF) > 639 ? 639 : (int)x, (int)(y & 0xFFFF) > 399 ? 399 : (int)y);
}

/* mouse_read_buttons 01AB:0B8E */
unsigned mouse_left(void)
{
    if (sys_mouse_buttons() & AX_BTN_L)
        return 1;
    return ax.bios.mouse_emu && any_down(AX_K_RETURN, AX_K_SPACE);
}

unsigned mouse_right(void)
{
    if (sys_mouse_buttons() & AX_BTN_R)
        return 1;
    return ax.bios.mouse_emu && any_down(AX_K_ESC, AX_K_TAB);
}

unsigned mouse_buttons(void)
{
    return mouse_left() | (mouse_right() << 8);
}

/* AX=0Dh, 01AB:036E: set, then wait 4 (on) / 2 (off) mouse interrupts */
void mouse_set_emulation(unsigned cx)
{
    ax.bios.mouse_emu = (int)(cx & 0xFFFF);
    sys_frame_wait();
    if (ax.bios.mouse_emu)
        sys_frame_wait();
}

unsigned mouse_emulation(void)
{
    return (unsigned)ax.bios.mouse_emu;
}
