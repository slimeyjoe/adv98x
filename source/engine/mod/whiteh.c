/* SPDX-License-Identifier: GPL-3.0-or-later */
/* WHITEH.TCM: the whole palette to white (mode 1), from white to the mailbox palette (mode 0),
 * or both (mode 2), in 15 steps (docs/re/plugins.md §4, §7.3). Every step replaces the palette
 * buffer and sets brightness 15 through INT F3h AH=13h (which waits for a VSYNC); before it,
 * s - 1 frames pass, so a step takes s frames. */
#include "ax.h"
#include "bios/bios.h"
#include "mod/mod.h"

/* one half: from `from` (per component) towards white (up) or towards `ref` (down) */
static void half(int up, const uint16_t ref[16], unsigned speed)
{
    unsigned acc[16][3], cur[16][3], k, i, c, w;
    uint16_t pal[16];
    for (i = 0; i < 16; i++)
        for (c = 0; c < 3; c++) {
            acc[i][c] = 0;
            cur[i][c] = up ? (ref[i] >> (4 * c)) & 15 : 15;
        }
    if (speed == 0) {                           /* one write with the final state */
        for (i = 0; i < 16; i++)
            pal[i] = up ? 0xFFF : ref[i];
        bg_set_palette(pal, 15);
        return;
    }
    for (k = 0; k < 15; k++) {
        for (i = 0; i < 16; i++) {
            for (c = 0; c < 3; c++) {
                acc[i][c] += 16 - ((ref[i] >> (4 * c)) & 15);
                if (acc[i][c] >= 16) {
                    acc[i][c] -= 16;
                    cur[i][c] = up ? cur[i][c] + 1 : cur[i][c] - 1;
                }
            }
            pal[i] = (uint16_t)((cur[i][2] & 15) << 8 | (cur[i][1] & 15) << 4 | (cur[i][0] & 15));
        }
        for (w = 1; w < speed; w++)
            lrv_sys_frame_wait(&ax.sys);
        bg_set_palette(pal, 15);
    }
}

static unsigned long whiteh_exec(const uint16_t *a, int n)
{
    uint16_t pal[16];
    unsigned speed;
    if (n < 2 || a[0] > 2 || a[1] > 255)
        return 0xFF00;
    speed = a[1];
    if (a[0] == 1 || a[0] == 2) {
        bg_get_palette(pal);
        half(1, pal, speed);
        if (a[0] == 2 && speed)
            speed--;
    }
    if (a[0] == 0 || a[0] == 2)
        half(0, bg_mailbox(), speed);
    return 0xFF00;
}

const struct ax_module mod_whiteh = { "WHITEH", 0, whiteh_exec, 0 };
