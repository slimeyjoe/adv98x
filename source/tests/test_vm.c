/* SPDX-License-Identifier: GPL-3.0-or-later */
/* test_vm PAK STORAGE LANG KEYS: the whole engine on a pack, input from KEYS (comma-separated
 * hex words SSCC: PC-98 scan code and character, "-" for none). A key is given only while the
 * engine waits for input; when it waits and no key is left, or when the game ends, the state is
 * printed and the program exits:
 *   end exit|starved
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
#include "ax_internal.h"
#include "hal_file.h"
#include "gfx/cursor.h"

static const char *g_storage;
static unsigned g_keys[256];                  /* SSCC, or 0x10000000 | x << 12 | y for a click */
static int g_nkeys, g_next;
static int g_in_wait, g_wait_polls, g_wait_kind;
static uint32_t g_frames;
static char g_sound[64][80];
static int g_nsound;
static char g_pal[512][100];
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
            printf("%02x", ax.page[0].p[p][i]);
        putchar('\n');
    }
    if (ax.bios.mouse_shown) {                  /* the frame as presented, with the pointer */
        cursor_apply(0);
        for (p = 0; p < 4; p++) {
            printf("pointer ");
            for (i = 0; i < AX_PLANE_BYTES; i++)
                printf("%02x", ax.page[0].p[p][i]);
            putchar('\n');
        }
        cursor_restore(0);
    }
    printf("dac");
    for (i = 0; i < 48; i++)
        printf(" %d", ax.dac[i]);
    putchar('\n');
    for (i = 0; i < g_nsound; i++)
        printf("sound %s\n", g_sound[i]);
    for (i = 0; i < g_npal; i++)
        printf("pal %s\n", g_pal[i]);
    fflush(stdout);
}

static void tv_trace(const struct ax_trace_event *ev)
{
    if (ev->kind == AX_TR_QUIT) {               /* before the engine shuts down */
        dump("exit");
        exit(0);
    }
    if (getenv("TEST_VM_DEBUG") && (ev->kind == AX_TR_MENU_SEL || ev->kind == AX_TR_SCRIPT ||
                                    (ev->kind == AX_TR_WAIT && ev->a0 != AX_WAIT_TICKS)))
        fprintf(stderr, "ev %d %s a %d %d %d frame %lu\n", ev->kind, ev->name ? ev->name : "", ev->a0,
                ev->a1, ev->a2, (unsigned long)g_frames);
    if (ev->kind == AX_TR_WAIT && ev->a0 != AX_WAIT_TICKS) {
        g_in_wait = ev->a1 == 0;
        g_wait_kind = ev->a0;
        g_wait_polls = 0;
    }
    if (ev->kind == AX_TR_PALETTE && ev->name && g_npal < 512) {
        int k, n = 0;
        char *o = g_pal[g_npal++];
        if (ev->name[0] == 's')
            n += snprintf(o, 100, "13 %d", ev->a0);
        else
            n += snprintf(o, 100, "15 %d %d", ev->ints[0], ev->ints[2]);
        for (k = ev->name[0] == 's' ? 0 : 1; k < (ev->name[0] == 's' ? 16 : 2); k++)
            n += snprintf(o + n, (size_t)(100 - n), " %03X", ev->ints[k]);
    }
    if (ev->kind == AX_TR_SOUND && g_nsound < 64) {
        if (ev->name)
            snprintf(g_sound[g_nsound++], 80, "%d %s", ev->a0, ev->name);
        else if (ev->a0 == 0x03 || ev->a0 == 0x04 || ev->a0 == 0x07 || ev->a0 == 0x11)
            snprintf(g_sound[g_nsound++], 80, "%d %d", ev->a0, ev->a1 & 0xFFFF);
        else
            snprintf(g_sound[g_nsound++], 80, "%d -", ev->a0);
    }
}

static void tv_poll(struct ax_input *in)
{
    memset(in, 0, sizeof *in);
    if (!g_in_wait)
        return;
    if (g_next < g_nkeys && (g_keys[g_next] >> 28) == 2) {
        if (g_wait_kind == AX_WAIT_CLICK) {
            g_next++;                           /* R*: up to the click-map wait */
        } else {
            in->keys[0].scan = 0x1C;
            in->keys[0].chr = 0x0D;
            in->nkeys = 1;
            g_wait_polls = 0;
            return;
        }
    }
    if (g_next < g_nkeys && (g_keys[g_next] >> 28) == 1 && g_wait_kind == AX_WAIT_CLICK) {
        in->mouse_abs = 1;
        in->mouse_x = (int)((g_keys[g_next] >> 12) & 0xFFF);
        in->mouse_y = (int)(g_keys[g_next] & 0xFFF);
        in->events = AX_EV_MOUSE_L;
        g_next++;
        g_wait_polls = 0;
        return;
    }
    if (g_next < g_nkeys && !(g_keys[g_next] >> 28) && g_wait_kind != AX_WAIT_CLICK) {
        in->keys[0].scan = (uint8_t)(g_keys[g_next] >> 8);
        in->keys[0].chr = (uint8_t)g_keys[g_next];
        in->nkeys = 1;
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

static void tv_flush(void) {}
static void tv_frame(void)
{
    if (++g_frames > 2000000) {
        dump("frames");
        exit(0);
    }
}
static uint32_t tv_ticks(void) { return g_frames; }
static int tv_vopen(const struct ax_video_cfg *c) { (void)c; return 0; }
static void tv_vclose(void) {}
static void tv_present(const struct ax_planes *pg, const struct ax_rect *d, int sw, int sl,
                       const uint8_t rgb[48], int on)
{
    (void)pg; (void)d; (void)sw; (void)sl; (void)rgb; (void)on;
}
static int tv_aopen(int r) { (void)r; return 0; }
static void tv_aclose(void) {}

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
    struct ax_hal hal;
    struct ax_config cfg;
    char *k;
    if (argc != 5 || tf_hal(&hal, argv[1]) != 0) {
        fprintf(stderr, "usage: test_vm PAK STORAGE LANG KEYS\n");
        return 2;
    }
    g_storage = argv[2];
    for (k = strtok(argv[4], ","); k && g_nkeys < 256; k = strtok(0, ","))
        if (!strcmp(k, "R*")) {
            g_keys[g_nkeys++] = 0x20000000u;
        } else if (k[0] == 'C') {
            unsigned x = 0, y = 0;
            sscanf(k, "C:%u:%u", &x, &y);
            g_keys[g_nkeys++] = 0x10000000u | (x << 12) | y;
        } else if (strcmp(k, "-")) {
            g_keys[g_nkeys++] = (unsigned)strtoul(k, 0, 16);
        }
    hal.video_open = tv_vopen; hal.video_close = tv_vclose; hal.video_present = tv_present;
    hal.frame_wait = tv_frame; hal.ticks = tv_ticks;
    hal.input_poll = tv_poll; hal.input_flush = tv_flush;
    hal.audio_open = tv_aopen; hal.audio_close = tv_aclose;
    hal.storage_read = tv_sread; hal.storage_write = tv_swrite;
    hal.trace = tv_trace;
    memset(&cfg, 0, sizeof cfg);
    cfg.language = xpak_lang_id(argv[3]);
    ax_run(&hal, &cfg);
    return 1;
}
