/* SPDX-License-Identifier: GPL-3.0-or-later */
/* GPC decoder (gpc.h). Every step follows source/tools/gpc.py, which is bit-exact with the
 * original decoder under emulation on all 103 distinct GPC files (re-tools/gpc_verify.py). */
#include <string.h>
#include "ax.h"
#include "gfx/gpc.h"
#include "lrvne/endian.h"

static const uint8_t gpc_magic[16] = "PC98)GPCFILE   ";

int gpc_parse(const uint8_t *d, uint32_t n, struct gpc_info *g)
{
    uint32_t pal, img;
    int i;
    memset(g, 0, sizeof *g);
    if (n < 0x30 || memcmp(d, gpc_magic, 16) != 0)
        return -1;
    g->interleave = (int)lrv_rd32le(d + 0x10);
    pal = lrv_rd32le(d + 0x14);
    img = lrv_rd32le(d + 0x18);
    if (img > n || n - img < 16)
        return -1;
    if (pal) {
        unsigned count;
        if (pal > n || n - pal < 4)
            return -1;
        count = lrv_rd16le(d + pal);
        if (count > 16)
            count = 16;
        if (n - pal - 4 < 2 * count)
            return -1;
        for (i = 0; i < (int)count; i++)
            g->palette[i] = lrv_rd16le(d + pal + 4 + 2 * i);
        g->has_palette = 1;
    }
    g->w = lrv_rd16le(d + img);
    g->h = lrv_rd16le(d + img + 2);
    if (lrv_rd16le(d + img + 8) != 4)               /* bits per pixel */
        return -1;
    g->x = lrv_rd16le(d + img + 10);
    g->y = lrv_rd16le(d + img + 12);
    g->stream = img + 16;
    return 0;
}

uint32_t gpc_rows_size(const struct gpc_info *g)
{
    return (uint32_t)g->h * 4u * (uint32_t)((g->w + 7) >> 3);
}

/* Layer 1, zero suppression (gpc.py unpack_stream): control byte A, MSB first: bit clear ->
 * 8 zero bytes; bit set -> mask byte B, MSB first: clear -> a zero byte, set -> a literal.
 * Stops at out_len or at the end of the input (the rest stays zero). */
static void unpack_stream(const uint8_t *d, uint32_t n, uint32_t pos, uint8_t *out, uint32_t out_len)
{
    uint32_t o = 0;
    memset(out, 0, out_len);
    while (o < out_len) {
        unsigned a, abit;
        if (pos >= n)
            return;
        a = d[pos++];
        if (a == 0) {
            o += 64;
            continue;
        }
        for (abit = 0x80; abit && o < out_len; abit >>= 1) {
            unsigned b, bbit;
            if (!(a & abit)) {
                o += 8;
                continue;
            }
            if (pos >= n)
                return;
            b = d[pos++];
            for (bbit = 0x80; bbit; bbit >>= 1) {
                if (b & bbit) {
                    if (pos >= n)
                        return;
                    if (o < out_len)
                        out[o] = d[pos];
                    pos++;
                }
                o++;
            }
        }
    }
}

int gpc_decode_rows(const uint8_t *d, uint32_t n, const struct gpc_info *g, uint8_t *rows)
{
    uint32_t row_len = 4u * (uint32_t)((g->w + 7) >> 3), stride = row_len + 1;
    uint32_t buf_len = stride * (uint32_t)g->h, r, i;
    uint8_t *buf;
    int step = g->interleave, start, dst, src;

    if (!g->h || !row_len)
        return 0;
    buf = lrv_alloc(ax.hal, buf_len);
    if (!buf)
        return -1;
    unpack_stream(d, n, g->stream, buf, buf_len);
    /* Layer 2: a running XOR along `step` interleaved chains, the accumulator carried over
     * from chain to chain; then every row is XORed with the row stored before it. Done in
     * stored order, into the stored-order slots of `buf` (rows only move in layer 3). */
    for (r = 0; r < (uint32_t)g->h; r++) {
        uint8_t *row = buf + r * stride + 1;
        unsigned f = buf[r * stride];
        if (f) {
            uint8_t acc = 0;
            uint32_t s;
            for (s = 0; s < f && s < row_len; s++)
                for (i = s; i < row_len; i += f) {
                    acc ^= row[i];
                    row[i] = acc;
                }
        }
        if (r > 0) {
            const uint8_t *prev = row - stride;
            for (i = 0; i < row_len; i++)
                row[i] ^= prev[i];
        }
    }
    /* Layer 3: stored rows are dealt out to screen rows 0, N, 2N, ..., 1, N+1, ... */
    if (step <= 1)
        step = 1;
    src = 0;
    for (start = 0; start < step && start < g->h; start++)
        for (dst = start; dst < g->h; dst += step) {
            memcpy(rows + (uint32_t)dst * row_len, buf + (uint32_t)src * stride + 1, row_len);
            src++;
        }
    lrv_free(ax.hal, buf, buf_len);
    return 0;
}

int gpc_draw(const uint8_t *d, uint32_t n, struct lrv_surface *dst, int xb, int y, int masked,
             struct lrv_rect *written)
{
    struct gpc_info g;
    uint32_t rsize;
    uint8_t *rows;
    int bw, r, p, k;

    if (written)
        lrv_rect_clear(written);
    if (gpc_parse(d, n, &g) != 0)
        return -1;
    if (xb < 0) {
        xb = g.x >> 3;
        y = g.y;
    }
    bw = (g.w + 7) >> 3;
    rsize = gpc_rows_size(&g);
    rows = lrv_alloc(ax.hal, rsize ? rsize : 1);
    if (!rows)
        lrv_fatal(ax.hal, "out of memory (picture)");
    if (gpc_decode_rows(d, n, &g, rows) != 0)
        lrv_fatal(ax.hal, "out of memory (picture)");
    for (r = 0; r < g.h; r++) {
        long off = (long)(y + r) * LRV_PC98_STRIDE + xb;
        const uint8_t *row = rows + (uint32_t)r * 4u * (uint32_t)bw;
        for (k = 0; k < bw; k++, off++) {
            uint8_t b0, b1, b2, b3, m;
            if (off < 0 || off >= AX_PLANE_BYTES)
                continue;
            b0 = row[k]; b1 = row[bw + k]; b2 = row[2 * bw + k]; b3 = row[3 * bw + k];
            if (!masked) {
                dst->plane[0][off] = b0; dst->plane[1][off] = b1;
                dst->plane[2][off] = b2; dst->plane[3][off] = b3;
            } else {
                m = (uint8_t)(b0 | b1 | b2 | b3);
                for (p = 0; p < 4; p++) {
                    uint8_t s = p == 0 ? b0 : p == 1 ? b1 : p == 2 ? b2 : b3;
                    dst->plane[p][off] = (uint8_t)((dst->plane[p][off] & ~m) | (s & m));
                }
            }
            if (written) {
                int wy = (int)(off / LRV_PC98_STRIDE), wx = (int)(off % LRV_PC98_STRIDE);
                lrv_rect_add(written, wx, wy, wx + 1, wy + 1);
            }
        }
    }
    lrv_free(ax.hal, rows, rsize ? rsize : 1);
    return 0;
}
