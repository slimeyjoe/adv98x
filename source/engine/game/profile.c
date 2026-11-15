/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The game profile: what makes the generic engine run one particular Adv98V game. It is the
 * pack's "profile" entry (tools/mkpack.py writes it), key=value lines in UTF-8, parsed by
 * lrvne (lrvne/profile.h):
 *   id=...               the game's short name: names the directory of its saves
 *   title=...            window title (default: the id)
 *   lang=ja              the default language, a tag of the pack's languages
 *   modules=A,B,...      the plug-in modules the game enables (mod/mod.h), by the base names
 *                        of the plug-in files its scripts load
 *   start=...            the script the game starts with, named as the original's start file
 *                        names it (docs/re/interpreter.md §7) */
#include <string.h>
#include "ax.h"

static const struct lrv_pfield fields[] = {
    LRV_PROFILE_BASE_FIELDS(struct ax_profile, base),
    LRV_PF_STR("start", struct ax_profile, start)
};

int profile_load(void)
{
    struct ax_profile *p = &ax.profile;
    int rc;
    memset(p, 0, sizeof *p);
    rc = lrv_profile_load(&ax.pack, fields, (int)(sizeof fields / sizeof fields[0]), p);
    if (rc == LRV_ERR_NOTFOUND)
        lrv_log(ax.hal, LRV_LOG_ERROR, "pack: no game profile");
    else if (rc == LRV_OK && (!p->base.id[0] || !p->start[0])) {
        lrv_log(ax.hal, LRV_LOG_ERROR, "profile: id and start are required");
        rc = LRV_ERR_FORMAT;
    }
    if (!p->base.title[0])
        strcpy(p->base.title, p->base.id);
    return rc;
}
