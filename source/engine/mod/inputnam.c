/* SPDX-License-Identifier: GPL-3.0-or-later */
/* INPUTNAM.TCM: name entry (docs/re/plugins.md §5, §7.4), after the plug-in's code
 * (tcmtool.py listing; addresses below are offsets in the file). The field is a row of 16x16
 * cells drawn with the AdvBIOS text services; keys are read from the BIOS buffer, type-ahead
 * dropped; the result is written to NAME.DEF as 256 bytes: the name (Shift-JIS) then FFh. */
#include <string.h>
#include "ax.h"
#include "bios/bios.h"
#include "mod/mod.h"

/* tab_kana 02BC: half-width kana A0h..DFh (keyboard in kana mode) -> hiragana; A0h..A5h
 * ignored, ﾞ ﾟ -> the dakuten / handakuten codes */
static const uint16_t tab_kana[64] = {
    0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x82F0, 0x829F,
    0x82A1, 0x82A3, 0x82A5, 0x82A7, 0x82E1, 0x82E3, 0x82E5, 0x82C1,
    0x815B, 0x82A0, 0x82A2, 0x82A4, 0x82A6, 0x82A8, 0x82A9, 0x82AB,
    0x82AD, 0x82AF, 0x82B1, 0x82B3, 0x82B5, 0x82B7, 0x82B9, 0x82BB,
    0x82BD, 0x82BF, 0x82C2, 0x82C4, 0x82C6, 0x82C8, 0x82C9, 0x82CA,
    0x82CB, 0x82CC, 0x82CD, 0x82D0, 0x82D3, 0x82D6, 0x82D9, 0x82DC,
    0x82DD, 0x82DE, 0x82DF, 0x82E0, 0x82E2, 0x82E4, 0x82E6, 0x82E7,
    0x82E8, 0x82E9, 0x82EA, 0x82EB, 0x82ED, 0x82F1, 0x814A, 0x814B,
};
/* tab_dakuten 033C (か..と, then running on into tab_handakuten は..ほ) */
static const uint16_t tab_voiced[] = {
    0x82A9, 0x82AB, 0x82AD, 0x82AF, 0x82B1, 0x82B3, 0x82B5, 0x82B7, 0x82B9, 0x82BB,
    0x82BD, 0x82BF, 0x82C2, 0x82C4, 0x82C6,
    0x82CD, 0x82D0, 0x82D3, 0x82D6, 0x82D9, 0
};
#define TAB_SEMI (tab_voiced + 15)

static struct {
    unsigned maxlen, x, y;
    uint8_t colour, back;
    uint16_t def[8];                    /* default name, Shift-JIS words, 0-terminated */
    uint16_t typed[8];
    unsigned count;
} st;

/* draw_cell 0138: fill cell number `count` with the background, draw `dx` there */
static void draw_cell(unsigned dx)
{
    uint16_t r[4];
    r[0] = (uint16_t)(st.count * 2 + st.x);
    r[2] = (uint16_t)(r[0] + 1);
    r[1] = (uint16_t)st.y;
    r[3] = (uint16_t)(st.y + 15);
    bt_fill_rect(r, st.back);
    bt_set_cursor(r[0], r[1]);
    bt_set_colour(st.colour);
    bt_draw_char(dx);
}

static int in_list(const uint16_t *list, unsigned w)
{
    for (; *list; list++)
        if (*list == w)
            return 1;
    return 0;
}

/* get_key 0242: a key only if the buffer was empty when sensed; 0 = nothing usable, 8 erase,
 * 0Dh Return, else a Shift-JIS code; -1 when the player quits */
static long get_key(void)
{
    unsigned k, scan, chr;
    for (;;) {
        if (bios_key_sense()) {
            bios_key_read();
            continue;
        }
        lrv_sys_trace(&ax.sys, LRV_TR_WAIT, 0, 0, AX_WAIT_NAME, 0, 0, 0);
        while (!bios_key_sense()) {
            if (lrv_sys_quitting(&ax.sys)) {
                lrv_sys_trace(&ax.sys, LRV_TR_WAIT, 0, 0, AX_WAIT_NAME, 1, AX_LEAVE_QUIT, 0);
                return -1;
            }
            lrv_sys_frame_wait(&ax.sys);
        }
        k = bios_key_read();
        lrv_sys_trace(&ax.sys, LRV_TR_WAIT, 0, 0, AX_WAIT_NAME, 1, AX_LEAVE_KEY, 0);
        break;
    }
    scan = k >> 8;
    chr = k & 0xFF;
    if (scan == 0x0E || scan == 0x39 || scan == 0x3B)
        return 8;
    if (scan == 0x1C)
        return 0x0D;
    if (chr >= 0xE0)
        return 0;
    if (chr >= 0xA0)
        return tab_kana[chr - 0xA0];
    if ((chr >= '0' && chr <= '9') || (chr >= 'A' && chr <= 'Z') || (chr >= 'a' && chr <= 'z')) {
        unsigned lo = chr + 0x1F;
        return 0x8200 | (lo >= 0x7F ? lo + 1 : lo);
    }
    return 0;
}

