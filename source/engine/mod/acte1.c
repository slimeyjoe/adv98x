/* SPDX-License-Identifier: GPL-3.0-or-later */
/* ACTE1.TCM: screen blocks (docs/re/plugins.md §6, §7.5). Commands are recognised by their first
 * letter, operands are unsigned decimal, `,` joins commands. x and w in byte columns, y and h in
 * lines; all four planes of the current drawing page. All commands; HALT (a debugging screen)
 * is a no-op. NOVA uses INIT, GET, PUT and FREE. */
#include <string.h>
#include "ax.h"
#include "bios/bios.h"
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
        lrv_free(ax.hal, st.slot[n].data, st.slot[n].size);
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
    lrv_log(ax.hal, LRV_LOG_ERROR, "ACTE] > %s : %s", cmd, what);
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
    struct lrv_surface *pg = lrv_screen_access(&ax.screen);
    uint32_t size = (uint32_t)w * h * 4u, k = 0;
    unsigned p, r, c;
    if ((uint32_t)w * h >= 16384u) {
        fail("GET", "Oversize");
        return;
    }
    if (n >= SLOTS)
        n &= SLOTS - 1;                 /* the original corrupts memory (§6.2) */
    free_slot((int)n);
    st.slot[n].data = lrv_xalloc(ax.hal, size ? size : 1);
    st.slot[n].size = size ? size : 1;
    st.slot[n].w = w;
    st.slot[n].h = h;
    for (p = 0; p < 4; p++)
        for (r = 0; r < h; r++)
            for (c = 0; c < w; c++) {
                uint32_t off = ((y + r) * 80u + x + c) & 0xFFFF;
                st.slot[n].data[k++] = off < AX_PLANE_BYTES ? pg->plane[p][off] : 0;
            }
}

static void put(unsigned n, unsigned x, unsigned y)
{
    struct lrv_surface *pg = lrv_screen_access(&ax.screen);
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
        lrv_sys_frame_wait(&ax.sys);   /* wait for the start of the next VSYNC */
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
                    pg->plane[p][sy * 80 + sx] =
                        (uint8_t)((pg->plane[p][sy * 80 + sx] & ~m) | (v & m));
                } else {
                    pg->plane[p][sy * 80 + sx] = v;
                }
            }
    lrv_screen_mark(&ax.screen, ax.screen.access_page, (int)x, (int)y, (int)(x + w), (int)(y + h));
}

/* a rectangle of `page` (byte columns, lines) into `buf`, plane after plane, no clipping */
static void grab(int page, unsigned x, unsigned y, unsigned w, unsigned h, uint8_t *buf)
{
    unsigned p, r, c, k = 0;
    for (p = 0; p < 4; p++)
        for (r = 0; r < h; r++)
            for (c = 0; c < w; c++) {
                uint32_t off = ((y + r) * 80u + x + c) & 0xFFFF;
                buf[k++] = off < AX_PLANE_BYTES ? ax.screen.page[page].plane[p][off] : 0;
            }
}

/* `buf` to `page` at (x, y); overlay: source colour 0 keeps the destination */
static void drop(int page, unsigned x, unsigned y, unsigned w, unsigned h, const uint8_t *buf)
{
    unsigned p, r, c;
    for (r = 0; r < h; r++)
        for (c = 0; c < w; c++) {
            uint32_t off = ((y + r) * 80u + x + c) & 0xFFFF;
            uint8_t m = 0xFF;
            if (off >= AX_PLANE_BYTES)
                continue;
            if (st.over) {
                m = 0;
                for (p = 0; p < 4; p++)
                    m |= buf[((uint32_t)p * h + r) * w + c];
            }
            for (p = 0; p < 4; p++) {
                uint8_t *d = &ax.screen.page[page].plane[p][off];
                *d = (uint8_t)((*d & ~m) | (buf[((uint32_t)p * h + r) * w + c] & m));
            }
        }
    lrv_screen_mark(&ax.screen, page, 0, (int)y, LRV_PC98_STRIDE, (int)(y + h + 1));
}

