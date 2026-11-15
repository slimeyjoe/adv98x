/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The few system services the harness of tests/be68k needs: rt.c on m68k Linux system calls,
 * POSIX in the native build (be68k.c). */
#ifndef BE68K_H
#define BE68K_H

#include <stddef.h>

int  os_open_read(const char *path);            /* -1 on failure */
long os_read(int fd, void *buf, size_t n);
long os_write(int fd, const void *buf, size_t n);
long os_seek(int fd, long off, int whence);     /* whence 0 = SEEK_SET, 2 = SEEK_END */
void os_close(int fd);

#endif
