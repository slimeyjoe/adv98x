/* SPDX-License-Identifier: GPL-3.0-or-later */
/* ACTE1.TCM: screen blocks (docs/re/plugins.md §6, §7.5). Commands are recognised by their first
 * letter, operands are unsigned decimal, `,` joins commands. x and w in byte columns, y and h in
 * lines; all four planes of the current drawing page. Done: INIT, GET, PUT, FREE, OVER, VIEW,
 * WAIT, EXIT, HALT (no-op); SHOW, ACCE, COPY, MOVE, LOAD arrive with M5. */
#include <string.h>
#include "ax_internal.h"
#include "gfx/gfx.h"
#include "mod/mod.h"

#define SLOTS 64

static struct {
    int table;                          /* a slot table exists (INIT) */
    int error;
    int show, acce, over;
    unsigned view[4];
    struct { uint8_t *data; unsigned w, h; uint32_t size; } slot[SLOTS];
} st;

static void free_slot(int n)
{
    if (st.slot[n].data)
        sys_free(st.slot[n].data, st.slot[n].size);
    memset(&st.slot[n], 0, sizeof st.slot[n]);
}

static void drop_slots(void)
{
    int n;
    for (n = 0; n < SLOTS; n++)
        free_slot(n);
    st.table = 0;
}

/* load-mem of the file: everything kept in the image goes back to the file's contents (the
 * table pointer, the error flag, the page, overlay and view settings); the old blocks leak in
 * the original, here they are freed: a new INIT starts with 64 empty slots either way (§6.5) */
static void acte1_load(void)
{
    drop_slots();
    st.error = 0;
    st.show = st.acce = st.over = 0;
    st.view[0] = 0; st.view[1] = 0; st.view[2] = 79; st.view[3] = 399;
}

static void fail(const char *cmd, const char *what)
{
    sys_log(AX_LOG_ERROR, "ACTE] > %s : %s", cmd, what);
    st.error = 1;
}

static unsigned number(const uint8_t **pp)
{
    const uint8_t *p = *pp;
    unsigned v = 0;
    while (*p == ' ' || *p == '\t')
        p++;
    while (*p >= '0' && *p <= '9')
        v = (v * 10 + (unsigned)(*p++ - '0')) & 0xFFFF;
    *pp = p;
    return v;
}

static void get(unsigned n, unsigned x, unsigned y, unsigned w, unsigned h)
{
    struct ax_planes *pg = gfx_access();
    uint32_t size = (uint32_t)w * h * 4u, k = 0;
    unsigned p, r, c;
    if ((uint32_t)w * h >= 16384u) {
        fail("GET", "Oversize");
        return;
    }
    if (n >= SLOTS)
        n &= SLOTS - 1;                 /* the original corrupts memory (§6.2) */
    free_slot((int)n);
    st.slot[n].data = sys_alloc(size ? size : 1);
    st.slot[n].size = size ? size : 1;
    st.slot[n].w = w;
    st.slot[n].h = h;
    for (p = 0; p < 4; p++)
        for (r = 0; r < h; r++)
            for (c = 0; c < w; c++) {
                uint32_t off = ((y + r) * 80u + x + c) & 0xFFFF;
                st.slot[n].data[k++] = off < AX_PLANE_BYTES ? pg->p[p][off] : 0;
            }
}

static void put(unsigned n, unsigned x, unsigned y)
{
    struct ax_planes *pg = gfx_access();
    unsigned p, r, c, w, h;
    const uint8_t *d;
    if (n >= SLOTS) {
        fail("PUT", "Overspec number");
        return;
    }
    if (!st.slot[n].data) {
        fail("PUT", "Accessed null pointer");
        return;
    }
    w = st.slot[n].w;
    h = st.slot[n].h;
    d = st.slot[n].data;
    if (!st.over && st.show == st.acce)
        sys_frame_wait();               /* wait for the start of the next VSYNC */
    for (p = 0; p < 4; p++)
        for (r = 0; r < h; r++)
            for (c = 0; c < w; c++) {
                unsigned sx = x + c, sy = y + r;
                uint8_t v = d[((uint32_t)p * h + r) * w + c];
                if (sx < st.view[0] || sx > st.view[2] || sx > 79 ||
                    sy < st.view[1] || sy > st.view[3] || sy > 399)
                    continue;
                if (st.over) {
                    uint8_t m = 0;
                    unsigned q;
                    for (q = 0; q < 4; q++)
                        m |= d[((uint32_t)q * h + r) * w + c];
                    pg->p[p][sy * 80 + sx] = (uint8_t)((pg->p[p][sy * 80 + sx] & ~m) | (v & m));
                } else {
                    pg->p[p][sy * 80 + sx] = v;
                }
            }
    gfx_mark_dirty(ax.access_page, (int)x, (int)y, (int)(x + w), (int)(y + h));
}

static unsigned long acte1_exec(const uint16_t *args, int nargs)
{
    const uint8_t *p;
    if (nargs < 1)
        return 0xFF00;
    p = mod_string(args[0]);
    for (;;) {
        int c = *p | 0x20;
        unsigned a, b, cc, d, e;
        /* skip the rest of the command word */
        while (*p && *p != ' ' && *p != '\t' && *p != '"' && *p != ',')
            p++;
        switch (c) {
        case 'i':                       /* page, overlay and view are kept */
            st.error = 0;
            drop_slots();
            st.table = 1;
            break;
        case 'g':
            a = number(&p); b = number(&p); cc = number(&p); d = number(&p); e = number(&p);
            if (st.error)
                return 0xFF00;
            get(a, b, cc, d, e);
            break;
        case 'p':
            a = number(&p); b = number(&p); cc = number(&p);
            if (st.error)
                return 0xFF00;
            put(a, b, cc);
            break;
        case 'f':
            a = number(&p);
            if (a >= SLOTS)
                fail("FREE", "Overspec number");
            else
                free_slot((int)a);
            break;
        case 'o':
            st.over = number(&p) != 0;
            break;
        case 'v':
            st.view[0] = number(&p); st.view[1] = number(&p);
            st.view[2] = number(&p); st.view[3] = number(&p);
            if (st.view[2] < st.view[0] || st.view[3] < st.view[1] || st.view[2] > 79 ||
                st.view[3] > 399)
                fail("VIEW", "Overspec number");
            break;
        case 'w':
            a = number(&p);
            while (a--)
                sys_frame_wait();
            break;
        case 'e':
            drop_slots();
            return 0xFF00;
        case 'h':
            return 0xFF00;
        default:
            if (c == 's' || c == 'a' || c == 'c' || c == 'm' || c == 'l')
                sys_log(AX_LOG_WARN, "ACTE1: command %c not implemented yet (M5)", c);
            return 0xFF00;
        }
        if (st.error)
            return 0xFF00;
        while (*p == ' ' || *p == '\t')
            p++;
        if (*p != ',')
            return 0xFF00;
        p++;
    }
}

const struct ax_module mod_acte1 = { "ACTE1", acte1_load, acte1_exec };
