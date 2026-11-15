/* SPDX-License-Identifier: GPL-3.0-or-later */
/* ax_run: start-up, the game (or the picture viewer), shutdown; ax_render_music. */
#include <stdio.h>
#include <string.h>
#include "ax.h"
#include "gfx/gpc.h"
#include "text/font.h"
#include "gfx/cursor.h"
#include "gfx/textlayer.h"
#include "snd/snd.h"
#include "vm/mes.h"
#include "mod/mod.h"

struct ax_state ax;

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
    struct lrv_rect w;
    uint32_t size;
    uint8_t *data = xpak_load(&ax.pak, e, &size);
    char name[XPAK_NAME_LEN + 1];

    memcpy(name, e->name, XPAK_NAME_LEN);
    name[XPAK_NAME_LEN] = 0;
    lrv_screen_clear_access(&ax.screen);
    if (!data || gpc_parse(data, size, &g) != 0) {
        lrv_log(ax.hal, LRV_LOG_WARN, "viewer: %s is not a GPC picture", name);
    } else {
        gpc_draw(data, size, lrv_screen_access(&ax.screen), -1, 0, 0, &w);
        lrv_screen_mark_surface(&ax.screen, lrv_screen_access(&ax.screen), &w);
        if (g.has_palette)
            bg_load_palette(g.palette);
        bg_program(15);
        lrv_sys_trace(&ax.sys, AX_TR_PICTURE, name, 0, g.x, g.y, 0, g.has_palette ? 3 : 0);
        lrv_log(ax.hal, LRV_LOG_INFO, "%s: %dx%d at (%d, %d), interleave %d", name, g.w, g.h, g.x, g.y,
                g.interleave);
    }
    if (data)
        xpak_free(&ax.pak, data, size);
}

static int run_viewer(const char *first)
{
    int k = -1;
    if (first) {
        const struct xpak_entry *e = xpak_find(&ax.pak, first, XPAK_T_GPC);
        if (e)
            k = (int)(e - ax.pak.entries);
        else
            lrv_log(ax.hal, LRV_LOG_WARN, "viewer: no picture %s", first);
    }
    if (k < 0)
        k = viewer_next(-1, 1);
    if (k < 0) {
        lrv_log(ax.hal, LRV_LOG_ERROR, "viewer: the pack has no pictures");
        return 1;
    }
    viewer_show(k);
    lrv_sys_trace(&ax.sys, LRV_TR_WAIT, 0, 0, AX_WAIT_KEY, 0, 0, 0);
    for (;;) {
        struct lrv_keypress key;
        int dir = 0;
        lrv_sys_frame_wait(&ax.sys);
        if (lrv_sys_resetting(&ax.sys)) {          /* the reset button: back to the first picture */
            lrv_sys_reset_done(&ax.sys);
            k = viewer_next(-1, 1);
            viewer_show(k);
            continue;
        }
        if (lrv_sys_quitting(&ax.sys))
            break;
        while (lrv_sys_key_read(&ax.sys, &key)) {
            if (key.key == LRV_K_RIGHT || key.key == LRV_K_DOWN || key.key == LRV_K_RETURN ||
                key.key == LRV_K_KP_ENTER || key.key == LRV_K_SPACE)
                dir = 1;
            else if (key.key == LRV_K_LEFT || key.key == LRV_K_UP)
                dir = -1;
            else if (key.key == LRV_K_ESC)
                ax.sys.quit_requested = 1;
        }
        if (lrv_sys_mouse_pressed(&ax.sys, LRV_EV_MOUSE_L))
            dir = 1;
        if (lrv_sys_mouse_pressed(&ax.sys, LRV_EV_MOUSE_R))
            ax.sys.quit_requested = 1;
        if (dir && !lrv_sys_quitting(&ax.sys)) {
            lrv_sys_trace(&ax.sys, LRV_TR_WAIT, 0, 0, AX_WAIT_KEY, 1, AX_LEAVE_KEY, 0);
            k = viewer_next(k, dir);
            viewer_show(k);
            lrv_sys_trace(&ax.sys, LRV_TR_WAIT, 0, 0, AX_WAIT_KEY, 0, 0, 0);
        }
    }
    lrv_sys_trace(&ax.sys, LRV_TR_WAIT, 0, 0, AX_WAIT_KEY, 1, AX_LEAVE_QUIT, 0);
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
        lrv_log(ax.hal, LRV_LOG_WARN, "pack: no built-in messages for this language");
        return;
    }
    vm_set_messages(d, size);
    xpak_free(&ax.pak, d, size);
}

/* The machine in its start-up state: both pages clear, page 0 shown and accessed, the display
 * on, no text layer, AdvBIOS as it initialises itself (the default palette at full
 * brightness). */
static void machine_init(void)
{
    lrv_screen_reset(&ax.screen);
    tl_init();
    cursor_reset();
    bios_init();
}

/* The reset button (LRV_EV_RESET; the original has none, the player would reboot the PC-98 and
 * start the game again): the game unwinds as for a quit, then the machine is put back into its
 * start-up state - screen, palette, text layer, sound, AdvBIOS, the interpreter's memory, the
 * plug-ins - and the game starts again from its start script. The storage (saves, the player's
 * name) is kept, as the floppy keeps it. This is how the player leaves an ending, which loops
 * for ever in the original (END.MES). */
