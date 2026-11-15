/* SPDX-License-Identifier: GPL-3.0-or-later */
/* test_pack PAK [NAME...]: the pack as the engine reads it (lrvne's reader):
 *   lang <TAB> id <TAB> tag                    for every language the pack names
 *   name <TAB> type <TAB> lang <TAB> size <TAB> FNV-1a 64 of the data (hex)   for every entry
 * then, for each language and each NAME,
 *   find <TAB> lang id <TAB> name <TAB> type <TAB> lang of the entry lrv_pack_find returns (or -)
 * tests/check_pack.py compares the output with the pack tool's reading and the originals. */
#include <stdio.h>
#include "lrvne/pack.h"
#include "test_hal.h"

int main(int argc, char **argv)
{
    struct lrv_hal hal;
    struct lrv_pack pk;
    int i, l, a;
    if (argc < 2 || th_hal(&hal, argv[1]) != 0 || lrv_pack_open(&pk, &hal, LRV_PACK_MAIN) != 0) {
        fprintf(stderr, "usage: test_pack PAK [NAME...]\n");
        return 2;
    }
    for (l = 1; l <= LRV_PACK_LANGS_MAX; l++)
        if (lrv_pack_lang_tag(&pk, l))
            printf("lang\t%d\t%s\n", l, lrv_pack_lang_tag(&pk, l));
    for (i = 0; i < pk.count; i++) {
        const struct lrv_pack_entry *e = &pk.entries[i];
        uint32_t size;
        uint8_t *d = lrv_pack_load(&pk, e, &size);
        uint64_t h = 1469598103934665603ull;
        uint32_t k;
        if (!d)
            return 1;
        for (k = 0; k < size; k++)
            h = (h ^ d[k]) * 1099511628211ull;
        printf("%s\t%d\t%d\t%lu\t%016llx\n", e->name, e->type, e->lang, (unsigned long)size,
               (unsigned long long)h);
        lrv_pack_free(&pk, d, size);
    }
    for (l = 1; l <= LRV_PACK_LANGS_MAX; l++) {
        if (!lrv_pack_lang_tag(&pk, l))
            continue;
        lrv_pack_set_lang(&pk, l);
        for (a = 2; a < argc; a++) {
            const struct lrv_pack_entry *e = lrv_pack_find(&pk, argv[a], LRV_PT_ANY);
            if (e)
                printf("find\t%d\t%s\t%d\t%d\n", l, argv[a], e->type, e->lang);
            else
                printf("find\t%d\t%s\t-\t-\n", l, argv[a]);
        }
    }
    lrv_pack_close(&pk);
    return 0;
}
