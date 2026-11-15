/* SPDX-License-Identifier: GPL-3.0-or-later */
/* test_vm PAK STORAGE LANG KEYS: the whole engine on a pack, input from KEYS (comma-separated
 * hex words SSCC: PC-98 scan code and character, "-" for none; "RESET" presses the reset
 * button, after which the logs below start again). The engine gets each as a press of the
 * host key that is this PC-98 key or, for a pair no key gives (the reference takes any), of a
 * key that types the character. A key is given only while the engine waits for input; when it waits and no key is left, or when the game ends, the state is
 * printed and the program exits (also, with TEST_VM_STOP_SAVE=NAME, right after the game writes
 * the record NAME: END writes its unlock file and then loops for ever):
 *   end exit|starved|save
 *   frames N
 *   mem <hex of the interpreter's 64 KB>
 *   plane <hex> (x4, page 0)
 *   dac <48 values>
 *   sound <function> <argument or name>      (in order)
 * Records written to STORAGE are files there. tests/check_vm.py compares all of it with the
 * original interpreter run by re-tools/nvovl_emu.py. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ax.h"
#include "test_hal.h"
#include "gfx/cursor.h"
#include "gfx/textlayer.h"

static const char *g_storage;
static unsigned g_keys[8192];                 /* SSCC, or 0x10000000 | x << 12 | y for a click,
                                               * 0x20000000 Return up to a click map, 0x30000000 reset */
static int g_nkeys, g_next;
static int g_in_wait, g_wait_polls, g_wait_kind;
static uint32_t g_frames;
static char g_sound[1024][80];
static int g_nsound;
static char g_pal[2048][100];
static int g_npal;

static void dump(const char *why)
{
    int p, i;
    printf("end %s\nframes %lu\nmem ", why, (unsigned long)g_frames);
    for (i = 0; i < 0x10000; i++)
        printf("%02x", ax.mem[i]);
    putchar('\n');
    for (p = 0; p < 4; p++) {
        printf("plane ");
        for (i = 0; i < AX_PLANE_BYTES; i++)
            printf("%02x", ax.screen.page[0].plane[p][i]);
        putchar('\n');
    }
    if (ax.bios.mouse_shown) {                  /* the frame as presented, with the pointer */
        struct lrv_rect dirty;
        lrv_rect_clear(&dirty);
        cursor_apply(0, &ax.screen.page[0], &dirty);
        for (p = 0; p < 4; p++) {
            printf("pointer ");
            for (i = 0; i < AX_PLANE_BYTES; i++)
                printf("%02x", ax.screen.page[0].plane[p][i]);
            putchar('\n');
        }
        cursor_restore(0, &ax.screen.page[0], &dirty);
    }
    printf("tvram ");
    for (i = 0; i < 0x4000; i++)
        printf("%02x", tl_vram()[i]);
    putchar('\n');
    printf("dac");
    for (i = 0; i < 48; i++)
        printf(" %d", ax.screen.rgb[i]);
    putchar('\n');
    for (i = 0; i < g_nsound; i++)
        printf("sound %s\n", g_sound[i]);
    for (i = 0; i < g_npal; i++)
        printf("pal %s\n", g_pal[i]);
    fflush(stdout);
}

static void tv_trace(const struct lrv_trace_event *ev)
{
    if (ev->kind == LRV_TR_QUIT) {               /* before the engine shuts down */
        dump("exit");
        exit(0);
    }
    if (ev->kind == AX_TR_SAVE && ev->name && getenv("TEST_VM_STOP_SAVE") &&
        !strcmp(ev->name, getenv("TEST_VM_STOP_SAVE"))) {
        dump("save");
        exit(0);
    }
    if (ev->kind == LRV_TR_RESET) {              /* compared from here: the game as started anew */
        g_nsound = g_npal = 0;
        g_in_wait = 0;
    }
    if (getenv("TEST_VM_DEBUG") && (ev->kind == AX_TR_MENU_SEL || ev->kind == AX_TR_SCRIPT ||
                                    (ev->kind == LRV_TR_WAIT && ev->a0 != AX_WAIT_TICKS)))
        fprintf(stderr, "ev %d %s a %d %d %d frame %lu\n", ev->kind, ev->name ? ev->name : "", ev->a0,
                ev->a1, ev->a2, (unsigned long)g_frames);
    if (ev->kind == LRV_TR_WAIT && ev->a0 != AX_WAIT_TICKS) {
        g_in_wait = ev->a1 == 0;
        g_wait_kind = ev->a0;
        g_wait_polls = 0;
    }
    if (ev->kind == AX_TR_PALETTE && ev->name && g_npal < 2048) {
        int k, n = 0;
        char *o = g_pal[g_npal++];
        if (ev->name[0] == 's')
            n += snprintf(o, 100, "13 %d", ev->a0);
        else
            n += snprintf(o, 100, "15 %d %d", ev->ints[0], ev->ints[2]);
        for (k = ev->name[0] == 's' ? 0 : 1; k < (ev->name[0] == 's' ? 16 : 2); k++)
            n += snprintf(o + n, (size_t)(100 - n), " %03X", ev->ints[k]);
    }
    if (ev->kind == AX_TR_SOUND && g_nsound < 1024) {
        if (ev->name)
            snprintf(g_sound[g_nsound++], 80, "%d %s", ev->a0, ev->name);
        else if (ev->a0 == 0x03 || ev->a0 == 0x04 || ev->a0 == 0x07 || ev->a0 == 0x11)
            snprintf(g_sound[g_nsound++], 80, "%d %d", ev->a0, ev->a1 & 0xFFFF);
        else
            snprintf(g_sound[g_nsound++], 80, "%d -", ev->a0);
    }
}

