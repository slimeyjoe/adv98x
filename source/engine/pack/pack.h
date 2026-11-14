/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Asset pack ("XPAK") reader.
 *
 * All game data (pictures, songs, scripts, click maps, fonts, language tables, the game profile)
 * is stored in one pack built by tools/mkpack.py. The pack is either appended to the executable (found via
 * a 16-byte trailer at the end of the file) or a separate file next to it.
 *
 * Layout (little-endian):
 *   0x00  4   "XPAK"
 *   0x04  u16 format version (1)
 *   0x06  u16 entry count
 *   0x08  u32 total pack size (bytes, including this header)
 *   0x0C  4   reserved (0)
 *   0x10  entries, 32 bytes each, sorted by (lang, name) for binary search:
 *         name[20] (NUL padded, upper-case base name without extension, e.g. "NV01", "RUN",
 *                   "font16", "strings"), u8 type, u8 lang, u16 reserved, u32 offset, u32 size
 *   data, each entry 4-byte aligned, offsets relative to the pack start.
 *
 * Trailer appended after the pack when it is bundled into an executable:
 *   "XPKT" + u32 pack size + u32 ~pack size + 4 bytes "XPKT"  (16 bytes)
 *
 * The engine asks the backend for an opaque handle and reads ranges through hal->pack_read, so
 * a backend may memory-map, preload or stream from a slow disk. The entry table is read once. */
#ifndef AX_PACK_PACK_H
#define AX_PACK_PACK_H

#include <stddef.h>
#include <stdint.h>

#define XPAK_MAGIC        "XPAK"
#define XPAK_VERSION      1
#define XPAK_HEADER_SIZE  16
#define XPAK_ENTRY_SIZE   32
#define XPAK_NAME_LEN     20
#define XPKT_TRAILER_SIZE 16

enum xpak_type {
    XPAK_T_GPC     = 1,   /* GPC picture, byte-exact original */
    XPAK_T_USO     = 2,   /* USO song, byte-exact original */
    XPAK_T_MES     = 3,   /* MES script, byte-exact original (per language) */
    XPAK_T_CLM     = 4,   /* click map, byte-exact original */
    XPAK_T_FONT    = 5,   /* glyph table (xfont format) */
    XPAK_T_STRINGS = 6,   /* language string table */
    XPAK_T_META    = 7,   /* pack, profile and language metadata (key=value text) */
    XPAK_T_BLOB    = 8    /* anything else */
};

/* Language ids; 0 = language-neutral (shared by all languages). */
enum xpak_lang {
    XPAK_L_ANY = 0,
    XPAK_L_JA  = 1,
    XPAK_L_EN  = 2,
    XPAK_L_PL  = 3
};

/* Language id for a name ("ja", "en", "pl", any case); 0 (pack default) if unknown. */
int xpak_lang_id(const char *name);

struct xpak_entry {
    char     name[XPAK_NAME_LEN];
    uint8_t  type;
    uint8_t  lang;
    uint32_t offset;
    uint32_t size;
};

struct ax_hal;

struct xpak {
    const struct ax_hal *hal;
    void *src;                    /* backend pack handle */
    uint32_t base;                /* offset of the pack inside the source (0, or inside an exe) */
    uint32_t total;
    uint16_t count;
    struct xpak_entry *entries;   /* allocated through the HAL */
    uint8_t lang;                 /* current language for lookups (falls back to XPAK_L_ANY) */
};

/* Open the pack through the backend. Returns 0 on success, -1 on failure (logged). */
int xpak_open(struct xpak *pk, const struct ax_hal *hal);
void xpak_close(struct xpak *pk);

/* Look up an entry by name (case-insensitive) in the current language, then in the neutral
 * set. Returns NULL if absent. */
const struct xpak_entry *xpak_find(const struct xpak *pk, const char *name, int type);

/* Read a whole entry into a buffer allocated through the HAL (caller frees with xpak_free).
 * Returns NULL on failure. `*size` receives the entry size. */
uint8_t *xpak_load(const struct xpak *pk, const struct xpak_entry *e, uint32_t *size);
void xpak_free(const struct xpak *pk, uint8_t *data, uint32_t size);

/* Read part of an entry into a caller buffer. Returns bytes read. */
size_t xpak_read(const struct xpak *pk, const struct xpak_entry *e, uint32_t off,
                 void *dst, size_t n);

#endif
