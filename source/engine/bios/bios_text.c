/* SPDX-License-Identifier: GPL-3.0-or-later */
/* INT F6h, text and simple drawing: AdvBIOS 0000:0A26-0D8F (docs/re/advbios.md §4.2, §5.2).
 * Drawing goes to the access page as the GRCG does it: characters in RMW mode (set glyph pixels
 * take the colour, clear ones leave the page alone), fills in TDW mode (every pixel takes the
 * colour). VRAM offsets are 16-bit y * 80 + x as in the original; nothing is written outside
 * the 32000 visible bytes of a plane. */
#include <string.h>
#include "ax.h"
#include "bios/bios.h"

#define B (ax.bios)

/* ---- VRAM access through the GRCG ---------------------------------------------------------- */

/* a run of n bytes at VRAM offset off was written (a run over the right edge goes on in the
 * next line) */
static void mark(unsigned off, unsigned n)
{
    lrv_screen_mark_off(&ax.screen, ax.screen.access_page, (int)off, (int)n, 1);
}

/* RMW: plane = (plane & ~mask) | (tile & mask), tile = all ones where the colour has the bit */
static void rmw_byte(unsigned off, uint8_t mask, int colour)
{
    struct lrv_surface *pg = lrv_screen_access(&ax.screen);
    int p;
    off &= 0xFFFF;
    if (off >= AX_PLANE_BYTES)
        return;
    for (p = 0; p < 4; p++) {
        uint8_t tile = (colour >> p) & 1 ? 0xFF : 0x00;
        pg->plane[p][off] = (uint8_t)((pg->plane[p][off] & ~mask) | (tile & mask));
    }
}

/* TDW: plane = tile */
static void tdw_run(unsigned off, unsigned n, int colour)
{
    struct lrv_surface *pg = lrv_screen_access(&ax.screen);
    unsigned i;
    int p;
    for (i = 0; i < n; i++) {
        unsigned o = (off + i) & 0xFFFF;
        if (o >= AX_PLANE_BYTES)
            continue;
        for (p = 0; p < 4; p++)
            pg->plane[p][o] = (colour >> p) & 1 ? 0xFF : 0x00;
    }
    mark(off & 0xFFFF, n);
}

/* ---- window, colour, cursor ---------------------------------------------------------------- */

/* clamp_sort_pair 0000:0A5C: both clamped to `max`, then sorted (unsigned) */
static void clamp_sort(uint16_t *a, uint16_t *b, uint16_t max)
{
    if (*a > max) *a = max;
    if (*b > max) *b = max;
    if (!(*a < *b)) {
        uint16_t t = *a;
        *a = *b;
        *b = t;
    }
}

void bt_set_window(const uint16_t rect[4])
{
    memcpy(B.win, rect, sizeof B.win);
    clamp_sort(&B.win[0], &B.win[2], 79);
    clamp_sort(&B.win[1], &B.win[3], 399);
}

void bt_get_window(uint16_t rect[4])
{
    memcpy(rect, B.win, sizeof B.win);
}

void bt_set_colour(int c)
{
    B.colour = (uint8_t)(c & 15);
}

int bt_colour(void)
{
    return B.colour;
}

void bt_set_cursor(unsigned x, unsigned y)
{
    B.cur_x = (uint16_t)x;
    B.cur_y = (uint16_t)y;
}

void bt_cursor(unsigned *x, unsigned *y)
{
    *x = B.cur_x;
    *y = B.cur_y;
}

void bt_set_delay(unsigned ticks, int al)
{
    B.delay = (uint16_t)ticks;
    B.delay_skip = (uint16_t)(int16_t)(int8_t)al;    /* cbw */
}

void bt_set_beep(unsigned ticks)
{
    B.beep = (uint16_t)ticks;
}

int bt_bold(int al)
{
    al &= 0xFF;
    if (al <= 1)
        B.bold = (uint8_t)al;
    return B.bold;
}

/* ---- characters ---------------------------------------------------------------------------- */

/* 0000:024C: Shift-JIS -> JIS with 8-bit arithmetic and no validation */
unsigned bios_sjis_to_jis(unsigned dx)
{
    uint8_t dh = (uint8_t)(dx >> 8), dl = (uint8_t)dx;
    dh = (uint8_t)(dh - 0x70);
    if (dh >= 0x30)
        dh = (uint8_t)(dh - 0x40);
    dh = (uint8_t)(dh << 1);
    if (dl > 0x7F)
        dl--;
    if (dl >= 0x9E) {
        dl = (uint8_t)(dl - 0x5E);
        dh++;
    }
    dh--;
    dl = (uint8_t)(dl - 0x1F);
    return ((unsigned)dh << 8) | dl;
}

