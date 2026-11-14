/* SPDX-License-Identifier: GPL-3.0-or-later */
/* System layer: the single blocking point of the engine (frames), the derived 20 ms tick,
 * presentation, the input model (BIOS key buffer, key-down bitmap, mouse) and diagnostics.
 * Everything here is a thin layer over the HAL. */
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include "ax_internal.h"
#include "gfx/gfx.h"
#include "gfx/cursor.h"
#include "gfx/textlayer.h"

struct ax_state ax;

/* ---- diagnostics ------------------------------------------------------------------------- */

void sys_log(int level, const char *fmt, ...)
{
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    ax.hal->log(level, buf);
}

void sys_fatal(const char *fmt, ...)
{
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    ax.hal->fatal(buf);
}

void *sys_alloc(size_t n)
{
    void *p = ax.hal->mem_alloc(n ? n : 1, AX_MEM_ANY);
    if (!p)
        sys_fatal("out of memory (%lu bytes)", (unsigned long)n);
    memset(p, 0, n);
    return p;
}

void sys_free(void *p, size_t n)
{
    if (p)
        ax.hal->mem_free(p, n ? n : 1);
}

static void trace_base(struct ax_trace_event *ev, int kind)
{
    memset(ev, 0, sizeof *ev);
    ev->kind = kind;
    ev->tick = ax.frame;
    ev->pos = ax.script_pos;
    ev->script = ax.script_name;
}

void sys_trace(int kind, const char *name, const uint8_t *text, int a0, int a1, int a2, int a3)
{
    struct ax_trace_event ev;
    if (!ax.hal->trace)
        return;
    trace_base(&ev, kind);
    ev.name = name;
    ev.text = text;
    ev.a0 = a0; ev.a1 = a1; ev.a2 = a2; ev.a3 = a3;
    ax.hal->trace(&ev);
}

void sys_trace_ints(int kind, const char *name, const int *ints, int n, int a0)
{
    struct ax_trace_event ev;
    if (!ax.hal->trace)
        return;
    trace_base(&ev, kind);
    ev.name = name;
    ev.ints = ints;
    ev.nints = n;
    ev.a0 = a0;
    ax.hal->trace(&ev);
}

void sys_trace_items(int kind, const uint8_t *const *items, int n, int a0)
{
    struct ax_trace_event ev;
    if (!ax.hal->trace)
        return;
    trace_base(&ev, kind);
    ev.items = items;
    ev.n = n;
    ev.a0 = a0;
    ax.hal->trace(&ev);
}

/* ---- input ----------------------------------------------------------------------------- */

static void kbuf_push(const struct ax_key *k)
{
    if (ax.kcount >= AX_KEYQ)
        return;                         /* full: dropped, as the BIOS buffer drops it */
    ax.kbuf[(ax.khead + ax.kcount) % AX_KEYQ] = *k;
    ax.kcount++;
}

static void clamp_pointer(void)
{
    if (ax.mouse_x < 0) ax.mouse_x = 0;
    if (ax.mouse_y < 0) ax.mouse_y = 0;
    if (ax.mouse_x > AX_SCREEN_W - 1) ax.mouse_x = AX_SCREEN_W - 1;
    if (ax.mouse_y > AX_SCREEN_H - 1) ax.mouse_y = AX_SCREEN_H - 1;
}

static void poll_input(void)
{
    struct ax_input in;
    int i;
    memset(&in, 0, sizeof in);
    ax.hal->input_poll(&in);
    for (i = 0; i < in.nkeys && i < AX_KEYQ; i++)
        kbuf_push(&in.keys[i]);
    ax.mouse_edges |= in.events & (AX_EV_MOUSE_L | AX_EV_MOUSE_R);
    if (in.events & AX_EV_QUIT)
        ax.quit_requested = 1;
    if (in.events & AX_EV_EMERGENCY)
        ax.emergency_quit = 1;
    /* the pointer: an absolute host position wins when it moved, else relative motion */
    if (in.mouse_abs) {
        if (!ax.in.mouse_abs || in.mouse_x != ax.in.mouse_x || in.mouse_y != ax.in.mouse_y) {
            ax.mouse_x = in.mouse_x;
            ax.mouse_y = in.mouse_y;
        }
    } else {
        ax.mouse_x += in.mouse_dx;
        ax.mouse_y += in.mouse_dy;
    }
    clamp_pointer();
    ax.in = in;
    /* a click shorter than a poll still holds its button down for this one poll */
    if (in.events & AX_EV_MOUSE_L)
        ax.in.buttons |= AX_BTN_L;
    if (in.events & AX_EV_MOUSE_R)
        ax.in.buttons |= AX_BTN_R;
}

