/* SPDX-License-Identifier: GPL-3.0-or-later */
/* be68k PAK SPEC TICKS LANG RATE: the whole engine on a HAL of its own, for a run on a
 * big-endian machine (tests/be68k.sh builds it for m68k Linux and runs it under qemu-m68k, and
 * builds it natively as the reference).
 *
 * The HAL is the headless backend's (lrvne's backends/null) as far as the engine can tell: the
 * pack read from a file, frames that never wait, input from an autoplay spec (lrvne's
 * backends/common/autoplay.c, the same code), sound pushed at the rate of the video mode's frame
 * period through the light FM core, records kept in memory. At each snap: tick of the spec it
 * prints
 *
 *   snap t<tick> <frame hash> <audio frames> <audio hash>
 *
 * (the frame hash is lrv_frame_hash32 of the frame last presented, as the headless backend
 * prints it; the audio hash is FNV-1a over the samples so far as little-endian bytes, as a WAV
 * file holds them), and after TICKS frames every record the game wrote,
 *
 *   record <key> <length> <hash>
 *
 * and "end <tick>". Everything the engine reads (pack, pictures, scripts, songs, fonts, the
 * profile, its own memory image) passes through the code paths of a real run. */
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ax.h"
#include "autoplay.h"
#include "be68k.h"

#ifndef BE68K_FREESTANDING
#include <fcntl.h>
#include <unistd.h>

int os_open_read(const char *path) { return open(path, O_RDONLY); }
long os_read(int fd, void *buf, size_t n) { return (long)read(fd, buf, n); }
long os_write(int fd, const void *buf, size_t n) { return (long)write(fd, buf, n); }
long os_seek(int fd, long off, int whence) { return (long)lseek(fd, off, whence); }
void os_close(int fd) { close(fd); }
#endif

static void say(int fd, const char *fmt, ...) __attribute__((format(printf, 2, 3)));

static void say(int fd, const char *fmt, ...)
{
    char buf[256];
    va_list ap;
    int n;
    va_start(ap, fmt);
    n = vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    if (n > (int)sizeof buf - 1)
        n = (int)sizeof buf - 1;
    if (n > 0)
        os_write(fd, buf, (size_t)n);
}

static uint32_t fnv(uint32_t h, const uint8_t *p, size_t n)
{
    while (n--)
        h = (h ^ *p++) * 16777619u;
    return h;
}

/* ---- the pack ------------------------------------------------------------------------------ */

static int g_pak = -1;
static uint32_t g_pak_size;

static void *p_open(int which, uint32_t *size)
{
    if (which != LRV_PACK_MAIN || g_pak < 0)
        return 0;
    *size = g_pak_size;
    return &g_pak;
}

static size_t p_read(void *h, uint32_t off, void *dst, size_t n)
{
    size_t got = 0;
    (void)h;
    if (os_seek(g_pak, (long)off, 0) != (long)off)
        return 0;
    while (got < n) {
        long r = os_read(g_pak, (uint8_t *)dst + got, n - got);
        if (r <= 0)
            break;
        got += (size_t)r;
    }
    return got;
}

static void p_close(void *h)
{
    (void)h;
}

/* ---- records ------------------------------------------------------------------------------- */

#define NREC 32
static struct { char key[32]; uint8_t *data; size_t len; } g_rec[NREC];

static int s_open(const char *id)
{
    (void)id;
    return LRV_OK;
}

static int find_rec(const char *key)
{
    int i;
    for (i = 0; i < NREC && g_rec[i].key[0]; i++)
        if (!strcmp(g_rec[i].key, key))
            return i;
    return i < NREC ? -1 - i : -1 - NREC;
}

static int s_read(const char *key, void *buf, size_t cap, size_t *len)
{
    int i = find_rec(key);
    if (i < 0)
        return LRV_ERR_NOTFOUND;
    *len = g_rec[i].len < cap ? g_rec[i].len : cap;
    memcpy(buf, g_rec[i].data, *len);
    return LRV_OK;
}

static int s_write(const char *key, const void *buf, size_t len)
{
    int i = find_rec(key);
    if (i < 0) {
        i = -1 - i;
        if (i >= NREC || strlen(key) >= sizeof g_rec[i].key)
            return LRV_ERR_IO;
        strcpy(g_rec[i].key, key);
    }
    free(g_rec[i].data);
    g_rec[i].data = malloc(len ? len : 1);
    if (!g_rec[i].data)
        return LRV_ERR_NOMEM;
    memcpy(g_rec[i].data, buf, len);
    g_rec[i].len = len;
    return LRV_OK;
}

/* ---- video, time, input, sound --------------------------------------------------------------- */

static struct lrv_autoplay g_ap;
static uint32_t g_tick, g_max_ticks;
static struct lrv_video_mode g_mode;
static uint32_t g_hash, g_hash_tick;   /* the frame presented before tick g_hash_tick */
static int g_rate;
static uint64_t g_audio_acc;
static long g_audio_owed;
static uint32_t g_audio_frames, g_audio_hash = 2166136261u;

static int v_open(const struct lrv_video_cfg *cfg)
{
    if (cfg->mode.format != LRV_FMT_PLANAR4)
        return LRV_ERR_RANGE;
    g_mode = cfg->mode;
    return LRV_OK;
}

static void v_close(void)
{
}

/* Hashed here, when the next tick takes a snapshot: the overlays (pointer, text layer) are on
 * the page only during the present. lrv_screen presents every frame. */
static void v_present(const struct lrv_frame *frame)
{
    if (lrv_autoplay_snap_due(&g_ap, g_tick + 1)) {
        g_hash = lrv_frame_hash32(frame);
        g_hash_tick = g_tick + 1;
    }
}