static void add_char(unsigned dx)
{
    if (st.count >= st.maxlen)
        return;
    draw_cell(dx);
    st.typed[st.count++] = (uint16_t)dx;
    draw_cell(0x81A5);                  /* draw_cursor 01C7 */
    st.typed[st.count] = 0;
}

/* edit_loop 0176: returns on Return (0) or when the player quits (-1) */
static int edit_loop(void)
{
    for (;;) {
        long k = get_key();
        unsigned prev;
        if (k < 0)
            return -1;
        if (k == 0)
            continue;
        if (k == 0x0D)
            return 0;
        if (k == 8) {
            if (!st.count)
                continue;
            draw_cell(0x8140);
            st.count--;
            draw_cell(0x81A5);
            st.typed[st.count] = 0;
            continue;
        }
        if (k == 0x814A || k == 0x814B) {
            if (!st.count)
                continue;
            prev = st.typed[st.count - 1];
            if (!in_list(k == 0x814A ? tab_voiced : TAB_SEMI, prev))
                continue;
            prev += k == 0x814A ? 1u : 2u;
            st.typed[st.count - 1] = (uint16_t)prev;
            st.count--;
            draw_cell(0x8140);
            add_char(prev);
            continue;
        }
        add_char((unsigned)k);
    }
}

/* write_name 00FC: the name (typed, or the default), FFh to 256 bytes, written until it is */
static void write_name(void)
{
    uint8_t out[256 + 32];
    const uint16_t *src = st.count ? st.typed : st.def;
    size_t n = 0;
    for (; *src && n < 32; src++) {
        out[n++] = (uint8_t)(*src >> 8);
        out[n++] = (uint8_t)*src;
    }
    memset(out + n, 0xFF, 256);
    bios_select_drive(0, 0);
    if (bios_file_write("A:\\NAME.DEF", out, 256) != 256)
        lrv_log(ax.hal, LRV_LOG_ERROR, "INPUTNAM: cannot write NAME.DEF");
}

/* parse_args 002C: needs 5 arguments; maxlen 0 or > 6 -> 6; x clamped so the field fits; y <= 383 */
static unsigned long inputnam_exec(const uint16_t *a, int n)
{
    unsigned saved;
    if (n < 5)
        return 0xFF00;
    st.maxlen = (a[2] == 0 || a[2] > 6) ? 6 : a[2];
    st.x = a[3];
    if (st.maxlen * 2 + st.x > 0x4F)
        st.x = 0x50 - st.maxlen * 2;
    st.y = a[4] > 0x17F ? 0x17F : a[4];
    memset(st.def, 0, sizeof st.def);
    if (n >= 6) {
        const uint8_t *s = mod_string(a[5]);
        unsigned i;
        for (i = 0; s[i] != '"' && i < 14; i += 2)
            st.def[i / 2] = (uint16_t)(s[i] << 8 | (s[i + 1] == '"' ? 0 : s[i + 1]));
    }
    st.colour = (uint8_t)(n >= 7 ? a[6] & 15 : 15);
    st.back = (uint8_t)(n >= 8 ? a[7] & 15 : 0);
    /* input_name 00C2 */
    saved = (unsigned)bt_colour();
    st.count = 0;
    st.typed[0] = 0;
    draw_cell(0x81A5);
    for (;;) {
        if (edit_loop() < 0)
            return 0xFF00;
        if (st.count || st.def[0])
            break;
    }
    draw_cell(0x8140);
    write_name();
    bt_set_colour((int)saved);
    return 0xFF00;
}

const struct ax_module mod_inputnam = { "INPUTNAM", 0, inputnam_exec };