static void reset_machine(void)
{
    snd_reset();
    machine_init();
    lrv_sys_reset_done(&ax.sys);
    lrv_log(ax.hal, LRV_LOG_INFO, "reset");
    lrv_sys_trace(&ax.sys, LRV_TR_RESET, 0, 0, 0, 0, 0, 0);
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
        if (!lrv_sys_resetting(&ax.sys))
            return 0;
        reset_machine();
    }
}

/* ---- the engine --------------------------------------------------------------------------- */

static int open_pack(const struct lrv_hal *hal, const struct lrv_run_cfg *cfg)
{
    memset(&ax, 0, sizeof ax);
    ax.hal = hal;
    if (xpak_open(&ax.pak, hal) != 0)
        return LRV_ERR_NOTFOUND;
    if (profile_load(&ax.profile) != 0)
        lrv_log(hal, LRV_LOG_WARN, "pack: no game profile, using defaults");
    ax.lang = cfg->lang && xpak_lang_id(cfg->lang) ? xpak_lang_id(cfg->lang)
                                                    : ax.profile.default_lang;
    ax.pak.lang = (uint8_t)ax.lang;
    return LRV_OK;
}

/* Offline: a song by its name in the pack ("NV01"; an extension is ignored) through the sound
 * path the game uses, the INT F4h services included. */
int ax_render_music(void *ctx, const struct lrv_hal *hal, const struct lrv_run_cfg *cfg,
                    const char *name, double seconds, uint32_t *rate,
                    void (*sink)(void *sctx, const int16_t *pcm, int frames), void *sctx)
{
    static int16_t buf[1024];
    char song[XPAK_NAME_LEN + 1], file[XPAK_NAME_LEN + 8];
    double left;
    int rc = LRV_ERR_NOTFOUND;
    (void)ctx;

    if (open_pack(hal, cfg) != LRV_OK)
        return rc;
    snprintf(song, sizeof song, "%.*s", (int)strcspn(name, "."), name);
    snprintf(file, sizeof file, "%s.USO", song);
    lrv_sys_init(&ax.sys, hal, 0, 0);       /* the services report to it */
    if (xpak_find(&ax.pak, song, XPAK_T_USO)) {
        snd_open(cfg, 0);
        *rate = lrv_mixer_rate(&ax.mixer);
        snd_stop();
        snd_load_play(file);
        snd_play();
        for (left = seconds * *rate; left > 0; left -= 1024) {
            int n = left < 1024 ? (int)left : 1024;
            lrv_mixer_render(&ax.mixer, buf, n);
            sink(sctx, buf, n);
        }
        snd_close();
        rc = *rate ? LRV_OK : LRV_ERR;
    }
    xpak_close(&ax.pak);
    return rc;
}

int ax_run(void *ctx, const struct lrv_hal *hal, const struct lrv_run_cfg *cfg)
{
    const struct ax_options *opt = ctx;
    struct lrv_video_cfg video;
    int rc;

    if (open_pack(hal, cfg) != LRV_OK)
        lrv_fatal(hal, "cannot open the game pack (make pack; docs/game-data.md)");

    memset(&video, 0, sizeof video);
    video.mode = lrv_pc98_video_mode;
    video.title = ax.profile.title;
    video.fullscreen = cfg->fullscreen;
    video.scale_mode = cfg->scale_mode;
    video.host_mode = cfg->host_mode;
    if (hal->video_open(&video) != LRV_OK)
        lrv_fatal(hal, "cannot open the display");
    /* VRAM pages 0 and 1; the pointer and, above it, the text layer exist only in the
     * presented picture */
    if (lrv_screen_init(&ax.screen, hal, &video.mode, 2, 0, LRV_MEM_CHIP) != LRV_OK)
        lrv_fatal(hal, "out of memory (screen)");
    lrv_screen_add_overlay(&ax.screen, cursor_apply, cursor_restore, 0);
    lrv_screen_add_overlay(&ax.screen, tl_apply, tl_restore, 0);

    /* the frame: the mouse driver's interrupts, the audio, the present, the wait, AdvBIOS's
     * tick, the input */
    lrv_sys_init(&ax.sys, hal, video.mode.w, video.mode.h);
    lrv_sys_set_present(&ax.sys, lrv_screen_present_hook, &ax.screen);
    lrv_sys_add_hook(&ax.sys, LRV_HOOK_PUMP, mouse_frame, 0);
    lrv_sys_add_hook(&ax.sys, LRV_HOOK_PUMP, lrv_mixer_pump, &ax.mixer);
    lrv_sys_add_hook(&ax.sys, LRV_HOOK_TICK, bios_frame_tick, 0);

    machine_init();
    font_init();
    cursor_init();
    snd_open(cfg, 1);
    if (hal->storage_open("nova") != LRV_OK)
        lrv_log(hal, LRV_LOG_WARN, "no storage: the game cannot save");

    rc = opt->view ? run_viewer(opt->view_picture) : run_game();

    lrv_sys_trace(&ax.sys, LRV_TR_QUIT, 0, 0, rc, 0, 0, 0);
    snd_close();
    hal->video_close();
    cursor_shutdown();
    font_shutdown();
    lrv_screen_free(&ax.screen);
    xpak_close(&ax.pak);
    return rc;
}