static long frames_per_tick(int rate, uint64_t *acc)
{
    long n;
    *acc += (uint64_t)rate * (g_mode.frame_ns ? g_mode.frame_ns : 16666667u);
    n = (long)(*acc / 1000000000u);
    *acc %= 1000000000u;
    return n;
}

static void finish(void)
{
    int i;
    for (i = 0; i < NREC && g_rec[i].key[0]; i++)
        say(1, "record %s %lu %08lx\n", g_rec[i].key, (unsigned long)g_rec[i].len,
            (unsigned long)fnv(2166136261u, g_rec[i].data, g_rec[i].len));
    say(1, "end %lu\n", (unsigned long)g_tick);
}

static void t_frame_wait(void)
{
    g_tick++;
    if (g_rate)
        g_audio_owed += frames_per_tick(g_rate, &g_audio_acc);
    if (g_tick > g_max_ticks) {
        finish();
        exit(3);
    }
    if (lrv_autoplay_snap_due(&g_ap, g_tick)) {
        if (g_hash_tick == g_tick)
            say(1, "snap t%lu %08lx %lu %08lx\n", (unsigned long)g_tick, (unsigned long)g_hash,
                (unsigned long)g_audio_frames, (unsigned long)g_audio_hash);
        else
            say(1, "snap t%lu nothing-presented\n", (unsigned long)g_tick);
    }
}

static void i_poll(struct lrv_input *in)
{
    memset(in, 0, sizeof *in);
    lrv_autoplay_poll(&g_ap, g_tick, in);
}

static void i_flush(void)
{
    lrv_autoplay_flush(&g_ap, g_tick);
}

static int a_open(int rate, const struct lrv_audio_source *src)
{
    (void)src;
    g_rate = rate > 0 ? rate : 0;
    g_audio_owed = 0;
    return g_rate;
}

static void a_close(void)
{
    g_rate = 0;
}

static int a_space(void)
{
    return g_audio_owed > 0 ? (int)g_audio_owed : 0;
}

static void a_push(const int16_t *pcm, int frames)
{
    int i;
    for (i = 0; i < frames; i++) {
        uint8_t le[2];
        le[0] = (uint8_t)((uint16_t)pcm[i] & 0xFF);
        le[1] = (uint8_t)((uint16_t)pcm[i] >> 8);
        g_audio_hash = fnv(g_audio_hash, le, 2);
    }
    g_audio_frames += (uint32_t)frames;
    g_audio_owed -= frames;
}

/* ---- the rest of the HAL ------------------------------------------------------------------- */

static void *m_alloc(size_t n, unsigned flags)
{
    (void)flags;
    return malloc(n);
}

static void m_free(void *p, size_t n)
{
    (void)n;
    free(p);
}

static void l_log(int level, const char *msg)
{
    if (level >= LRV_LOG_WARN)
        say(2, "log: %s\n", msg);
}

static void l_fatal(const char *msg)
{
    say(2, "fatal: %s\n", msg);
    exit(1);
}

static char *read_text(const char *path)
{
    int fd = os_open_read(path);
    long n;
    char *s;
    if (fd < 0)
        return 0;
    n = os_seek(fd, 0, 2);
    s = n >= 0 ? malloc((size_t)n + 1) : 0;
    if (s && (os_seek(fd, 0, 0) != 0 || os_read(fd, s, (size_t)n) != n)) {
        free(s);
        s = 0;
    }
    if (s)
        s[n] = 0;
    os_close(fd);
    return s;
}

int main(int argc, char **argv)
{
    static struct ax_options options;
    struct lrv_run_cfg cfg;
    struct lrv_hal hal;
    char err[96], *spec;
    long size;

    if (argc != 6) {
        say(2, "usage: be68k PAK SPEC TICKS LANG RATE\n");
        return 2;
    }
    g_pak = os_open_read(argv[1]);
    size = g_pak >= 0 ? os_seek(g_pak, 0, 2) : -1;
    spec = read_text(argv[2]);
    if (size <= 0 || !spec) {
        say(2, "be68k: cannot read %s\n", size <= 0 ? argv[1] : argv[2]);
        return 2;
    }
    g_pak_size = (uint32_t)size;
    if (lrv_autoplay_parse(&g_ap, spec, err, sizeof err) != LRV_OK) {
        say(2, "be68k: %s\n", err);
        return 2;
    }
    g_max_ticks = (uint32_t)strtoul(argv[3], 0, 10);

    memset(&hal, 0, sizeof hal);
    hal.video_open = v_open;
    hal.video_close = v_close;
    hal.video_present = v_present;
    hal.frame_wait = t_frame_wait;
    hal.input_poll = i_poll;
    hal.input_flush = i_flush;
    hal.audio_open = a_open;
    hal.audio_close = a_close;
    hal.audio_space = a_space;
    hal.audio_push = a_push;
    hal.storage_open = s_open;
    hal.storage_read = s_read;
    hal.storage_write = s_write;
    hal.pack_open = p_open;
    hal.pack_read = p_read;
    hal.pack_close = p_close;
    hal.mem_alloc = m_alloc;
    hal.mem_free = m_free;
    hal.log = l_log;
    hal.fatal = l_fatal;

    memset(&cfg, 0, sizeof cfg);
    cfg.lang = argv[4];
    cfg.audio_rate = (int)strtoul(argv[5], 0, 10);
    cfg.opn_core = 1;                   /* the light core: the one the Amiga family has */
    ax_run(&options, &hal, &cfg);
    finish();
    return 0;
}
