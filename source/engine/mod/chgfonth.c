/* SPDX-License-Identifier: GPL-3.0-or-later */
/* CHGFONTH.TCM: bold text on/off (docs/re/plugins.md §2, §7.1): bold = argc ? arg1 & 1 : 0 */
#include "ax.h"
#include "mod/mod.h"

static unsigned long chgfonth_exec(const uint16_t *args, int nargs)
{
    bt_bold((nargs & 0xFF) ? (args[0] & 1) : 0);
    return 0xFF00;
}

const struct ax_module mod_chgfonth = { "CHGFONTH", 0, chgfonth_exec, 0 };
