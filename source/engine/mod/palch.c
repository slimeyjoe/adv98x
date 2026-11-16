/* SPDX-License-Identifier: GPL-3.0-or-later */
/* PALCH.TCM: change one palette colour, at once or gliding in 15 steps (docs/re/plugins.md §3,
 * §7.2). Arguments: index, blue, red, green [, speed in frames per step]. The colour is shown
 * at brightness row 15 (INT F3h AH=15h, CL=0Fh), whatever the current brightness. */
#include "ax.h"
#include "bios/bios.h"
#include "mod/mod.h"

static unsigned long palch_exec(const uint16_t *a, int n)
{
    unsigned idx, target, cur, k, i;
    unsigned acc[3] = { 0, 0, 0 }, step[3], dir[3], c[3], t[3];
    if (n < 4 || a[0] > 15 || a[1] > 15 || a[2] > 15 || a[3] > 15 || (n >= 5 && a[4] > 255))
        return 0xFF00;
    idx = a[0];
    target = (unsigned)(a[3] << 8 | a[2] << 4 | a[1]);
    if (n < 5) {
        bg_set_entry((int)idx, target, 15);
        return 0xFF00;
    }
    cur = bg_get_entry((int)idx);
    for (i = 0; i < 3; i++) {                   /* blue, red, green: bits 0, 4, 8 */
        c[i] = (cur >> (4 * i)) & 15;
        t[i] = (target >> (4 * i)) & 15;
        step[i] = (t[i] > c[i] ? t[i] - c[i] : c[i] - t[i]) + 1;
        dir[i] = t[i] >= c[i];
    }
    for (k = 0; k < 15; k++) {
        for (i = 0; i < 3; i++) {
            acc[i] += step[i];
            if (acc[i] >= 16) {
                acc[i] -= 16;
                c[i] = dir[i] ? c[i] + 1 : c[i] - 1;
            }
        }
        for (i = 0; i < a[4]; i++)
            lrv_sys_frame_wait(&ax.sys);
        bg_set_entry((int)idx, (c[2] & 15) << 8 | (c[1] & 15) << 4 | (c[0] & 15), 15);
    }
    return 0xFF00;
}

const struct ax_module mod_palch = { "PALCH", 0, palch_exec, 0 };
