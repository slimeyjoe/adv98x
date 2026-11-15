/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The C library of the freestanding m68k Linux build of tests/be68k (be68k.sh): what the engine,
 * lrvne and the harness call, on Linux system calls (qemu-m68k's user mode emulates them). Not
 * a general C library: formatting knows the conversions the code uses (%s %c %d %u %x %X, the
 * flags - and 0, a width, a precision, l and z), fopen fails, memory is one mapping per block. */
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "be68k.h"

/* ---- startup, system calls, setjmp ------------------------------------------------------- */

__asm__(
    "   .text\n"
    "   .globl _start\n"
    "_start:\n"                             /* (sp) = argc, 4(sp) = argv[0], ... */
    "   move.l  (%sp),%d0\n"
    "   lea     4(%sp),%a0\n"
    "   move.l  %a0,-(%sp)\n"
    "   move.l  %d0,-(%sp)\n"
    "   jsr     main\n"
    "   move.l  %d0,%d1\n"
    "   moveq   #1,%d0\n"                   /* exit */
    "   trap    #0\n"
    /* long rt_syscall(long nr, long a, long b, long c, long d, long e, long f): d0 = nr,
     * the arguments in d1-d5 and a0 */
    "   .globl rt_syscall\n"
    "rt_syscall:\n"
    "   movem.l %d2-%d5,-(%sp)\n"
    "   move.l  20(%sp),%d0\n"
    "   move.l  24(%sp),%d1\n"
    "   move.l  28(%sp),%d2\n"
    "   move.l  32(%sp),%d3\n"
    "   move.l  36(%sp),%d4\n"
    "   move.l  40(%sp),%d5\n"
    "   move.l  44(%sp),%a0\n"
    "   trap    #0\n"
    "   movem.l (%sp)+,%d2-%d5\n"
    "   rts\n"
    /* jmp_buf: d2-d7 a2-a7 (48 bytes), the return address, fp2-fp7 (72 bytes) */
    "   .globl setjmp\n"
    "setjmp:\n"
    "   move.l  4(%sp),%a0\n"
    "   movem.l %d2-%d7/%a2-%a7,(%a0)\n"
    "   move.l  (%sp),48(%a0)\n"
    "   fmovem.x %fp2-%fp7,52(%a0)\n"
    "   moveq   #0,%d0\n"
    "   rts\n"
    "   .globl longjmp\n"
    "longjmp:\n"
    "   move.l  4(%sp),%a0\n"
    "   move.l  8(%sp),%d0\n"
    "   bne.s   1f\n"
    "   moveq   #1,%d0\n"
    "1: fmovem.x 52(%a0),%fp2-%fp7\n"
    "   movem.l (%a0),%d2-%d7/%a2-%a7\n"    /* sp as setjmp found it: at its return slot */
    "   move.l  48(%a0),(%sp)\n"
    "   rts\n");

long rt_syscall(long nr, long a, long b, long c, long d, long e, long f);

enum { SYS_EXIT = 1, SYS_READ = 3, SYS_WRITE = 4, SYS_OPEN = 5, SYS_CLOSE = 6, SYS_LSEEK = 19,
       SYS_MUNMAP = 91, SYS_MMAP2 = 192 };

int os_open_read(const char *path)
{
    long fd = rt_syscall(SYS_OPEN, (long)path, 0 /* O_RDONLY */, 0, 0, 0, 0);
    return fd < 0 ? -1 : (int)fd;
}

long os_read(int fd, void *buf, size_t n)
{
    return rt_syscall(SYS_READ, fd, (long)buf, (long)n, 0, 0, 0);
}

long os_write(int fd, const void *buf, size_t n)
{
    return rt_syscall(SYS_WRITE, fd, (long)buf, (long)n, 0, 0, 0);
}

long os_seek(int fd, long off, int whence)
{
    return rt_syscall(SYS_LSEEK, fd, off, whence, 0, 0, 0);
}

void os_close(int fd)
{
    rt_syscall(SYS_CLOSE, fd, 0, 0, 0, 0, 0);
}

void exit(int code)
{
    for (;;)
        rt_syscall(SYS_EXIT, code, 0, 0, 0, 0, 0);
}

/* ---- memory: a mapping per block, its size in front ---------------------------------------- */

#define HDR 8

void *malloc(size_t n)
{
    long p = rt_syscall(SYS_MMAP2, 0, (long)(n + HDR), 3 /* PROT_READ|WRITE */,
                        0x22 /* MAP_PRIVATE|MAP_ANONYMOUS */, -1, 0);
    if (p < 0 && p > -4096)
        return 0;
    *(size_t *)p = n + HDR;
    return (char *)p + HDR;
}

void free(void *p)
{
    if (p) {
        char *b = (char *)p - HDR;
        rt_syscall(SYS_MUNMAP, (long)b, (long)*(size_t *)b, 0, 0, 0, 0);
    }
}

void *realloc(void *p, size_t n)
{
    void *q = malloc(n);
    if (q && p) {
        size_t old = *(size_t *)((char *)p - HDR) - HDR;
        memcpy(q, p, old < n ? old : n);
        free(p);
    }
    return q;
}

/* ---- <string.h> ---------------------------------------------------------------------------- */

/* Not inlined: GCC 16.2 for m68k inlined this loop into realloc as move.b (a1)+,(0,a1,d0.l)
 * with d0 computed for the destination as if a1 were not yet incremented; the 68k (and
 * qemu) increment it first, so the copy came out one byte off. */
__attribute__((noinline)) void *memcpy(void *d, const void *s, size_t n)
{
    unsigned char *p = d;
    const unsigned char *q = s;
    while (n--)
        *p++ = *q++;
    return d;
}

__attribute__((noinline)) void *memmove(void *d, const void *s, size_t n)
{
    unsigned char *p = d;
    const unsigned char *q = s;
    if (p < q)
        while (n--)
            *p++ = *q++;
    else
        while (n--)
            p[n] = q[n];
    return d;
}

__attribute__((noinline)) void *memset(void *d, int c, size_t n)
{
    unsigned char *p = d;
    while (n--)
        *p++ = (unsigned char)c;
    return d;
}

int memcmp(const void *a, const void *b, size_t n)
{
    const unsigned char *p = a, *q = b;
    for (; n; n--, p++, q++)
        if (*p != *q)
            return *p - *q;
    return 0;
}

size_t strlen(const char *s)
{
    size_t n = 0;
    while (s[n])
        n++;
    return n;
}

int strncmp(const char *a, const char *b, size_t n)
{
    for (; n; n--, a++, b++) {
        if (*a != *b)
            return (unsigned char)*a - (unsigned char)*b;
        if (!*a)
            return 0;
    }
    return 0;
}

int strcmp(const char *a, const char *b)
{
    return strncmp(a, b, (size_t)-1);
}

char *strcpy(char *d, const char *s)
{
    char *r = d;
    while ((*d++ = *s++) != 0)
        ;
    return r;
}

char *strncpy(char *d, const char *s, size_t n)
{
    size_t i = 0;
    for (; i < n && s[i]; i++)
        d[i] = s[i];
    for (; i < n; i++)
        d[i] = 0;
    return d;
}

char *strchr(const char *s, int c)
{
    for (;; s++) {
        if (*s == (char)c)
            return (char *)s;
        if (!*s)
            return 0;
    }
}

char *strrchr(const char *s, int c)
{
    const char *r = 0;
    for (;; s++) {
        if (*s == (char)c)
            r = s;
        if (!*s)
            return (char *)r;
    }
}

size_t strcspn(const char *s, const char *reject)
{
    size_t n = 0;
    for (; s[n] && !strchr(reject, s[n]); n++)
        ;
    return n;
}

/* ---- <stdlib.h> ---------------------------------------------------------------------------- */

int abs(int v) { return v < 0 ? -v : v; }
long labs(long v) { return v < 0 ? -v : v; }

/* insertion sort: stable, as glibc's merge sort is, so equal keys keep their order on both */
void qsort(void *base, size_t n, size_t size, int (*cmp)(const void *, const void *))
{
    unsigned char *b = base, tmp[64];
    size_t i, j;
    if (size > sizeof tmp)
        exit(99);
    for (i = 1; i < n; i++) {
        memcpy(tmp, b + i * size, size);
        for (j = i; j > 0 && cmp(b + (j - 1) * size, tmp) > 0; j--)
            memcpy(b + j * size, b + (j - 1) * size, size);
        memcpy(b + j * size, tmp, size);
    }
}

unsigned long strtoul(const char *s, char **end, int base)
{
    unsigned long v = 0;
    const char *p = s;
    while (*p == ' ' || *p == '\t' || *p == '\n')
        p++;
    if (*p == '+')
        p++;
    if ((base == 0 || base == 16) && p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) {
        p += 2;
        base = 16;
    } else if (base == 0) {
        base = *p == '0' ? 8 : 10;
    }
    for (;; p++) {
        int d = *p >= '0' && *p <= '9' ? *p - '0' : *p >= 'a' && *p <= 'z' ? *p - 'a' + 10
              : *p >= 'A' && *p <= 'Z' ? *p - 'A' + 10 : 99;
        if (d >= base)
            break;
        v = v * (unsigned long)base + (unsigned long)d;
    }
    if (end)
        *end = (char *)p;
    return v;
}

/* ---- <stdio.h> ----------------------------------------------------------------------------- */

FILE *fopen(const char *path, const char *mode)
{
    (void)path;
    (void)mode;
    return 0;
}

size_t fread(void *buf, size_t size, size_t n, FILE *f)
{
    (void)buf; (void)size; (void)n; (void)f;
    return 0;
}

int fclose(FILE *f)
{
    (void)f;
    return 0;
}

struct out { char *buf; size_t cap, len; };

static void put(struct out *o, char c)
{
    if (o->len + 1 < o->cap)
        o->buf[o->len] = c;
    o->len++;
}

int vsnprintf(char *buf, size_t cap, const char *fmt, va_list ap)
{
    struct out o;
    o.buf = buf;
    o.cap = cap;
    o.len = 0;
    for (; *fmt; fmt++) {
        char digits[24], *s;
        int left = 0, zero = 0, width = 0, prec = -1, lng = 0, neg = 0, n, i;
        unsigned long u;
        if (*fmt != '%') {
            put(&o, *fmt);
            continue;
        }
        for (fmt++; *fmt == '-' || *fmt == '0'; fmt++)
            *fmt == '-' ? (left = 1) : (zero = 1);
        if (*fmt == '*') {
            width = va_arg(ap, int);
            fmt++;
        }
        for (; *fmt >= '0' && *fmt <= '9'; fmt++)
            width = width * 10 + *fmt - '0';
        if (*fmt == '.') {
            prec = 0;
            if (*++fmt == '*') {
                prec = va_arg(ap, int);
                fmt++;
            }
            for (; *fmt >= '0' && *fmt <= '9'; fmt++)
                prec = prec * 10 + *fmt - '0';
        }
        for (; *fmt == 'l' || *fmt == 'z'; fmt++)
            lng = 1;
        switch (*fmt) {
        case 's':
            s = va_arg(ap, char *);
            if (!s)
                s = "(null)";
            for (n = 0; s[n] && (prec < 0 || n < prec); n++)
                ;
            break;
        case 'c':
            digits[0] = (char)va_arg(ap, int);
            s = digits;
            n = 1;
            break;
        case 'd': case 'i': case 'u': case 'x': case 'X': {
            const char *hex = *fmt == 'X' ? "0123456789ABCDEF" : "0123456789abcdef";
            unsigned base = *fmt == 'x' || *fmt == 'X' ? 16u : 10u;
            if (*fmt == 'd' || *fmt == 'i') {
                long v = lng ? va_arg(ap, long) : va_arg(ap, int);
                neg = v < 0;
                u = neg ? 0ul - (unsigned long)v : (unsigned long)v;
            } else {
                u = lng ? va_arg(ap, unsigned long) : va_arg(ap, unsigned);
            }
            s = digits + sizeof digits;
            n = 0;
            do {
                *--s = hex[u % base];
                u /= base;
                n++;
            } while (u);
            for (; n < prec; n++)
                *--s = '0';
            if (neg) {
                if (zero && !left)
                    width--, put(&o, '-');
                else
                    *--s = '-', n++;
            }
            break;
        }
        case '%':
            s = "%";
            n = 1;
            break;
        default:
            return -1;
        }
        if (!left)
            for (i = n; i < width; i++)
                put(&o, zero && *fmt != 's' && *fmt != 'c' ? '0' : ' ');
        for (i = 0; i < n; i++)
            put(&o, s[i]);
        if (left)
            for (i = n; i < width; i++)
                put(&o, ' ');
    }
    if (o.cap)
        o.buf[o.len < o.cap ? o.len : o.cap - 1] = 0;
    return (int)o.len;
}

int snprintf(char *buf, size_t cap, const char *fmt, ...)
{
    va_list ap;
    int n;
    va_start(ap, fmt);
    n = vsnprintf(buf, cap, fmt, ap);
    va_end(ap);
    return n;
}
