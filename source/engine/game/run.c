/* SPDX-License-Identifier: GPL-3.0-or-later */
/* ax_run: start-up, the game (or the picture viewer), shutdown. */
#include <stdio.h>
#include <string.h>
#include "ax_internal.h"
#include "gfx/gfx.h"
#include "gfx/gpc.h"
#include "text/font.h"
#include "gfx/cursor.h"
#include "gfx/textlayer.h"
#include "snd/snd.h"
#include "vm/mes.h"
#include "mod/mod.h"

/* ---- picture viewer (--view): a tool for looking at the pack's pictures as AdvBIOS draws
 * them: the page cleared to colour 0, the picture opaque at its own position, its palette at
 * full brightness. ←/→ (or ↑/↓, Return, Space, left click) step, Esc / right click quits. ---- */

static int viewer_next(int from, int dir)
{
    int i, n = ax.pak.count;
    for (i = 1; i <= n; i++) {
        int k = ((from + dir * i) % n + n) % n;
        if (ax.pak.entries[k].type == XPAK_T_GPC)
            return k;
    }
    return -1;
}

static void viewer_show(int k)
{
    const struct xpak_entry *e = &ax.pak.entries[k];
    struct gpc_info g;
    struct ax_rect w;
    uint32_t size;
    uint8_t *data = xpak_load(&ax.pak, e, &size);
    char name[XPAK_NAME_LEN + 1];

    memcpy(name, e->name, XPAK_NAME_LEN);
    name[XPAK_NAME_LEN] = 0;
    gfx_clear_page();
    if (!data || gpc_parse(data, size, &g) != 0) {
        sys_log(AX_LOG_WARN, "viewer: %s is not a GPC picture", name);
    } else {
        gpc_draw(data, size, gfx_access(), -1, 0, 0, &w);
        gfx_mark_planes(gfx_access(), &w);
        if (g.has_palette)
            gfx_set_palette(g.palette);
        gfx_set_brightness(15);
        sys_trace(AX_TR_PICTURE, name, 0, g.x, g.y, 0, g.has_palette ? 3 : 0);
        sys_log(AX_LOG_INFO, "%s: %dx%d at (%d, %d), interleave %d", name, g.w, g.h, g.x, g.y,
                g.interleave);
    }
    if (data)
        xpak_free(&ax.pak, data, size);
}

static int run_viewer(void)
{
    int k = -1;
    if (ax.cfg.view_picture) {
        const struct xpak_entry *e = xpak_find(&ax.pak, ax.cfg.view_picture, XPAK_T_GPC);
        if (e)
            k = (int)(e - ax.pak.entries);
        else
            sys_log(AX_LOG_WARN, "viewer: no picture %s", ax.cfg.view_picture);
    }
    if (k < 0)
        k = viewer_next(-1, 1);
    if (k < 0) {
        sys_log(AX_LOG_ERROR, "viewer: the pack has no pictures");
        return 1;
    }
    viewer_show(k);
    sys_trace(AX_TR_WAIT, 0, 0, AX_WAIT_KEY, 0, 0, 0);
    for (;;) {
        int dir = 0;
        sys_frame_wait();
        if (sys_resetting()) {          /* the reset button: back to the first picture */
            sys_reset_input();
            k = viewer_next(-1, 1);
            viewer_show(k);
            continue;
        }
        if (sys_quitting())
            break;
        while (sys_key_sense()) {
            unsigned key = sys_key_read() >> 8;
            if (key == AX_K_RIGHT || key == AX_K_DOWN || key == AX_K_RETURN || key == AX_K_SPACE)
                dir = 1;
            else if (key == AX_K_LEFT || key == AX_K_UP)
                dir = -1;
            else if (key == AX_K_ESC)
                ax.quit_requested = 1;
        }
        if (sys_mouse_pressed(AX_EV_MOUSE_L))
            dir = 1;
        if (sys_mouse_pressed(AX_EV_MOUSE_R))
            ax.quit_requested = 1;
        if (dir && !sys_quitting()) {
            sys_trace(AX_TR_WAIT, 0, 0, AX_WAIT_KEY, 1, AX_LEAVE_KEY, 0);
            k = viewer_next(k, dir);
            viewer_show(k);
            sys_trace(AX_TR_WAIT, 0, 0, AX_WAIT_KEY, 0, 0, 0);
        }
    }
    sys_trace(AX_TR_WAIT, 0, 0, AX_WAIT_KEY, 1, AX_LEAVE_QUIT, 0);
    return 0;
}

