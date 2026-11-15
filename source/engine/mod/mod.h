/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Native plug-in modules: the replacements of the machine-code plug-ins (.TCM) a game loads
 * with `load-mem` and calls with `exec-mem` (docs/re/plugins.md §1, §7). A module is selected
 * by the base name of the file `load-mem` names, if the game profile enables it, and bound to
 * the load address; `exec-mem` on that address calls it with the argument block the
 * interpreter built at 0xDA73 (count, then one word per argument; a string argument is the
 * address of its opening quote in the interpreter's memory). */
#ifndef AX_MOD_H
#define AX_MOD_H

#include <stdint.h>

struct ax_module {
    const char *name;                       /* file base name, upper case: "ACTE1" */
    void (*load)(void);                     /* load-mem of the file: in-image state reset */
    /* the call; returns (AX << 16) | CX as the interpreter reads them (CH < 0: no result) */
    unsigned long (*exec)(const uint16_t *args, int nargs);
};

void mod_init(const char *enabled);         /* the profile's list of module names */
/* load-mem of `file` at `addr`: 1 when a module took it (nothing is read into memory) */
int  mod_load(const char *file, unsigned addr);
/* exec-mem at `addr` with the block at 0xDA73; returns (AX << 16) | CX, or -1 when no module
 * is there */
long mod_exec(unsigned addr);

/* helpers for the modules */
const uint8_t *mod_string(unsigned quote_addr);     /* the bytes after the opening quote */

extern const struct ax_module mod_chgfonth, mod_palch, mod_whiteh, mod_inputnam, mod_acte1;

#endif
