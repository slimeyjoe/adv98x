/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The module registry (mod.h). */
#include <string.h>
#include "ax.h"
#include "mod/mod.h"
#include "vm/mes.h"

static const struct ax_module *const all[] = {
    &mod_chgfonth, &mod_palch, &mod_whiteh, &mod_inputnam, &mod_acte1
};
#define NALL ((int)(sizeof all / sizeof all[0]))

#define MAXBOUND 16
static struct { unsigned addr; const struct ax_module *m; } bound[MAXBOUND];
static int nbound;
static int enabled[NALL];

void mod_init(const char *list)
{
    int i;
    nbound = 0;
    for (i = 0; i < NALL; i++)          /* a fresh start (also after a reset): nothing loaded */
        if (all[i]->load)
            all[i]->load();
    for (i = 0; i < NALL; i++)
        enabled[i] = lrv_list_has(list, all[i]->name);
}

int mod_load(const char *file, unsigned addr)
{
    char base[32];
    const char *p = file, *b = file;
    size_t n;
    int i, k;
    for (; *p; p++)
        if (*p == '\\' || *p == '/' || *p == ':')
            b = p + 1;
    n = strcspn(b, ".");
    if (n >= sizeof base)
        return 0;
    memcpy(base, b, n);
    base[n] = 0;
    for (i = 0; i < NALL; i++) {
        if (!enabled[i] || !lrv_name_eq(base, all[i]->name))
            continue;
        for (k = 0; k < nbound && bound[k].addr != addr; k++)
            ;
        if (k == nbound) {
            if (nbound == MAXBOUND)
                return 0;
            nbound++;
        }
        bound[k].addr = addr;
        bound[k].m = all[i];
        if (all[i]->load)
            all[i]->load();
        lrv_sys_trace(&ax.sys, AX_TR_MODULE, all[i]->name, 0, -1, (int)addr, 0, 0);
        return 1;
    }
    return 0;
}

long mod_exec(unsigned addr)
{
    uint16_t args[64];
    int k, n, i;
    for (k = 0; k < nbound && bound[k].addr != addr; k++)
        ;
    if (k == nbound)
        return -1;
    n = vm_rd16(MES_ARGS);
    if (n > 64)
        n = 64;
    for (i = 0; i < n; i++)
        args[i] = vm_rd16(MES_ARGS + 2 + 2 * (unsigned)i);
    {
        int ints[64];
        for (i = 0; i < n; i++)
            ints[i] = args[i];
        lrv_sys_trace_ints(&ax.sys, AX_TR_MODULE, bound[k].m->name, ints, n, (int)addr);
    }
    return (long)bound[k].m->exec(args, n);
}

const uint8_t *mod_string(unsigned quote_addr)
{
    return ax.mem + ((quote_addr + 1) & 0xFFFF);
}
