/* SPDX-License-Identifier: GPL-3.0-or-later */
/* <setjmp.h> of the freestanding m68k build of tests/be68k (rt.c): d2-d7, a2-a7, the return
 * address and fp2-fp7. */
#ifndef BE68K_SETJMP_H
#define BE68K_SETJMP_H

typedef long jmp_buf[32];

int setjmp(jmp_buf env);
void longjmp(jmp_buf env, int value) __attribute__((noreturn));

#endif