/* the press of a host key that the PC-98 reports as (scan, chr) */
static void tv_press(struct lrv_input *in, unsigned scan, unsigned chr)
{
    static const unsigned mods[] = { 0, LRV_MOD_CAPS, LRV_MOD_SHIFT, LRV_MOD_KANA,
                                     LRV_MOD_KANA | LRV_MOD_SHIFT };
    int any, key;
    unsigned m;
    for (any = 0; any <= (chr != 0); any++)
        for (m = 0; m < sizeof mods / sizeof mods[0]; m++)
            for (key = 1; key < LRV_K_COUNT; key++) {
                struct lrv_keypress k;
                struct lrv_pc98_key pk;
                k.key = (uint8_t)key;
                k.chr = 0;
                k.mods = (uint8_t)mods[m];
                if (lrv_pc98_keypress(&k, 0, &pk) && pk.chr == chr && (any || pk.scan == scan)) {
                    in->keys[in->nkeys++] = k;
                    return;
                }
            }
    fprintf(stderr, "test_vm: no key gives scan %02X with character %02X\n", scan, chr);
    exit(2);
}

static void tv_poll(struct lrv_input *in)
{
    memset(in, 0, sizeof *in);
    if (!g_in_wait)
        return;
    if (g_next < g_nkeys && (g_keys[g_next] >> 28) == 3) {
        in->events = LRV_EV_RESET;
        g_next++;
        g_wait_polls = 0;
        return;
    }
    if (g_next < g_nkeys && (g_keys[g_next] >> 28) == 2) {
        if (g_wait_kind == AX_WAIT_CLICK) {
            g_next++;                           /* R*: up to the click-map wait */
        } else {
            tv_press(in, 0x1C, 0x0D);
            g_wait_polls = 0;
            return;
        }
    }
    if (g_next < g_nkeys && (g_keys[g_next] >> 28) == 1 && g_wait_kind == AX_WAIT_CLICK) {
        in->mouse_abs = 1;
        in->mouse_x = (int)((g_keys[g_next] >> 12) & 0xFFF);
        in->mouse_y = (int)(g_keys[g_next] & 0xFFF);
        in->events = LRV_EV_MOUSE_L;
        g_next++;
        g_wait_polls = 0;
        return;
    }
    if (g_next < g_nkeys && !(g_keys[g_next] >> 28) && g_wait_kind != AX_WAIT_CLICK) {
        tv_press(in, (g_keys[g_next] >> 8) & 0xFF, g_keys[g_next] & 0xFF);
        if (getenv("TEST_VM_DEBUG"))
            fprintf(stderr, "key %04X in wait %d at frame %lu\n", g_keys[g_next], g_wait_kind,
                    (unsigned long)g_frames);
        g_next++;
        g_wait_polls = 0;
        return;
    }
    if (++g_wait_polls > 50) {
        dump("starved");
        exit(0);
    }
}

static void tv_frame(void)
{
    if (++g_frames > 2000000) {
        dump("frames");
        exit(0);
    }
}
static int tv_sopen(const char *game_id) { (void)game_id; return 0; }

static int tv_sread(const char *key, void *buf, size_t cap, size_t *len)
{
    char path[1024];
    FILE *f;
    snprintf(path, sizeof path, "%s/%s", g_storage, key);
    if (!(f = fopen(path, "rb")))
        return -1;
    *len = fread(buf, 1, cap, f);
    fclose(f);
    return 0;
}

static int tv_swrite(const char *key, const void *buf, size_t len)
{
    char path[1024];
    FILE *f;
    snprintf(path, sizeof path, "%s/%s", g_storage, key);
    if (!(f = fopen(path, "wb")))
        return -1;
    fwrite(buf, 1, len, f);
    fclose(f);
    return 0;
}

int main(int argc, char **argv)
{
    static struct ax_options options;           /* the game, not the viewer */
    struct lrv_hal hal;
    struct lrv_run_cfg cfg;
    char *k;
    if (argc != 5 || th_hal(&hal, argv[1]) != 0) {
        fprintf(stderr, "usage: test_vm PAK STORAGE LANG KEYS\n");
        return 2;
    }
    g_storage = argv[2];
    for (k = strtok(argv[4], ","); k && g_nkeys < 8192; k = strtok(0, ","))
        if (!strcmp(k, "R*")) {
            g_keys[g_nkeys++] = 0x20000000u;
        } else if (!strcmp(k, "RESET")) {
            g_keys[g_nkeys++] = 0x30000000u;
        } else if (k[0] == 'C') {
            unsigned x = 0, y = 0;
            sscanf(k, "C:%u:%u", &x, &y);
            g_keys[g_nkeys++] = 0x10000000u | (x << 12) | y;
        } else if (strcmp(k, "-")) {
            g_keys[g_nkeys++] = (unsigned)strtoul(k, 0, 16);
        }
    hal.frame_wait = tv_frame;
    hal.input_poll = tv_poll;
    hal.storage_open = tv_sopen; hal.storage_read = tv_sread; hal.storage_write = tv_swrite;
    hal.trace = tv_trace;
    memset(&cfg, 0, sizeof cfg);                /* no audio */
    cfg.lang = argv[3];
    ax_run(&options, &hal, &cfg);
    return 1;
}