/* text_newline 0000:0C7C: x = x0; y += 20, back to y0 when that reaches y1 */
static void newline(void)
{
    uint16_t y = (uint16_t)(B.cur_y + 20);
    B.cur_x = B.win[0];
    B.cur_y = y < B.win[3] ? y : B.win[1];
}

/* is_punctuation_jis 0000:0C60: JIS 2121..212A, 2144, 2145 */
static int punctuation(void)
{
    unsigned c = B.last_char;
    if ((c >> 8) != 0x21)
        return 0;
    c &= 0xFF;
    return c <= 0x2A || c == 0x44 || c == 0x45;
}

/* text_wait_ticks 0000:0C36 with text_skip_check 0000:0C48 */
static void text_wait(unsigned ticks)
{
    bios_delay(ticks, B.delay_skip != 0);
}

/* MakeCharBold 0000:0BFC: every row ORed with itself shifted right one pixel; when the
 * rightmost pixel was set, the pixel left of it is set as well (the bit shifted out is put back
 * as bit 1) */
static void make_bold(uint8_t *rows, int width)
{
    int r;
    for (r = 0; r < 16; r++) {
        if (width != 2) {
            uint8_t a = rows[r], s = (uint8_t)(a >> 1);
            if (a & 1)
                s |= 2;
            rows[r] = (uint8_t)(a | s);
        } else {
            uint8_t l = rows[2 * r], h = rows[2 * r + 1];
            uint8_t sl = (uint8_t)(l >> 1), sh = (uint8_t)((h >> 1) | ((l & 1) << 7));
            if (h & 1)
                sh |= 2;
            rows[2 * r] = (uint8_t)(l | sl);
            rows[2 * r + 1] = (uint8_t)(h | sh);
        }
    }
}

/* apiF6_09_DrawChar 0000:0AB0 */
void bt_draw_char(unsigned dx)
{
    uint8_t rows[32];
    int width, r;
    unsigned off;

    dx &= 0xFFFF;
    if (!(dx >> 8)) {
        unsigned dl = dx & 0xFF;
        if (dl == 0x0D) {
            newline();
            goto after;                 /* the beep and delay of the last character apply */
        }
        if (dl < 0x20)
            return;
        if (dl <= 0x7E)
            dx = 0x2900 | dl;
        else if (dl >= 0xA0 && dl <= 0xDF)
            dx = 0x2A00 | (dl - 0x80);
        else
            return;
    } else {
        dx = bios_sjis_to_jis(dx);
    }
    B.last_char = (uint16_t)dx;
    width = lrv_font_rom_glyph(&ax.font16, &ax.font8, dx, rows);
    if (B.bold)
        make_bold(rows, width);
    if (B.colour == B.lip_colour[0])
        B.lip_count[0]++;
    if (B.colour == B.lip_colour[1])
        B.lip_count[1]++;
    if (width == 2 && B.cur_x >= B.win[2])
        newline();
    off = (unsigned)(uint16_t)(80u * B.cur_y + B.cur_x);
    for (r = 0; r < 16; r++) {
        if (width == 2) {
            rmw_byte(off, rows[2 * r], B.colour);
            rmw_byte(off + 1, rows[2 * r + 1], B.colour);
        } else {
            rmw_byte(off, rows[r], B.colour);
        }
        mark(off & 0xFFFF, (unsigned)width);
        off = (off + 80) & 0xFFFF;
    }
    B.cur_x = (uint16_t)(B.cur_x + width);
    if (B.cur_x > B.win[2])
        newline();
after:
    if (B.beep) {
        if (!punctuation())
            bios_beep(1);
        text_wait(B.beep);
        bios_beep(0);
    }
    if (B.delay)
        text_wait(B.delay + (punctuation() ? 25u : 0u));
}

/* apiF6_0A_DrawText 0000:0C96: a lead byte 81-9F / E0-FC takes the next byte with it, whatever
 * it is; 00h or FFh ends the string */
void bt_draw_string(const uint8_t *s)
{
    for (;;) {
        unsigned a = s[0];
        if (a == 0 || a == 0xFF)
            return;
        if ((a >= 0x81 && a <= 0x9F) || (a >= 0xE0 && a <= 0xFC)) {
            bt_draw_char((a << 8) | s[1]);
            s += 2;
        } else {
            bt_draw_char(a);
            s += 1;
        }
    }
}

/* ---- fills ----------------------------------------------------------------------------------- */

/* rect_to_vram 0000:0CF8 + grcg_fill 0000:0D12: lines and bytes counted as 16-bit, a run per
 * line of x1 - x0 + 1 bytes from y * 80 + x0 */
static void fill(const uint16_t rect[4], int c)
{
    unsigned off = (uint16_t)(80u * rect[1] + rect[0]);
    unsigned n = (uint16_t)(rect[2] - rect[0] + 1);
    unsigned lines = (uint16_t)(rect[3] - rect[1] + 1);
    if (!lines)
        lines = 0x10000;
    while (lines--) {
        tdw_run(off, n, c);
        off = (off + 80) & 0xFFFF;
    }
}

