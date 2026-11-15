/* SPDX-License-Identifier: GPL-3.0-or-later */
/* <stdio.h> of the freestanding m68k build of tests/be68k (rt.c): formatting into buffers;
 * fopen always fails (the harness reads its files itself). */
#ifndef BE68K_STDIO_H
#define BE68K_STDIO_H

#include <stdarg.h>
#include <stddef.h>

typedef struct be68k_file FILE;

int snprintf(char *buf, size_t n, const char *fmt, ...);
int vsnprintf(char *buf, size_t n, const char *fmt, va_list ap);
FILE *fopen(const char *path, const char *mode);
size_t fread(void *buf, size_t size, size_t n, FILE *f);
int fclose(FILE *f);

#endif
