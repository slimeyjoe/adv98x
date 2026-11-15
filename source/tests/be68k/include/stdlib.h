/* SPDX-License-Identifier: GPL-3.0-or-later */
/* <stdlib.h> of the freestanding m68k build of tests/be68k (rt.c). */
#ifndef BE68K_STDLIB_H
#define BE68K_STDLIB_H

#include <stddef.h>

void *malloc(size_t n);
void *realloc(void *p, size_t n);
void free(void *p);
void qsort(void *base, size_t n, size_t size, int (*cmp)(const void *, const void *));
unsigned long strtoul(const char *s, char **end, int base);
int abs(int v);
long labs(long v);
void exit(int code) __attribute__((noreturn));

#endif
