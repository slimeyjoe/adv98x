/* SPDX-License-Identifier: GPL-3.0-or-later */
/* test_gpc decode FILE...       per file: "w h x y interleave palette(16 x 0GRB or -) fnv64"
 *                               of the decoded pixels (w*h palette indexes, row-major)
 * test_gpc draw FILE XB Y MASKED  the picture drawn as INT F3h AH=01h (XB 65535 = the file's
 *                               position) over a fixed background: fnv64 of the four planes
 * tests/check_gpc.py compares both with source/tools/gpc.py. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ax_internal.h"
#include "gfx/gpc.h"
#include "hal_file.h"

static uint8_t *read_file(const char *path, uint32_t *size)
{
    FILE *f = fopen(path, "rb");
    uint8_t *d;
    long n;
    if (!f)
        return 0;
    fseek(f, 0, SEEK_END);
    n = ftell(f);
    fseek(f, 0, SEEK_SET);
    d = malloc((size_t)n);
    if (d && fread(d, 1, (size_t)n, f) != (size_t)n) {
        free(d);
        d = 0;
    }
    fclose(f);
    *size = (uint32_t)n;
    return d;
}

static uint64_t fnv(uint64_t h, const uint8_t *p, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++)
        h = (h ^ p[i]) * 1099511628211ull;
    return h;
}

int main(int argc, char **argv)
{
    struct ax_hal hal;
    int i;
    tf_hal(&hal, 0);
    memset(&ax, 0, sizeof ax);
    ax.hal = &hal;
    if (argc >= 3 && !strcmp(argv[1], "decode")) {
        for (i = 2; i < argc; i++) {
            uint32_t size, rs;
            uint8_t *d = read_file(argv[i], &size), *rows, *pix;
            struct gpc_info g;
            int bw, y, x, k;
            if (!d || gpc_parse(d, size, &g) != 0) {
                printf("%s bad\n", argv[i]);
                continue;
            }
            bw = (g.w + 7) >> 3;
            rs = gpc_rows_size(&g);
            rows = malloc(rs ? rs : 1);
            pix = malloc((size_t)g.w * (size_t)g.h + 1);
            gpc_decode_rows(d, size, &g, rows);
            for (y = 0; y < g.h; y++)
                for (x = 0; x < g.w; x++) {
                    int v = 0, bit = 7 - (x & 7);
                    for (k = 0; k < 4; k++)
                        v |= ((rows[(size_t)y * 4 * bw + k * bw + x / 8] >> bit) & 1) << k;
                    pix[(size_t)y * g.w + x] = (uint8_t)v;
                }
            printf("%d %d %d %d %d ", g.w, g.h, g.x, g.y, g.interleave);
            if (g.has_palette)
                for (k = 0; k < 16; k++)
                    printf("%03X%s", g.palette[k], k < 15 ? "," : " ");
            else
                printf("- ");
            printf("%016llx\n", (unsigned long long)fnv(1469598103934665603ull, pix,
                                                        (size_t)g.w * (size_t)g.h));
            free(rows);
            free(pix);
            free(d);
        }
        return 0;
    }
    if (argc == 6 && !strcmp(argv[1], "draw")) {
        uint32_t size;
        uint8_t *d = read_file(argv[2], &size);
        static uint8_t mem[4][AX_PLANE_BYTES];
        struct ax_planes pl;
        uint64_t h = 1469598103934665603ull;
        int p, xb = atoi(argv[3]);
        for (p = 0; p < 4; p++) {
            pl.p[p] = mem[p];
            for (i = 0; i < AX_PLANE_BYTES; i++)
                mem[p][i] = (uint8_t)((i * 7 + p * 29 + (i / 80) * 3) & 0xFF);
        }
        if (!d || gpc_draw(d, size, &pl, xb == 65535 ? -1 : xb, atoi(argv[4]), atoi(argv[5]), 0))
            return 1;
        for (p = 0; p < 4; p++)
            h = fnv(h, mem[p], AX_PLANE_BYTES);
        printf("%016llx\n", (unsigned long long)h);
        free(d);
        return 0;
    }
    fprintf(stderr, "usage: test_gpc decode FILE... | draw FILE XB Y MASKED\n");
    return 2;
}
