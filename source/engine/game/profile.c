/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The game profile: what makes the generic engine run one particular Adv98V game. It is the
 * pack's "profile" meta entry (tools/mkpack.py), key=value lines in UTF-8:
 *   title=...            window title
 *   start=RUN            the script NV.INI would start (docs/re/interpreter.md §7)
 *   modules=a,b,...      the plug-in modules (.TCM replacements) the game enables
 *   lang=ja              the default language */
#include <string.h>
#include "ax_internal.h"

static void copy_val(char *dst, size_t cap, const uint8_t *v, size_t n)
{
    if (n >= cap)
        n = cap - 1;
    memcpy(dst, v, n);
    dst[n] = 0;
}

int profile_load(struct ax_profile *p)
{
    const struct xpak_entry *e = xpak_find(&ax.pak, "profile", XPAK_T_META);
    uint8_t *blob;
    uint32_t size, i = 0;

    memset(p, 0, sizeof *p);
    strcpy(p->title, "Adv98X");
    strcpy(p->start, "RUN");
    p->default_lang = XPAK_L_JA;
    if (!e || !(blob = xpak_load(&ax.pak, e, &size)))
        return -1;
    while (i < size) {
        uint32_t s = i, eq = 0, end;
        while (i < size && blob[i] != '\n') {
            if (!eq && blob[i] == '=')
                eq = i;
            i++;
        }
        end = i++;
        if (!eq)
            continue;
        if (eq - s == 5 && !memcmp(blob + s, "title", 5))
            copy_val(p->title, sizeof p->title, blob + eq + 1, end - eq - 1);
        else if (eq - s == 5 && !memcmp(blob + s, "start", 5))
            copy_val(p->start, sizeof p->start, blob + eq + 1, end - eq - 1);
        else if (eq - s == 7 && !memcmp(blob + s, "modules", 7))
            copy_val(p->modules, sizeof p->modules, blob + eq + 1, end - eq - 1);
        else if (eq - s == 4 && !memcmp(blob + s, "lang", 4)) {
            char l[8];
            copy_val(l, sizeof l, blob + eq + 1, end - eq - 1);
            if (xpak_lang_id(l))
                p->default_lang = xpak_lang_id(l);
        }
    }
    xpak_free(&ax.pak, blob, size);
    return 0;
}
