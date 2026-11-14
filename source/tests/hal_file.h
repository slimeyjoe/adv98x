/* SPDX-License-Identifier: GPL-3.0-or-later */
/* A minimal HAL for the unit tests: a pack from a file, malloc, logging to stderr. */
#ifndef AX_TESTS_HAL_FILE_H
#define AX_TESTS_HAL_FILE_H

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ax_hal.h"

static FILE *tf_pak;
static uint32_t tf_size;

static void *tf_open(uint32_t *size) { *size = tf_size; return tf_pak; }
static size_t tf_read(void *h, uint32_t off, void *dst, size_t n)
{
    if (fseek((FILE *)h, (long)off, SEEK_SET) != 0)
        return 0;
    return fread(dst, 1, n, (FILE *)h);
}
static void tf_close(void *h) { (void)h; }
static void *tf_alloc(size_t n, unsigned f) { (void)f; return malloc(n); }
static void tf_free(void *p, size_t n) { (void)n; free(p); }
static void tf_log(int level, const char *msg) { if (level >= AX_LOG_WARN) fprintf(stderr, "%s\n", msg); }
static void tf_fatal(const char *msg) { fprintf(stderr, "fatal: %s\n", msg); exit(1); }

/* fills *hal; returns 0, or -1 when the pack cannot be opened */
static int tf_hal(struct ax_hal *hal, const char *pak)
{
    memset(hal, 0, sizeof *hal);
    hal->pack_open = tf_open; hal->pack_read = tf_read; hal->pack_close = tf_close;
    hal->mem_alloc = tf_alloc; hal->mem_free = tf_free; hal->log = tf_log; hal->fatal = tf_fatal;
    if (!pak)
        return 0;
    tf_pak = fopen(pak, "rb");
    if (!tf_pak)
        return -1;
    fseek(tf_pak, 0, SEEK_END);
    tf_size = (uint32_t)ftell(tf_pak);
    return 0;
}

#endif