/* ---- the game ------------------------------------------------------------------------------ */

/* the built-in messages of the interpreter (save failed, nothing saved, load failed) as script
 * fragments, per language: the pack's "messages" entry (tools/mkpack.py) */
static void install_messages(void)
{
    const struct xpak_entry *e = xpak_find(&ax.pak, "messages", XPAK_T_STRINGS);
    uint32_t size;
    uint8_t *d;
    if (!e || !(d = xpak_load(&ax.pak, e, &size))) {
        sys_log(AX_LOG_WARN, "pack: no built-in messages for this language");
        return;
    }
    vm_set_messages(d, size);
    xpak_free(&ax.pak, d, size);
}

/* The reset button (AX_EV_RESET; the original has none, the player would reboot the PC-98 and
 * start the game again): the game unwinds as for a quit, then the machine is put back into its
 * start-up state - screen, palette, text layer, sound, AdvBIOS, the interpreter's memory, the
 * plug-ins - and the game starts again from its start script. The storage (saves, the player's
 * name) is kept, as the floppy keeps it. This is how the player leaves an ending, which loops
 * for ever in the original (END.MES). */
static void reset_machine(void)
{
    snd_reset();
    gfx_reset();
    tl_init();
    cursor_reset();
    bios_init();
    sys_reset_input();
    sys_log(AX_LOG_INFO, "reset");
    sys_trace(AX_TR_RESET, 0, 0, 0, 0, 0, 0);
}

static int run_game(void)
{
    char start[40];
    snprintf(start, sizeof start, "\\MES\\%s.MES", ax.profile.start);
    for (;;) {
        vm_init();
        mod_init(ax.profile.modules);
        install_messages();
        vm_run_game(start);
        if (!sys_resetting())
            return 0;
        reset_machine();
    }
}

/* ---- the engine --------------------------------------------------------------------------- */

int ax_render_music(const struct ax_hal *hal, const struct ax_config *cfg, const char *name,
                    double seconds, uint32_t *rate,
                    void (*sink)(void *ctx, const int16_t *pcm, int frames), void *ctx)
{
    static int16_t buf[1024];
    double left;
    memset(&ax, 0, sizeof ax);
    ax.hal = hal;
    ax.cfg = *cfg;
    sys_init();
    if (xpak_open(&ax.pak, hal) != 0)
        return 1;
    bios_init();
    snd_init();
    *rate = snd_rate();
    if (!*rate) {
        xpak_close(&ax.pak);
        return 1;
    }
    snd_stop();
    snd_load_play(name);
    snd_play();
    for (left = seconds * *rate; left > 0; left -= 1024) {
        int n = left < 1024 ? (int)left : 1024;
        ax_audio_render(buf, n);
        sink(ctx, buf, n);
    }
    snd_shutdown();
    xpak_close(&ax.pak);
    return 0;
}

int ax_run(const struct ax_hal *hal, const struct ax_config *cfg)
{
    int rc;
    struct ax_video_cfg vc;

    memset(&ax, 0, sizeof ax);
    ax.hal = hal;
    ax.cfg = *cfg;
    sys_init();
    if (xpak_open(&ax.pak, hal) != 0) {
        hal->fatal("cannot open the game pack (make pack; docs/game-data.md)");
        return 1;
    }
    if (profile_load(&ax.profile) != 0)
        sys_log(AX_LOG_WARN, "pack: no game profile, using defaults");
    ax.lang = cfg->language ? cfg->language : ax.profile.default_lang;
    ax.pak.lang = (uint8_t)ax.lang;

    gfx_init();
    bios_init();
    font_init();
    cursor_init();
    tl_init();
    snd_init();
    vc = cfg->video;
    if (!vc.title)
        vc.title = ax.profile.title;
    if (hal->video_open(&vc) != 0) {
        hal->fatal("cannot open the display");
        return 1;
    }

    if (cfg->view) {
        rc = run_viewer();
    } else {
        rc = run_game();
    }

    sys_trace(AX_TR_QUIT, 0, 0, rc, 0, 0, 0);
    snd_shutdown();
    hal->video_close();
    cursor_shutdown();
    font_shutdown();
    gfx_shutdown();
    xpak_close(&ax.pak);
    return rc;
}
