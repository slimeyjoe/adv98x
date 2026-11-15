/* SPDX-License-Identifier: GPL-3.0-or-later */
/* ax_run: start-up, the game (or the picture viewer), shutdown; ax_render_music. */
#include <stdio.h>
#include <string.h>
#include "ax.h"
#include "gfx/gpc.h"
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
    int i, n = ax.pack.count;
    for (i = 1; i <= n; i++) {
        int k = ((from + dir * i) % n + n) % n;
        if (ax.pack.entries[k].type == AX_PT_GPC)
            return k;
    }
    return -1;
}

static void viewer_show(int k)
{
    const struct lrv_pack_entry *e = &ax.pack.entries[k];
    const char *name = e->name;
    struct gpc_info g;
    struct lrv_rect w;
    uint32_t size;
    uint8_t *data = lrv_pack_load(&ax.pack, e, &size);

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
        lrv_pack_free(&ax.pack, data, size);
}

/* a file of the game by its name, with or without its extension */
static const struct lrv_pack_entry *pack_file(const char *name, const char *ext, int type)
{
    char file[LRV_PACK_NAME_LEN + 1];
    snprintf(file, sizeof file, "%s%s", name, strchr(name, '.') ? "" : ext);
    return lrv_pack_find(&ax.pack, file, type);
}

static int run_viewer(const char *first)
{
    int k = -1;
    if (first) {
        const struct lrv_pack_entry *e = pack_file(first, ".GPC", AX_PT_GPC);
        if (e)
            k = (int)(e - ax.pack.entries);
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
                lrv_sys_request_quit(&ax.sys);
        }
        if (lrv_sys_mouse_pressed(&ax.sys, LRV_EV_MOUSE_L))
            dir = 1;
        if (lrv_sys_mouse_pressed(&ax.sys, LRV_EV_MOUSE_R))
            lrv_sys_request_quit(&ax.sys);
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
    const struct lrv_pack_entry *e = lrv_pack_find(&ax.pack, "messages", LRV_PT_STRINGS);
    uint32_t size;
    uint8_t *d;
    if (!e || !(d = lrv_pack_load(&ax.pack, e, &size))) {
        lrv_log(ax.hal, LRV_LOG_WARN, "pack: no built-in messages for this language");
        return;
    }
    vm_set_messages(d, size);
    lrv_pack_free(&ax.pack, d, size);
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
 * name) is kept, as the floppy keeps it. This is how the player leaves a script that never
 * ends, as the scripts of endings do. */
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
    for (;;) {
        vm_init();
        mod_init(ax.profile.base.modules);
        install_messages();
        vm_run_game(ax.profile.start);
        if (!lrv_sys_resetting(&ax.sys))
            return 0;
        reset_machine();
    }
}

/* ---- the engine --------------------------------------------------------------------------- */

/* The pack, the game's profile and the language: --lang, else the profile's. */
static int open_pack(const struct lrv_hal *hal, const struct lrv_run_cfg *cfg)
{
    const char *tag;
    int rc;
    memset(&ax, 0, sizeof ax);
    ax.hal = hal;
    rc = lrv_pack_open(&ax.pack, hal, LRV_PACK_MAIN);
    if (rc != LRV_OK)
        return rc;
    rc = profile_load();
    tag = cfg->lang ? cfg->lang : ax.profile.base.lang;
    if (rc == LRV_OK && !lrv_pack_lang_id(&ax.pack, tag)) {
        lrv_log(hal, LRV_LOG_ERROR, "pack: no language \"%s\"", tag);
        rc = LRV_ERR_NOTFOUND;
    }
    if (rc != LRV_OK) {
        lrv_pack_close(&ax.pack);
        return rc;
    }
    lrv_pack_set_lang(&ax.pack, lrv_pack_lang_id(&ax.pack, tag));
    return LRV_OK;
}

/* Offline: a song by its name in the pack, with or without ".USO", through the sound path
 * the game uses, the INT F4h services included. */
int ax_render_music(void *ctx, const struct lrv_hal *hal, const struct lrv_run_cfg *cfg,
                    const char *name, double seconds, uint32_t *rate,
                    void (*sink)(void *sctx, const int16_t *pcm, int frames), void *sctx)
{
    static int16_t buf[1024];
    const struct lrv_pack_entry *song;
    double left;
    int rc;
    (void)ctx;

    rc = open_pack(hal, cfg);
    if (rc != LRV_OK)
        return rc;
    lrv_sys_init(&ax.sys, hal, 0, 0);       /* the services report to it */
    song = pack_file(name, ".USO", AX_PT_USO);
    rc = song ? LRV_OK : LRV_ERR_NOTFOUND;
    if (song) {
        snd_open(cfg, 0);
        *rate = lrv_mixer_rate(&ax.mixer);
        snd_stop();
        snd_load_play(song->name);
        snd_play();
        for (left = seconds * *rate; left > 0; left -= 1024) {
            int n = left < 1024 ? (int)left : 1024;
            lrv_mixer_render(&ax.mixer, buf, n);
            sink(sctx, buf, n);
        }
        snd_close();
        if (!*rate)
            rc = LRV_ERR;
    }
    lrv_pack_close(&ax.pack);
    return rc;
}

int ax_run(void *ctx, const struct lrv_hal *hal, const struct lrv_run_cfg *cfg)
{
    const struct ax_options *opt = ctx;
    struct lrv_video_cfg video;
    int rc;

    if (open_pack(hal, cfg) != LRV_OK)
        lrv_fatal(hal, "cannot use the game pack (make pack; docs/game-data.md)");

    memset(&video, 0, sizeof video);
    video.mode = lrv_pc98_video_mode;
    video.title = ax.profile.base.title;
    video.fullscreen = cfg->fullscreen;
    video.scale_mode = cfg->scale_mode;
    video.host_mode = cfg->host_mode;
    if (hal->video_open(&video) != LRV_OK)
        lrv_fatal(hal, "cannot open the display");
    /* VRAM pages 0 and 1; the pointer and, above it, the text layer exist only in the
     * presented picture */
    if (lrv_screen_init(&ax.screen, hal, &video.mode, 2, 0, LRV_MEM_ANY) != LRV_OK)
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
    if (lrv_font_load(&ax.font16, &ax.pack, "font16", 16, LRV_GLYPH_ROWS) != LRV_OK ||
        lrv_font_load(&ax.font8, &ax.pack, "font8", 8, LRV_GLYPH_ROWS) != LRV_OK)
        lrv_fatal(hal, "the pack lacks the fonts font16 and font8");
    cursor_init();
    snd_open(cfg, 1);
    if (hal->storage_open(ax.profile.base.id) != LRV_OK)
        lrv_log(hal, LRV_LOG_WARN, "no storage: the game cannot save");

    rc = opt->view ? run_viewer(opt->view_picture) : run_game();

    lrv_sys_trace(&ax.sys, LRV_TR_QUIT, 0, 0, rc, 0, 0, 0);
    snd_close();
    hal->video_close();
    cursor_shutdown();
    lrv_font_free(&ax.font8);
    lrv_font_free(&ax.font16);
    lrv_screen_free(&ax.screen);
    lrv_pack_close(&ax.pack);
    return rc;
}
