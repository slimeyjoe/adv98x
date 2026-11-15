/* SPDX-License-Identifier: GPL-3.0-or-later */
/* test_pack PAK: lists every entry as the engine's reader sees it,
 *   name <TAB> type <TAB> lang <TAB> size <TAB> FNV-1a 64 of the data (hex)
 * then, for each language L in 1..3 and each name asked on the command line after the pack,
 *   find <TAB> L <TAB> name <TAB> type <TAB> lang of the entry xpak_find returns (or -)
 * tests/check_pack.py compares the output with tools/xpak.py. */
#include <stdio.h>
#include "pack/pack.h"
#include "test_hal.h"

int main(int argc, char **argv)
{
    struct lrv_hal hal;
    struct xpak pk;
    int i, l, a;
    if (argc < 2 || th_hal(&hal, argv[1]) != 0 || xpak_open(&pk, &hal) != 0) {
        fprintf(stderr, "usage: test_pack PAK [NAME...]\n");
        return 2;
    }
    for (i = 0; i < pk.count; i++) {
        const struct xpak_entry *e = &pk.entries[i];
        uint32_t size;
        uint8_t *d = xpak_load(&pk, e, &size);
        uint64_t h = 1469598103934665603ull;
        uint32_t k;
        if (!d)
            return 1;
        for (k = 0; k < size; k++)
            h = (h ^ d[k]) * 1099511628211ull;
        printf("%.20s\t%d\t%d\t%lu\t%016llx\n", e->name, e->type, e->lang, (unsigned long)size,
               (unsigned long long)h);
        xpak_free(&pk, d, size);
    }
    for (l = 1; l <= 3; l++)
        for (a = 2; a < argc; a++) {
            const struct xpak_entry *e;
            pk.lang = (uint8_t)l;
            e = xpak_find(&pk, argv[a], -1);
            if (e)
                printf("find\t%d\t%s\t%d\t%d\n", l, argv[a], e->type, e->lang);
            else
                printf("find\t%d\t%s\t-\t-\n", l, argv[a]);
        }
    xpak_close(&pk);
    return 0;
}