void bt_fill_window(int c)
{
    fill(B.win, c);
    B.cur_x = B.win[0];
    B.cur_y = B.win[1];
}

void bt_fill_page(int c)
{
    static const uint16_t all[4] = { 0, 0, 79, 399 };
    fill(all, c);
}

void bt_fill_rect(const uint16_t rect[4], int c)
{
    fill(rect, c);
}

/* apiF6_0E_InvertRect 0000:0D64: XOR FFh, plane by plane */
void bt_invert_rect(const uint16_t rect[4])
{
    struct lrv_surface *pg = lrv_screen_access(&ax.screen);
    unsigned off0 = (uint16_t)(80u * rect[1] + rect[0]);
    unsigned n = (uint16_t)(rect[2] - rect[0] + 1);
    unsigned lines = (uint16_t)(rect[3] - rect[1] + 1), l, i;
    int p;
    if (!lines)
        lines = 0x10000;
    for (p = 0; p < 4; p++) {
        unsigned off = off0;
        for (l = 0; l < lines; l++) {
            for (i = 0; i < (n ? n : 0x10000u); i++) {
                unsigned o = (off + i) & 0xFFFF;
                if (o < AX_PLANE_BYTES)
                    pg->plane[p][o] ^= 0xFF;
            }
            if (p == 0)
                mark(off, n);
            off = (off + 80) & 0xFFFF;
        }
    }
}

/* ---- scrolling: scroll_dispatch 0000:0EEE, the CPU paths 0FA4 / 102E (advbios.md §5.5) ----- */

static uint8_t vb(int p, unsigned off)
{
    off &= 0xFFFF;
    return off < AX_PLANE_BYTES ? lrv_screen_access(&ax.screen)->plane[p][off] : 0;
}

static void vset(int p, unsigned off, uint8_t v)
{
    off &= 0xFFFF;
    if (off < AX_PLANE_BYTES)
        lrv_screen_access(&ax.screen)->plane[p][off] = v;
}

/* one step: AL = 0 up, 1 down (by a line), 2 left, 3 right (by a byte column) */
static void scroll_step(int dir)
{
    unsigned x0 = B.win[0], y0 = B.win[1], x1 = B.win[2], y1 = B.win[3];
    unsigned rows, w, r, i, si, di;
    int p, bx;
    lrv_sys_frame_wait(&ax.sys);   /* one VSYNC per step */
    if (dir == 0 || dir == 1) {
        rows = (uint16_t)(y1 - y0);
        w = (uint16_t)(x1 - x0 + 1);
        if (dir == 0) {
            di = 80u * y0 + x0;
            si = di + 80;
            bx = 80;
        } else {
            si = 80u * (y1 - 1) + x0;
            di = si + 80;
            bx = -80;
        }
        for (r = 0; r < rows; r++) {
            for (p = 0; p < 4; p++)
                for (i = 0; i < w; i++)
                    vset(p, di + i, vb(p, si + i));
            si = (unsigned)((int)si + bx);
            di = (unsigned)((int)di + bx);
        }
        for (p = 0; p < 4; p++)
            for (i = 0; i < w; i++)
                vset(p, di + i, 0);
    } else {
        rows = (uint16_t)(y1 - y0 + 1);
        w = (uint16_t)(x1 - x0);
        for (r = 0; r < rows; r++) {
            for (p = 0; p < 4; p++) {
                if (dir == 2) {                 /* cld: from x0 + 1 to x0, left to right */
                    di = 80u * (y0 + r) + x0;
                    for (i = 0; i < w; i++)
                        vset(p, di + i, vb(p, di + i + 1));
                    vset(p, di + w, 0);
                } else {                        /* std: from x1 - 1 to x1, right to left */
                    di = 80u * (y0 + r) + x1;
                    for (i = 0; i < w; i++)
                        vset(p, di - i, vb(p, di - i - 1));
                    vset(p, di - w, 0);
                }
            }
        }
    }
    lrv_screen_mark(&ax.screen, ax.screen.access_page, (int)x0, (int)y0, (int)x1 + 1, (int)y1 + 1);
}

/* AH=10h: the text window, CX steps */
void bt_scroll(int dir, unsigned steps)
{
    steps &= 0xFFFF;
    if (dir < 0 || dir > 3)
        return;
    while (steps--)
        scroll_step(dir);
}

/* AH=11h: the same on a rectangle (the window is swapped in for the time) */
void bt_scroll_rect(const uint16_t rect[4], int dir, unsigned steps)
{
    uint16_t saved[4];
    memcpy(saved, B.win, sizeof saved);
    memcpy(B.win, rect, sizeof B.win);
    bt_scroll(dir, steps);
    memcpy(B.win, saved, sizeof saved);
}
