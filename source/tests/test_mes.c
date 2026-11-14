/* SPDX-License-Identifier: GPL-3.0-or-later */
/* test_mes FILE.MES: the interpreter's operand reader and block scanners on every offset of a
 * script loaded at 0x9000 (offsets printed relative to the file):
 *   t POS LEN              skip_token
 *   n POS VALUE NEXT       get_number where the byte is a number token (23h..2Ch)
 *   b POS OPEN END         skip_block from POS + 1 after an opener A2 (closer A3) or A0 (A1)
 * tests/check_mes.py compares with source/tools/mes.py. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ax_internal.h"
#include "vm/mes.h"
#include "hal_file.h"

int main(int argc, char **argv)
{
    struct ax_hal hal;
    FILE *f;
    long n, p;
    if (argc != 2 || !(f = fopen(argv[1], "rb"))) {
        fprintf(stderr, "usage: test_mes FILE.MES\n");
        return 2;
    }
    tf_hal(&hal, 0);
    memset(&ax, 0, sizeof ax);
    ax.hal = &hal;
    vm_init();
    n = (long)fread(ax.mem + MES_SCRIPT, 1, 0x10000 - MES_SCRIPT, f);
    fclose(f);
    /* after the script: closers, so that a scan which finds none in the file ends (mes.py does
     * not compare those offsets; the interpreter would scan on through its memory) */
    for (p = MES_SCRIPT + n; p < 0x10000; p++)
        ax.mem[p] = (p & 1) ? 0xA1 : 0xA3;
    for (p = 0; p < n; p++) {
        unsigned b = ax.mem[MES_SCRIPT + p], v;
        vm_si = (uint16_t)(MES_SCRIPT + p);
        vm_skip_token();
        printf("t %ld %d\n", p, (int)(uint16_t)(vm_si - (MES_SCRIPT + p)));
        if (b >= 0x23 && b <= 0x2C) {
            vm_si = (uint16_t)(MES_SCRIPT + p);
            vm_get_number(&v);
            printf("n %ld %u %d\n", p, v, (int)(uint16_t)(vm_si - MES_SCRIPT));
        }
        if (b == 0xA2 || b == 0xA0) {
            vm_si = (uint16_t)(MES_SCRIPT + p + 1);
            if (b == 0xA2)
                vm_skip_block(0xA2, 0xA3);
            else
                vm_skip_block(0xA0, 0xA1);
            printf("b %ld %u %d\n", p, b, (int)(uint16_t)(vm_si - MES_SCRIPT));
        }
    }
    return 0;
}
