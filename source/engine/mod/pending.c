/* SPDX-License-Identifier: GPL-3.0-or-later */
/* PALCH and WHITEH (docs/re/plugins.md §3-5) arrive with milestone M5; until then a
 * call is logged and does nothing. */
#include "ax_internal.h"
#include "mod/mod.h"

static unsigned long later(const char *name)
{
    sys_log(AX_LOG_WARN, "module %s: not implemented yet (M5)", name);
    return 0xFF00;
}

static unsigned long palch_exec(const uint16_t *a, int n) { (void)a; (void)n; return later("PALCH"); }
static unsigned long whiteh_exec(const uint16_t *a, int n) { (void)a; (void)n; return later("WHITEH"); }

const struct ax_module mod_palch = { "PALCH", 0, palch_exec };
const struct ax_module mod_whiteh = { "WHITEH", 0, whiteh_exec };
