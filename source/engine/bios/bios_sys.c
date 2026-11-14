/* SPDX-License-Identifier: GPL-3.0-or-later */
/* INT F1h, system services and waits (docs/re/advbios.md §4.1). The waits count AdvBIOS's
 * 20 ms ticks, which the engine derives from its frames (sys.c). */
#include <string.h>
#include "ax_internal.h"
#include "bios/bios.h"

void bios_init(void)
{
    struct ax_bios *b = &ax.bios;
    memset(b, 0, sizeof *b);
    /* the initialised DGROUP of NV.OV1 (advbios.md §5.2 "Defaults") */
    b->win[0] = 0; b->win[1] = 0; b->win[2] = 79; b->win[3] = 399;
    b->colour = 15;
    b->delay_skip = 0xFFFF;
    b->lip_colour[0] = b->lip_colour[1] = 0x10;      /* never matches a colour */
    b->rng = 1;
    memset(ax.mailbox, 0, sizeof ax.mailbox);
}

/* wait_skip_check 0000:03B4 / text_skip_check 0000:0C48: SHIFT held (INT 18h AH=02h bit 0)
 * or the right button down (INT 33h AX=6) */
int bios_skip_held(void)
{
    return sys_key_down(AX_K_SHIFT) || (sys_mouse_buttons() & AX_BTN_R) != 0;
}

/* apiF1_09_Delay 0000:03F0: ends after `ticks` ticks, when the player quits, or when skipping
 * is allowed and wanted */
void bios_delay(unsigned ticks, int skippable)
{
    uint32_t end = ax.tick + ticks;
    int traced = ticks > 1;
    if (traced)
        sys_trace(AX_TR_WAIT, 0, 0, AX_WAIT_TICKS, 0, (int)ticks, 0);
    while ((int32_t)(end - ax.tick) > 0) {
        if (sys_quitting() || (skippable && bios_skip_held()))
            break;
        sys_frame_wait();
    }
    if (traced)
        sys_trace(AX_TR_WAIT, 0, 0, AX_WAIT_TICKS, 1,
                  sys_quitting() ? AX_LEAVE_QUIT :
                  (int32_t)(end - ax.tick) > 0 ? AX_LEAVE_SKIP : AX_LEAVE_TIMEOUT, 0);
}

/* AH=04h / 05h: the beeper (port 37h). The sound itself arrives with M5. */
void bios_beep(int on)
{
    ax.beeper_on = on;
}
