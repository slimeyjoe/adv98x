/* SPDX-License-Identifier: GPL-3.0-or-later */
/* test_palette < SCENARIO: INT F3h palette services through the engine (bios/bios_gfx.c).
 *   default | bright L | setpal W0..W15(HEX) AL | entry I GRB(HEX) CL | snap NAME
 * Output per snap: "snap NAME BRIGHTNESS" then the DAC (16 x r g b) and the palette buffer
 * (16 x 0GRB). tests/check_palette.py compares with AdvBIOS's own code. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ax.h"
#include "bios/bios.h"
#include "test_hal.h"

int main(void)
{
    struct lrv_hal hal;
    char line[1024];
    th_hal(&hal, 0);
    memset(&ax, 0, sizeof ax);
    ax.hal = &hal;
    lrv_sys_init(&ax.sys, &hal, LRV_PC98_W, LRV_PC98_H);
    lrv_sys_set_present(&ax.sys, lrv_screen_present_hook, &ax.screen);
    if (lrv_screen_init(&ax.screen, &hal, &lrv_pc98_video_mode, 2, 0, LRV_MEM_ANY) != LRV_OK)
        return 2;
    bios_init();
    /* the hardware state AdvBIOS starts from in the harness: all colours 0, brightness 0 */
    memset(ax.palette, 0, sizeof ax.palette);
    bg_program(0);
    while (fgets(line, sizeof line, stdin)) {
        char op[32], name[64];
        unsigned a, b, c;
        uint16_t pal[16];
        int i;
        if (sscanf(line, "%31s", op) != 1)
            continue;
        if (!strcmp(op, "default")) {
            bg_default_palette();
        } else if (!strcmp(op, "bright")) {
            sscanf(line, "%*s %u", &a);
            bg_set_brightness((int)a);
        } else if (!strcmp(op, "setpal")) {
            char *p = line;
            strtok(p, " \n");
            for (i = 0; i < 16; i++)
                pal[i] = (uint16_t)strtoul(strtok(0, " \n"), 0, 16);
            a = (unsigned)strtoul(strtok(0, " \n"), 0, 10);
            bg_set_palette(pal, (int)a);
        } else if (!strcmp(op, "entry")) {
            sscanf(line, "%*s %u %x %u", &a, &b, &c);
            bg_set_entry((int)a, b, (int)c);
        } else if (!strcmp(op, "snap")) {
            sscanf(line, "%*s %63s", name);
            bg_get_palette(pal);
            printf("snap %s %d\n", name, bg_brightness());
            for (i = 0; i < 48; i++)
                printf("%d%c", ax.screen.rgb[i], i < 47 ? ' ' : '\n');
            for (i = 0; i < 16; i++)
                printf("%03X%c", pal[i] == bg_get_entry(i) ? pal[i] : 0xFFFu, i < 15 ? ' ' : '\n');
        } else {
            fprintf(stderr, "test_palette: unknown op %s\n", op);
            return 2;
        }
    }
    return 0;
}