static void copy(unsigned sp, unsigned x, unsigned y, unsigned w, unsigned h, unsigned dp,
                 unsigned x2, unsigned y2)
{
    uint8_t *buf;
    uint32_t size = (uint32_t)w * h * 4u;
    if (sp > 1 || dp > 1 || x > 80 || y > 400 || (uint32_t)w * h >= 16384u) {
        fail("COPY", "Overspec number");
        return;
    }
    buf = lrv_xalloc(ax.hal, size ? size : 1);
    grab((int)sp, x, y, w, h, buf);
    drop((int)dp, x2, y2, w, h, buf);
    lrv_free(ax.hal, buf, size ? size : 1);
    st.acce = (int)dp;                          /* COPY leaves the drawing page at dp */
    lrv_screen_set_access(&ax.screen, (int)dp);
}

/* MOVE: within the drawing page, plane by plane, rows top to bottom, bytes left to right */
static void move(unsigned x, unsigned y, unsigned w, unsigned h, unsigned x2, unsigned y2)
{
    struct lrv_surface *pg = lrv_screen_access(&ax.screen);
    unsigned p, r, c;
    if (x >= 80 || x2 >= 80 || y >= 400 || y2 >= 400 || (uint32_t)w * h >= 16384u) {
        fail("MOVE", "Overspec number");
        return;
    }
    for (p = 0; p < 4; p++)
        for (r = 0; r < h; r++)
            for (c = 0; c < w; c++) {
                uint32_t so = ((y + r) * 80u + x + c) & 0xFFFF, d = ((y2 + r) * 80u + x2 + c) & 0xFFFF;
                uint8_t m = 0xFF, v;
                unsigned q;
                if (so >= AX_PLANE_BYTES || d >= AX_PLANE_BYTES)
                    continue;
                v = pg->plane[p][so];
                if (st.over) {
                    m = 0;
                    for (q = 0; q < 4; q++)
                        m |= pg->plane[q][so];
                }
                pg->plane[p][d] = (uint8_t)((pg->plane[p][d] & ~m) | (v & m));
            }
    lrv_screen_mark(&ax.screen, ax.screen.access_page, 0, (int)y2, LRV_PC98_STRIDE,
                    (int)(y2 + h + 1));
}

/* LOAD: a GPC picture by name (the next token, at most 40 characters), drawn at its own
 * position into the drawing page with its palette (flags 3), colour 0 transparent in overlay
 * mode; a read error is not checked: the buffer is drawn as it is */
static void load(const uint8_t **pp)
{
    char name[41];
    unsigned n = 0;
    uint32_t cap;
    uint8_t *buf = bg_picture_buffer(&cap);
    long len;
    const uint8_t *p = *pp;
    while (*p == ' ' || *p == '\t')
        p++;
    while (*p && *p != ' ' && *p != ',' && *p != '"' && n < 40)
        name[n++] = (char)*p++;
    name[n] = 0;
    *pp = p;
    len = bios_file_load(name, buf, cap);
    if (len >= 0)
        ax.bios.piclen = (uint32_t)len;
    bg_draw_gpc(buf, ax.bios.piclen, 0xFFFF, 0xFFFF, st.over, 3);
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
                lrv_sys_frame_wait(&ax.sys);
            break;
        case 's':
            a = number(&p);
            if (a > 1) {
                fail("SHOW", "Overspec number");
                break;
            }
            st.show = (int)a;
            lrv_sys_frame_wait(&ax.sys);   /* wait for the start of a VSYNC */
            lrv_screen_set_display(&ax.screen, (int)a);
            break;
        case 'a':
            a = number(&p);
            if (a > 1) {
                fail("ACCE", "Overspec number");
                break;
            }
            st.acce = (int)a;
            lrv_screen_set_access(&ax.screen, (int)a);
            break;
        case 'c': {
            unsigned f, g, hh;
            a = number(&p); b = number(&p); cc = number(&p); d = number(&p); e = number(&p);
            f = number(&p); g = number(&p); hh = number(&p);
            if (st.error)
                return 0xFF00;
            copy(a, b, cc, d, e, f, g, hh);
            break;
        }
        case 'm': {
            unsigned f;
            a = number(&p); b = number(&p); cc = number(&p); d = number(&p); e = number(&p);
            f = number(&p);
            if (st.error)
                return 0xFF00;
            move(a, b, cc, d, e, f);
            break;
        }
        case 'l':
            if (st.error)
                return 0xFF00;
            load(&p);
            break;
        case 'e':
            drop_slots();
            return 0xFF00;
        case 'h':
            return 0xFF00;
        default:
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
