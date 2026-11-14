/* SPDX-License-Identifier: GPL-3.0-or-later */
/* test_usd < SCENARIO: drives the music driver (engine/snd/usd.c) through a scenario read from
 * stdin, one command per line, and prints every OPN register write as "clock reg val"
 * (decimal, clock in master clocks). tests/check_usd.py builds the scenarios (those of
 * re-tools/usdmodel.py --check) and compares the output with usdmodel.Model and with the
 * original driver's recordings.
 *
 *   init [CLK PHASE_A PHASE_B TEMPO]  a new driver: usd_init / usd_init_at; prints "init"
 *   load FILE | bank FILE             AH=00h / AH=10h with the file's bytes (rest of the line)
 *   loadhex HEX | bankhex HEX         the same with the bytes given in hex
 *   play | volume N | se I | enable M AH=01h / 07h / 11h / 06h; print "= RESULT"
 *   fadeout | fadein | stop           AH=03h / 04h / 02h
 *   fade P S F | stopowner N          AH=05h / 84h
 *   seconds S                         run to clock + round(S * USD_CLOCK) (Python's round)
 *   clocks N | until CLK              run to clock + N / to CLK
 *   aticks N                          step until N more timer-A ticks have been handled
 *   clock                             prints "@ clock aticks active"
 * Empty lines and lines starting with # are ignored. */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "snd/usd.h"

static struct usd drv;
static unsigned long long nwrites;

static void on_write(void *ctx, uint64_t clock, int reg, int val)
{
    (void)ctx;
    printf("%llu %d %d\n", (unsigned long long)clock, reg, val);
    nwrites++;
}

/* one line of any length; 0 at the end of the input */
static char *read_line(FILE *f, char **buf, size_t *cap)
{
    size_t len = 0;
    if (!*buf) {
        *cap = 4096;
        *buf = malloc(*cap);
        if (!*buf)
            return 0;
    }
    for (;;) {
        if (!fgets(*buf + len, (int)(*cap - len), f))
            return len ? *buf : 0;
        len += strlen(*buf + len);
        if (len && (*buf)[len - 1] == '\n') {
            (*buf)[--len] = 0;
            if (len && (*buf)[len - 1] == '\r')
                (*buf)[--len] = 0;
            return *buf;
        }
        if (len + 1 >= *cap) {
            char *n = realloc(*buf, *cap * 2);
            if (!n)
                return 0;
            *buf = n;
            *cap *= 2;
        }
    }
}

static uint8_t *read_file(const char *path, uint32_t *size)
{
    FILE *f = fopen(path, "rb");
    uint8_t *d;
    long n;
    if (!f)
        return 0;
    fseek(f, 0, SEEK_END);
    n = ftell(f);
    fseek(f, 0, SEEK_SET);
    d = malloc(n > 0 ? (size_t)n : 1);
    if (d && n > 0 && fread(d, 1, (size_t)n, f) != (size_t)n) {
        free(d);
        d = 0;
    }
    fclose(f);
    *size = (uint32_t)n;
    return d;
}

static int hexval(int c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    if (c >= 'A' && c <= 'F')
        return c - 'A' + 10;
    return -1;
}

static uint8_t *parse_hex(const char *s, uint32_t *size)
{
    size_t n = strlen(s) / 2, i;
    uint8_t *d = malloc(n ? n : 1);
    if (!d)
        return 0;
    for (i = 0; i < n; i++) {
        int hi = hexval(s[2 * i]), lo = hexval(s[2 * i + 1]);
        if (hi < 0 || lo < 0) {
            free(d);
            return 0;
        }
        d[i] = (uint8_t)(hi << 4 | lo);
    }
    *size = (uint32_t)n;
    return d;
}

/* int(round(s * CLOCK)) of Python: the product in double, rounded half to even */
static uint64_t seconds_to_clocks(double s)
{
    double x = s * (double)USD_CLOCK, fl = floor(x), frac = x - fl;
    uint64_t n = (uint64_t)fl;
    if (frac > 0.5 || (frac == 0.5 && (n & 1)))
        n++;
    return n;
}

static int fail(int line, const char *cmd, const char *why)
{
    fprintf(stderr, "test_usd: line %d: %s: %s\n", line, cmd, why);
    return 2;
}

