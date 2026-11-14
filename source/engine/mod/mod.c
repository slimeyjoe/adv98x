/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The module registry (mod.h). */
#include <string.h>
#include "ax_internal.h"
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

static int name_eq(const char *a, const char *b)
{
    for (; *a && *b; a++, b++)
        if ((*a | 0x20) != (*b | 0x20))
            return 0;
    return *a == *b;
}

void mod_init(const char *list)
{
    int i;
    nbound = 0;
    memset(enabled, 0, sizeof enabled);
    while (list && *list) {
        char w[32];
        size_t n = strcspn(list, ",");
        if (n >= sizeof w)
            n = sizeof w - 1;
        memcpy(w, list, n);
        w[n] = 0;
        for (i = 0; i < NALL; i++)
            if (name_eq(w, all[i]->name))
                enabled[i] = 1;
        list += n + (list[n] == ',');
    }
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
        if (!enabled[i] || !name_eq(base, all[i]->name))
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
        sys_trace(AX_TR_MODULE, all[i]->name, 0, -1, (int)addr, 0, 0);
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
        sys_trace_ints(AX_TR_MODULE, bound[k].m->name, ints, n, (int)addr);
    }
    return (long)bound[k].m->exec(args, n);
}

const uint8_t *mod_string(unsigned quote_addr)
{
    return ax.mem + ((quote_addr + 1) & 0xFFFF);
}
