/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Adv98X: the engine's state, shared by its modules.
 *
 * The original is two programs with global state (NV.OVL, the interpreter, and NV.OV1,
 * AdvBIOS); the engine keeps that shape in one structure, `ax`, so the modules can be read next
 * to the research documents (docs/re/interpreter.md, advbios.md). Comments name the original
 * addresses where a field models one.
 *
 * Everything below the interpreter and AdvBIOS's services is lrvne (source/lrvne, its headers
 * in lrvne/): the frame and the input queue (lrv_sys), the pages, the DAC and the presentation
 * (lrv_screen), the path from the music driver to samples (lrv_opnq, lrv_mixer), the pack, the
 * fonts. Their instances are members of `ax`; the engine calls lrvne directly. */
#ifndef AX_H
#define AX_H

#include <stddef.h>
#include <stdint.h>
#include "lrvne/app.h"
#include "lrvne/core.h"
#include "lrvne/gfx.h"
#include "lrvne/hal.h"
#include "lrvne/mixer.h"
#include "lrvne/opnq.h"
#include "lrvne/pc98.h"
#include "lrvne/sys.h"
#include "pack/pack.h"
#include "bios/bios.h"
#include "snd/usd.h"

/* Time bases (docs/engine-plan.md design point 5): the frame is the PC-98 VSYNC, 56.42 Hz;
 * AdvBIOS's tick is 20 ms. One frame adds AX_TICK_NUM to an accumulator, every AX_TICK_DEN
 * in it is one tick: 50 / 56.42 ticks per frame, exactly. */
#define AX_TICK_NUM   5000u
#define AX_TICK_DEN   5642u

/* bytes of one plane of a page (640 x 400: 32 000), the visible part of the 64 KB the
 * original's 16-bit VRAM offsets address */
#define AX_PLANE_BYTES (LRV_PC98_STRIDE * LRV_PC98_H)

/* ---- trace events (test automation; lrvne/trace.h has the kinds every engine shares) ---- */

/* Every event carries the script offset of the statement being executed, so a driver can
 * match it with the bytecode. The names of these kinds are in main.c, for the backends. */
enum ax_trace_kind {
    AX_TR_SCRIPT = LRV_TR_ENGINE,   /* name = script loaded; a0 = 0 main, 1 sub-script buffer */
    AX_TR_OP,           /* a0 = opcode, ints = operands, name = string operand */
    AX_TR_TEXT,         /* text = a run of drawn text (language encoding) */
    AX_TR_MENU,         /* items/n = item texts, a0 = kind (0 menu, 1 menu2 verbs, 2 nouns) */
    AX_TR_MENU_SEL,     /* a0 = selection (-1 cancel), a1 = kind */
    AX_TR_PICTURE,      /* name = picture, a0 = x, a1 = y, a2 = mode, a3 = palette flags */
    AX_TR_PALETTE,      /* a0 = brightness */
    AX_TR_SOUND,        /* name = song or NULL, a0 = function, a1 = argument */
    AX_TR_SAVE,         /* name = record, a0 = slot */
    AX_TR_LOAD,         /* name = record, a0 = slot, a1 = loaded; a0 = -1: a click map (name) */
    AX_TR_MODULE,       /* name = plug-in module, a0 = command, ints = arguments */
    AX_TR_FLAG,         /* a0 = flag or variable address, a1 = value */
    AX_TR_KIND_END
};

/* a0 of LRV_TR_WAIT */
enum ax_wait_kind {
    AX_WAIT_TICKS = 0,  /* timed delay (INT F1h AH=09h and the text delays) */
    AX_WAIT_KEY,        /* wait for input (INT F1h AH=07h) */
    AX_WAIT_MENU,       /* a menu waits for a choice */
    AX_WAIT_CLICK,      /* a click map waits (INT F1h AH=0Dh) */
    AX_WAIT_NAME,       /* name entry waits for a key */
    AX_WAIT_PROMPT      /* a yes/no prompt (quit) */
};
/* reasons for leaving a wait (a2 of the leave event) */
enum ax_wait_leave { AX_LEAVE_KEY = 0, AX_LEAVE_CLICK, AX_LEAVE_SKIP, AX_LEAVE_TIMEOUT,
                     AX_LEAVE_QUIT };

/* ---- the game profile (game/profile.c, from the pack's "profile" entry) ---------------- */
struct ax_profile {
    char title[96];                     /* window title, UTF-8 */
    char start[16];                     /* start script (NV.INI's target), e.g. "RUN" */
    char modules[96];                   /* comma-separated plug-in modules the game enables */
    int default_lang;                   /* XPAK_L_* */
};

/* ---- the state ------------------------------------------------------------------------ */

struct ax_state {
    const struct lrv_hal *hal;
    struct lrv_sys sys;                 /* frames, the input queue, quit and reset, traces */
    struct xpak pak;
    struct ax_profile profile;
    int lang;

    /* graphics (advbios.md §5.1, §5.7): VRAM pages 0 and 1, the access page (port A6h), the
     * displayed one (port A4h) and the DAC are the screen's */
    struct lrv_screen screen;
    uint16_t palette[16];               /* palette buffer 04E9:0022, 0GRB words */
    int brightness;                     /* 04E9:0042, 0..15 */
    uint16_t mailbox[16];               /* INT F3h AH=FFh buffer 0290:045C */

    /* the interpreter's segment (vm/mes.h): 64 KB + a guard */
    uint8_t *mem;

    /* AdvBIOS service state (bios/bios.h) */
    struct ax_bios bios;
    int beeper_on;
    uint32_t tick;                      /* 20 ms ticks since start (AdvBIOS DS:00F8 counts these) */
    uint32_t tick_acc;

    /* sound (snd/snd.h): the driver, the chip behind its write queue, the output */
    struct usd usd;
    struct lrv_opnq opnq;
    struct lrv_mixer mixer;
};

extern struct ax_state ax;

/* What the command line chose, beside what every engine has (lrv_run_cfg). */
struct ax_options {
    /* picture viewer (a tool, not the game): 1 = browse the pack's pictures instead of
     * running the game; view_picture names the first one (NULL = the first in the pack) */
    int view;
    const char *view_picture;
};

/* game/run.c: the functions of struct lrv_app (main.c); ctx is the struct ax_options */
int ax_run(void *ctx, const struct lrv_hal *hal, const struct lrv_run_cfg *cfg);
int ax_render_music(void *ctx, const struct lrv_hal *hal, const struct lrv_run_cfg *cfg,
                    const char *name, double seconds, uint32_t *rate,
                    void (*sink)(void *sctx, const int16_t *pcm, int frames), void *sctx);

/* game/profile.c */
int profile_load(struct ax_profile *p);

#endif
