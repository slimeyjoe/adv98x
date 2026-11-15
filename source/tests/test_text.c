/* SPDX-License-Identifier: GPL-3.0-or-later */
/* test_text PAK < SCENARIO: runs a scenario of INT F6h calls through the engine's text services
 * (bios/bios_text.c) and prints the screen at every snap. tests/check_text.py runs the same
 * scenario through AdvBIOS's own code (re-tools/advbios_emu.py) and compares.
 *
 * Scenario lines (numbers decimal, HEX = hex):
 *   window X0 Y0 X1 Y1 | colour C | cursor X Y | bold AL | char DX(HEX) | string HEX-BYTES
 *   fillwin C | fillpage C | fillrect X0 Y0 X1 Y1 C | invert X0 Y0 X1 Y1 | pattern | snap NAME
 *   scroll DIR STEPS | scrollrect X0 Y0 X1 Y1 DIR STEPS
 * Output per snap: "snap NAME CURX CURY" then four lines, the planes in hex. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ax.h"
#include "bios/bios.h"
#include "test_hal.h"

static int hexval(int c)
{
    return c <= '9' ? c - '0' : (c | 0x20) - 'a' + 10;
}

int main(int argc, char **argv)
{
    struct lrv_hal hal;
    char line[4096];
    if (argc < 2 || th_hal(&hal, argv[1]) != 0) {
        fprintf(stderr, "usage: test_text PAK < SCENARIO\n");
        return 2;
    }
    memset(&ax, 0, sizeof ax);
    ax.hal = &hal;
    lrv_sys_init(&ax.sys, &hal, LRV_PC98_W, LRV_PC98_H);
    lrv_sys_set_present(&ax.sys, lrv_screen_present_hook, &ax.screen);
    if (lrv_pack_open(&ax.pack, &hal, LRV_PACK_MAIN) != LRV_OK ||
        lrv_font_load(&ax.font16, &ax.pack, "font16", 16, LRV_GLYPH_ROWS) != LRV_OK ||
        lrv_font_load(&ax.font8, &ax.pack, "font8", 8, LRV_GLYPH_ROWS) != LRV_OK ||
        lrv_screen_init(&ax.screen, &hal, &lrv_pc98_video_mode, 2, 0, LRV_MEM_ANY) != LRV_OK)
        return 2;
    bios_init();
    while (fgets(line, sizeof line, stdin)) {
        char op[32], arg[4000];
        int a[5] = { 0, 0, 0, 0, 0 };
        uint16_t r[4];
        arg[0] = 0;
        if (sscanf(line, "%31s", op) != 1)
            continue;
        if (!strcmp(op, "window") || !strcmp(op, "fillrect") || !strcmp(op, "invert")) {
            sscanf(line, "%*s %d %d %d %d %d", &a[0], &a[1], &a[2], &a[3], &a[4]);
            r[0] = (uint16_t)a[0]; r[1] = (uint16_t)a[1]; r[2] = (uint16_t)a[2]; r[3] = (uint16_t)a[3];
            if (op[0] == 'w') bt_set_window(r);
            else if (op[0] == 'f') bt_fill_rect(r, a[4]);
            else bt_invert_rect(r);
        } else if (!strcmp(op, "colour")) {
            sscanf(line, "%*s %d", &a[0]);
            bt_set_colour(a[0]);
        } else if (!strcmp(op, "cursor")) {
            sscanf(line, "%*s %d %d", &a[0], &a[1]);
            bt_set_cursor((unsigned)a[0], (unsigned)a[1]);
        } else if (!strcmp(op, "bold")) {
            sscanf(line, "%*s %d", &a[0]);
            bt_bold(a[0]);
        } else if (!strcmp(op, "char")) {
            sscanf(line, "%*s %x", (unsigned *)&a[0]);
            bt_draw_char((unsigned)a[0]);
        } else if (!strcmp(op, "string")) {
            uint8_t s[2000];
            size_t n = 0, i;
            sscanf(line, "%*s %3999s", arg);
            for (i = 0; arg[i] && arg[i + 1] && n < sizeof s - 2; i += 2)
                s[n++] = (uint8_t)(hexval(arg[i]) * 16 + hexval(arg[i + 1]));
            s[n] = 0;
            bt_draw_string(s);
        } else if (!strcmp(op, "fillwin")) {
            sscanf(line, "%*s %d", &a[0]);
            bt_fill_window(a[0]);
        } else if (!strcmp(op, "fillpage")) {
            sscanf(line, "%*s %d", &a[0]);
            bt_fill_page(a[0]);
        } else if (!strcmp(op, "scroll")) {
            sscanf(line, "%*s %d %d", &a[0], &a[1]);
            bt_scroll(a[0], (unsigned)a[1]);
        } else if (!strcmp(op, "scrollrect")) {
            {
                int v[6];
                sscanf(line, "%*s %d %d %d %d %d %d", &v[0], &v[1], &v[2], &v[3], &v[4], &v[5]);
                r[0] = (uint16_t)v[0]; r[1] = (uint16_t)v[1]; r[2] = (uint16_t)v[2]; r[3] = (uint16_t)v[3];
                bt_scroll_rect(r, v[4], (unsigned)v[5]);
            }
        } else if (!strcmp(op, "pattern")) {
            int p, i;
            for (p = 0; p < 4; p++)
                for (i = 0; i < AX_PLANE_BYTES; i++)
                    ax.screen.page[0].plane[p][i] = (uint8_t)((i * 7 + p * 29 + (i / 80) * 3) & 0xFF);
        } else if (!strcmp(op, "snap")) {
            int p, i;
            unsigned x, y;
            sscanf(line, "%*s %63s", arg);
            bt_cursor(&x, &y);
            printf("snap %s %u %u\n", arg, x, y);
            for (p = 0; p < 4; p++) {
                for (i = 0; i < AX_PLANE_BYTES; i++)
                    printf("%02x", ax.screen.page[0].plane[p][i]);
                putchar('\n');
            }
        } else {
            fprintf(stderr, "test_text: unknown op %s\n", op);
            return 2;
        }
    }
    lrv_screen_free(&ax.screen);
    lrv_font_free(&ax.font8);
    lrv_font_free(&ax.font16);
    lrv_pack_close(&ax.pack);
    return 0;
}