int sys_quitting(void)
{
    return ax.quit_requested || ax.emergency_quit;
}

int sys_key_sense(void)
{
    return ax.kcount > 0;
}

unsigned sys_key_read(void)
{
    struct ax_key k;
    if (!ax.kcount)
        return 0xFFFFu;
    k = ax.kbuf[ax.khead];
    ax.khead = (ax.khead + 1) % AX_KEYQ;
    ax.kcount--;
    return ((unsigned)k.scan << 8) | k.chr;
}

void sys_key_flush(void)
{
    ax.hal->input_flush();
    ax.khead = ax.kcount = 0;
    ax.mouse_edges = 0;
}

int sys_key_down(int scan)
{
    return ax_key_down(&ax.in, scan);
}

unsigned sys_mouse_buttons(void)
{
    return ax.in.buttons;
}

int sys_mouse_pressed(unsigned ev)
{
    if (ax.mouse_edges & ev) {
        ax.mouse_edges &= ~ev;
        return 1;
    }
    return 0;
}

void sys_mouse_set_pos(int x, int y)
{
    ax.mouse_x = x;
    ax.mouse_y = y;
    clamp_pointer();
    if (ax.hal->mouse_warp)
        ax.hal->mouse_warp(ax.mouse_x, ax.mouse_y);
}

/* ---- frames, ticks and presentation ---------------------------------------------------- */

void sys_init(void)
{
    ax.khead = ax.kcount = 0;
    ax.mouse_x = AX_SCREEN_W / 2;
    ax.mouse_y = AX_SCREEN_H / 2;
    ax.frame = ax.tick = ax.tick_acc = 0;
    ax.nframe_hooks = ax.ntick_hooks = 0;
    ax.script_name = 0;
    ax.script_pos = ~0u;
}

void sys_add_frame_hook(void (*fn)(void))
{
    if (ax.nframe_hooks < AX_HOOKS_MAX)
        ax.frame_hooks[ax.nframe_hooks++] = fn;
}

void sys_add_tick_hook(void (*fn)(void))
{
    if (ax.ntick_hooks < AX_HOOKS_MAX)
        ax.tick_hooks[ax.ntick_hooks++] = fn;
}

static void present(void)
{
    struct ax_rect *d = &ax.dirty[ax.display_page];
    gfx_update_dac();
    cursor_apply(ax.display_page);
    tl_apply(ax.display_page);              /* the text layer is above the graphics */
    ax.hal->video_present(&ax.page[ax.display_page], d, ax.page_switched, 0, ax.dac,
                          ax.graphics_on);
    ax_rect_clear(d);
    /* after the clear: the restored bytes are dirty for the next present */
    tl_restore(ax.display_page);
    cursor_restore(ax.display_page);
    ax.page_switched = 0;
}

void sys_present_now(void)
{
    present();
}

static void advance_time(void)
{
    int i;
    ax.frame++;
    ax.tick_acc += AX_TICK_NUM;
    while (ax.tick_acc >= AX_TICK_DEN) {
        ax.tick_acc -= AX_TICK_DEN;
        ax.tick++;
        for (i = 0; i < ax.ntick_hooks; i++)
            ax.tick_hooks[i]();
    }
}

void sys_frame_wait(void)
{
    int i;
    if (sys_quitting()) {
        /* leaving: the loop that called us runs out at CPU speed; nothing more is shown */
        advance_time();
        return;
    }
    for (i = 0; i < ax.nframe_hooks; i++)
        ax.frame_hooks[i]();
    present();
    ax.hal->frame_wait();
    advance_time();
    poll_input();
}