int main(void)
{
    static char outbuf[1 << 16];
    char *buf = 0, *line;
    size_t cap = 0;
    int lineno = 0;
    setvbuf(stdout, outbuf, _IOFBF, sizeof outbuf);
    usd_init(&drv, on_write, 0);
    while ((line = read_line(stdin, &buf, &cap)) != 0) {
        char cmd[16], *arg;
        int n;
        long a, b, c;
        unsigned long long u, v, w, t;
        lineno++;
        while (*line == ' ' || *line == '\t')
            line++;
        if (!*line || *line == '#')
            continue;
        if (sscanf(line, "%15s%n", cmd, &n) != 1)
            return fail(lineno, line, "syntax");
        arg = line + n;
        while (*arg == ' ' || *arg == '\t')
            arg++;
        if (!strcmp(cmd, "init")) {
            if (sscanf(arg, "%llu %llu %llu %llu", &u, &v, &w, &t) == 4)
                usd_init_at(&drv, on_write, 0, u, (uint32_t)v, (uint32_t)w, (unsigned)t);
            else if (!*arg)
                usd_init(&drv, on_write, 0);
            else
                return fail(lineno, cmd, "init [CLK PHASE_A PHASE_B TEMPO]");
            printf("init\n");
        } else if (!strcmp(cmd, "load") || !strcmp(cmd, "bank") || !strcmp(cmd, "loadhex")
                   || !strcmp(cmd, "bankhex")) {
            uint32_t size = 0;
            uint8_t *d = cmd[4] == 'h' ? parse_hex(arg, &size) : read_file(arg, &size);
            if (!d)
                return fail(lineno, cmd, cmd[4] == 'h' ? "bad hex" : "cannot read the file");
            if (cmd[0] == 'l')
                usd_load(&drv, d, size);
            else
                usd_load_bank(&drv, d, size);
            free(d);
        } else if (!strcmp(cmd, "play")) {
            printf("= %d\n", usd_play(&drv));
        } else if (!strcmp(cmd, "volume") && sscanf(arg, "%ld", &a) == 1) {
            printf("= %d\n", usd_volume(&drv, (int)a));
        } else if (!strcmp(cmd, "se") && sscanf(arg, "%ld", &a) == 1) {
            printf("= %d\n", usd_play_se(&drv, (int)a));
        } else if (!strcmp(cmd, "enable") && sscanf(arg, "%ld", &a) == 1) {
            printf("= %d\n", usd_set_enable(&drv, (int)a));
        } else if (!strcmp(cmd, "fadeout")) {
            usd_fade_out(&drv);
        } else if (!strcmp(cmd, "fadein")) {
            usd_fade_in(&drv);
        } else if (!strcmp(cmd, "stop")) {
            usd_stop(&drv);
        } else if (!strcmp(cmd, "fade") && sscanf(arg, "%ld %ld %ld", &a, &b, &c) == 3) {
            usd_fade(&drv, (int)a, (int)b, (int)c);
        } else if (!strcmp(cmd, "stopowner") && sscanf(arg, "%ld", &a) == 1) {
            usd_stop_owner(&drv, (int)a);
        } else if (!strcmp(cmd, "seconds")) {
            char *end;
            double s = strtod(arg, &end);
            if (end == arg || s < 0)
                return fail(lineno, cmd, "seconds S");
            usd_run_until(&drv, usd_clock(&drv) + seconds_to_clocks(s));
        } else if (!strcmp(cmd, "clocks") && sscanf(arg, "%llu", &u) == 1) {
            usd_run_until(&drv, usd_clock(&drv) + u);
        } else if (!strcmp(cmd, "until") && sscanf(arg, "%llu", &u) == 1) {
            usd_run_until(&drv, u);
        } else if (!strcmp(cmd, "aticks") && sscanf(arg, "%llu", &u) == 1) {
            uint32_t target = usd_aticks(&drv) + (uint32_t)u;
            while (usd_aticks(&drv) < target)
                usd_step(&drv);
        } else if (!strcmp(cmd, "clock")) {
            printf("@ %llu %lu %d\n", (unsigned long long)usd_clock(&drv),
                   (unsigned long)usd_aticks(&drv), usd_active(&drv));
        } else {
            return fail(lineno, line, "unknown command or bad arguments");
        }
    }
    free(buf);
    fflush(stdout);
    fprintf(stderr, "test_usd: %d lines, %llu writes\n", lineno, nwrites);
    return 0;
}
