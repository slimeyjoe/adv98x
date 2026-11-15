/* SPDX-License-Identifier: GPL-3.0-or-later */
/* <string.h> of the freestanding m68k build of tests/be68k (rt.c): what the engine and lrvne use. */
#ifndef BE68K_STRING_H
#define BE68K_STRING_H

#include <stddef.h>

void *memcpy(void *d, const void *s, size_t n);
void *memmove(void *d, const void *s, size_t n);
void *memset(void *d, int c, size_t n);
int memcmp(const void *a, const void *b, size_t n);
size_t strlen(const char *s);
int strcmp(const char *a, const char *b);
int strncmp(const char *a, const char *b, size_t n);
char *strcpy(char *d, const char *s);
char *strncpy(char *d, const char *s, size_t n);
char *strchr(const char *s, int c);
char *strrchr(const char *s, int c);
size_t strcspn(const char *s, const char *reject);

#endif
