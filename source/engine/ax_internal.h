/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Engine-wide state shared by the engine modules (not for backends).
 *
 * The original is two programs with global state (NV.OVL, the interpreter, and NV.OV1,
 * AdvBIOS); the engine keeps that shape in one structure, `ax`, so the modules can be read next
 * to the research documents (docs/re/interpreter.md, advbios.md). Comments name the original
 * addresses where a field models one. */
#ifndef AX_INTERNAL_H
#define AX_INTERNAL_H

#include <stddef.h>
#include <stdint.h>
#include "ax.h"
#include "ax_hal.h"
#include "gfx/planes.h"
#include "pack/pack.h"
#include "bios/bios.h"

/* Time bases (docs/engine-plan.md design point 5): the frame is the PC-98 VSYNC, 56.42 Hz;
 * AdvBIOS's tick is 20 ms. One frame adds AX_TICK_NUM to an accumulator, every AX_TICK_DEN
 * in it is one tick: 50 / 56.42 ticks per frame, exactly. */
#define AX_FRAME_HZ   56.42
#define AX_TICK_NUM   5000u
#define AX_TICK_DEN   5642u

#define AX_HOOKS_MAX  8

/* ---- the game profile (game/profile.c, from the pack's "profile" entry) ---------------- */
struct ax_profile {
    char title[96];                     /* window title, UTF-8 */
    char start[16];                     /* start script (NV.INI's target), e.g. "RUN" */
    char modules[96];                   /* comma-separated plug-in modules the game enables */
    int default_lang;                   /* XPAK_L_* */
};

/* ---- the state ------------------------------------------------------------------------ */

struct ax_state {
    const struct ax_hal *hal;
    struct ax_config cfg;
    struct xpak pak;
    struct ax_profile profile;
    int lang;

    /* graphics (advbios.md §5.1, §5.7) */
    uint8_t *planemem;                  /* 2 pages x 4 planes */
    struct ax_planes page[2];           /* VRAM pages 0 and 1 */
    struct ax_rect dirty[2];            /* per page, pending upload */
    int access_page;                    /* port A6h */
    int display_page;                   /* port A4h */
    int page_switched;                  /* display page changed since last present */
    int graphics_on;
    uint16_t palette[16];               /* palette buffer 04E9:0022, 0GRB words */
    int brightness;                     /* 04E9:0042, 0..15 */
    uint8_t dac[48];                    /* what the hardware outputs: 16 x {R,G,B} 0..15 */
    int dac_changed;
    uint16_t mailbox[16];               /* INT F3h AH=FFh buffer 0290:045C */

    /* AdvBIOS service state (bios/bios.h) */
    struct ax_bios bios;
    int beeper_on;

    /* input */
    struct ax_input in;                 /* last poll: levels (keymap, buttons) */
    struct ax_key kbuf[AX_KEYQ];        /* the BIOS key buffer */
    int khead, kcount;
    unsigned mouse_edges;               /* AX_EV_MOUSE_* not yet consumed */
    int mouse_x, mouse_y;               /* the pointer position the engine works with */
    int quit_requested, emergency_quit;

    /* time */
    uint32_t frame;                     /* frames since start */
    uint32_t tick;                      /* 20 ms ticks since start (AdvBIOS DS:00F8 counts these) */
    uint32_t tick_acc;
    void (*frame_hooks[AX_HOOKS_MAX])(void);
    void (*tick_hooks[AX_HOOKS_MAX])(void);
    int nframe_hooks, ntick_hooks;

    /* trace context */
    const char *script_name;            /* current script, for trace events */
    uint32_t script_pos;                /* offset of the current statement, ~0u = none */
};

extern struct ax_state ax;

/* sys.c: the single blocking point, presentation, input and diagnostics */
void sys_init(void);
void sys_frame_wait(void);                       /* one frame: hooks, present, wait, input */
int  sys_quitting(void);                         /* the player asked to quit (window close) */
void sys_present_now(void);
void sys_add_frame_hook(void (*fn)(void));       /* run once per frame, before presenting */
void sys_add_tick_hook(void (*fn)(void));        /* run once per 20 ms tick */
/* the BIOS key buffer (advbios.md §6.1): sense (non-zero when a key waits), read (removes
 * it; scan code in the low byte's place of AH, character in AL: (scan << 8) | chr), flush */
int  sys_key_sense(void);
unsigned sys_key_read(void);
void sys_key_flush(void);                        /* also drops pending button edges */
int  sys_key_down(int scan);                     /* key-down bitmap */
/* mouse: position (640x400), buttons held, and consuming a press edge */
unsigned sys_mouse_buttons(void);
int  sys_mouse_pressed(unsigned ev);             /* AX_EV_MOUSE_L / _R since last consumed */
void sys_mouse_set_pos(int x, int y);            /* INT 33h AX=4: also warps the host pointer */

void sys_log(int level, const char *fmt, ...);
void sys_fatal(const char *fmt, ...);
void *sys_alloc(size_t n);                       /* zeroed; fatal when out of memory */
void sys_free(void *p, size_t n);
/* test automation events (ax_hal.h ax_trace_kind); no-ops without hal->trace */
void sys_trace(int kind, const char *name, const uint8_t *text, int a0, int a1, int a2, int a3);
void sys_trace_ints(int kind, const char *name, const int *ints, int n, int a0);
void sys_trace_items(int kind, const uint8_t *const *items, int n, int a0);
#define AX_TRACING() (ax.hal->trace != 0)

/* game/profile.c */
int profile_load(struct ax_profile *p);

#endif
