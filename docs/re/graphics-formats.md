# NOVA picture formats: GPC (PC-98) and Pi (Windows)

Scope: the still-picture files of NOVA (Cat's Pro, 1993; engine Adv98V 1.70.54)
and of its 1996 Windows re-release. Tools:

| tool | purpose |
|---|---|
| `source/tools/gpc.py` | GPC decoder (library + `info` / `png` CLI), stdlib only |
| `re-tools/pi.py` | Pi decoder (same interface), stdlib only |
| `re-tools/gpc_verify.py` | cross-checks GPC decoder against the Windows PI files and against the original decoder in `NV.OV1` run under Unicorn |

Converted pictures go to `resources/derived/images/{gpc,pi}/` (each with an
`index.tsv` giving position, size and palette); the verifier's table is
`resources/derived/images/gpc_verify.tsv`. Nothing derived from game art is
kept under `docs/`.

Marking used below: **[V]** verified (against all files, the original code, or
both, as stated), **[I]** inferred, **[?]** unknown.

Credits / prior art. The GPC layout and algorithm were first documented by
Kirinn Bunnylin for SuperSakura (`doc/gfx/gpc-gpa.md`, relayed by the
lime-juice project); the "XOR accumulator carries across chains" detail was
also reported by hermit1000/mes-tools (`GPC_RUNTIME_ANALYSIS.md`). The Pi
description used is Kirinn Bunnylin's <https://mooncore.eu/bunny/txt/pi-pic.htm>.
Both decoders here were written from those descriptions and then checked
against the game's own code; no code was copied.

## 1. Corpus

- PC-98: 122 `*.GPC` files on disks A-D = 102 names = 103 distinct contents.
  Every name present on several disks is byte-identical across them, except
  `NV43A.GPC` (disk B vs disk C, see 6.4). **[V]**
- Windows: 123 `*.PI` files; 84 share a name with a GPC, 9 more are the
  full-screen equivalents of GPC "A"/"B" half pairs, 30 are Windows-only
  (see 5.3). **[V]**
- File sizes 108 (`OPPAL`) to 62 365 bytes (`NV33`). AdvBIOS loads a GPC whole
  into a fixed buffer and reports `0xF800` (63 488) as its capacity, so that is
  the engine's hard limit for a GPC file. **[V: code at image 0x299E]** / **[I]**
  for "hard limit".

## 2. GPC container

All integers little-endian. Offsets in hex.

### 2.1 File header (0x30 bytes in every NOVA file)

| ofs | size | field | observed in all 103 contents |
|---|---|---|---|
| 00 | 16 | signature `"PC98)GPCFILE   "` + NUL | constant **[V]**. The AdvBIOS draw routine never checks it **[V: code]** |
| 10 | u32 | row interleave step `N` | 1 (28 files), 2 (69), 4 (2: `NV12B`, `NV50`), 16 (4: `MAP1`-`MAP4`); never 0 **[V]**. Original reads only the low 16 bits **[V]** |
| 14 | u32 | offset of palette block | always 0x30 **[V]**; 0 would mean "no palette" per the SuperSakura notes **[I]**, never occurs here. The original reads 16 bits and does not test for 0 **[V]** |
| 18 | u32 | offset of image block | always 0x5A **[V]** |
| 1C | u32 | reserved | always 0 **[V]**, not read by the decoder **[V]** |
| 20 | u32 | total file size | equals the real file size in every file **[V]**; not read by the decoder **[V]** |
| 24 | 12 | reserved | always 0 **[V]** |

### 2.2 Palette block (at 0x30, 0x2A bytes)

| ofs | size | field | observed |
|---|---|---|---|
| +0 | u16 | number of entries | 16 **[V]** (not read by the decoder: it always copies 16 words from +4 **[V]**) |
| +2 | u16 | bytes per entry | 2 **[V]** (not read) |
| +4 | 16 x u16 | colour `0x0GRB`: bits 11-8 green, 7-4 red, 3-0 blue, 4 bits each; entry *i* is colour index *i* | bits 15-12 always 0 **[V]** |
| +24 | 6 | `"n*bys"` + NUL | constant in all files **[V]**; meaning unknown **[?]**, not read |

The `0x0GRB` order is **[V]** twice: (a) the original DAC routine (image
0x2C9C) sends bits 11-8 to port 0xAA (green), bits 7-4 to 0xAC (red), bits 3-0
to 0xAE (blue) after selecting the index on 0xA8; (b) with this order the
palettes equal the Windows PI palettes for 80 of 85 comparable pictures, the 5
exceptions being deliberate changes (section 5.2). As bytes on disk an entry is
`RB 0G`.

Conversion to 8 bits per channel: replicate the nibble (`v * 17`). **[I]** (the
PC-98 DAC is 4-bit; the Windows PI files of converted art store `v << 4`.)

### 2.3 Image block (at 0x5A; 16-byte header, then the stream)

| ofs | size | field | observed |
|---|---|---|---|
| +0 | u16 | width in pixels | 16 ... 640, always a multiple of 8 **[V]**. Decoder uses `(width + 7) >> 3` bytes **[V]** |
| +2 | u16 | height in rows | 13 ... 400 **[V]** |
| +4 | u32 | length of the compressed stream in bytes (excluding these 16 bytes) | equals `file size - 0x6A` in every file, and the decoder consumes exactly that many bytes **[V]**. Not read by the original decoder (it stops when all rows are produced) **[V]**. SuperSakura documents this as u16 + unknown u16; in NOVA the high word is always 0 so u32 is **[I]** |
| +8 | u16 | bits per pixel / plane count | 4 **[V]**; not read by the decoder (4 planes are hard-wired) **[V]** |
| +A | u16 | x position in pixels | 0 ... 552, always a multiple of 8 **[V]**. The decoder uses `x >> 3` (byte column) **[V]** |
| +C | u16 | y position in rows | 0 ... 297 **[V]** |
| +E | u16 | unknown | always 0 **[V]**. The original loads it into AX and immediately discards it **[V]** |
| +10 | ... | compressed stream | runs to end of file **[V]** |

`x + width <= 640` and `y + height <= 400` hold for every file **[V]**.

## 3. GPC compression

Three reversible layers. Let `bw = (width + 7) >> 3` (bytes per bit plane per
row), `L = 4 * bw` (row payload) and `S = L + 1` (stored row = 1 filter byte +
payload).

### 3.1 Layer 1: zero suppression

The stream expands to `height * S` bytes. **[V]**

```
out = []
while len(out) < height * S:
    A = next_byte()
    for bit in 7..0 of A:                 # MSB first
        if A.bit == 0:
            out += [0] * 8
        else:
            B = next_byte()
            for bit in 7..0 of B:         # MSB first
                out += [next_byte()] if B.bit else [0]
truncate out to height * S
```

- Groups do not respect row boundaries: an 8-byte group or a whole 64-byte `A`
  unit can straddle two stored rows (the original decodes row by row and
  carries the surplus bytes over to the next row; image 0x2B94, 0x2A7C). **[V]**
- The final `A` unit normally overshoots the buffer; the surplus is discarded.
  In all NOVA files the bytes consumed for a complete `A` unit that covers the
  last needed byte equal the stream length field exactly (no trailing junk, no
  truncated streams). **[V]**
- There is no end marker and the original does no input bounds check. **[V]**
  `gpc.py` treats missing input as zeros. **[I]** (not exercised by any file)

### 3.2 Layer 2: row filters (horizontal XOR, then vertical XOR)

Rows are processed in *stored* order `r = 0 .. height-1`. Each stored row is
`F, d[0..L-1]`.

```
prev = [0] * L
for r in 0 .. height-1:
    F, d = stored_row(r)
    if F != 0:                            # horizontal: running XOR over F interleaved chains
        acc = 0                           # reset ONCE per row
        for start in 0 .. F-1:
            for i in start, start+F, start+2F, ... while i < L:
                acc ^= d[i]
                d[i] = acc                # acc is NOT reset when a new chain starts
    if r != 0:                            # vertical: XOR with previously stored row
        d ^= prev                         # (prev is the fully decoded previous stored row)
    prev = d
```

- **Accumulator carry-over: the mes-tools report is right.** The original
  (image 0x2B57) keeps `AL` when it moves to the next chain, so the first byte
  of chain `k` is XORed with the last byte of chain `k-1`. **[V: code]** It
  only matters when `F >= 2`; it changes pixels in 7 NOVA files (`MAP1`-`MAP4`,
  `NV12A`, `NV16B`, `NV32A`), which decode wrongly (e.g. 14 320 wrong pixels in
  `MAP1`) with a per-chain reset. **[V: PI + emulation]** (The SuperSakura
  pseudo-code also carries over; only its prose/table could be read otherwise.)
- The filter acts on the whole payload of `L` bytes, i.e. chains run straight
  across the four planes. **[V]**
- Filter values seen (rows): 0: 43 603, 1: 1 831, 2: 326, 3: 3, 4: 9, and 5, 9,
  12, 14 once each (all four in `NV12A`). **[V]**
- "Previous row" for the vertical XOR is the previous row *in the file*, which
  with interleaving is not the row above on screen. **[V]**

### 3.3 Layer 3: row interleave

Stored rows are dealt to screen rows in `N` passes (`N` = header 0x10):

```
src = 0
for pass in 0 .. N-1:
    for y in pass, pass+N, pass+2N, ... while y < height:
        screen_row[y] = stored_row[src]; src += 1
```

`N = 1` is plain top-to-bottom order. **[V]** `N = 0` never occurs; the
original would loop forever on it (it subtracts `N` from a row counter until it
reaches 0), `gpc.py` treats it like 1. **[V: code]** / **[I]**. Because the
original draws rows as they are decoded, the picture visibly appears in `N`
venetian-blind passes on a real machine (very fast for N = 2; `MAP*` use 16).
**[I]**

### 3.4 Planes to pixels

Each decoded row is four bit planes side by side: bytes `[0, bw)` plane 0,
`[bw, 2bw)` plane 1, and so on. Bit 7 of a byte is the leftmost pixel; plane
`p` supplies bit `p` of the colour index. **[V]** (Plane 0..3 go to the four
segment values the caller passes, in that order; on PC-98 hardware colour bit
0..3 = VRAM planes B, R, G, E/I. **[I]** for the caller's segment order.)

## 4. What the original draw routine does (engine-relevant)

Routine at image offset 0x29AE of the unpacked `NV.OV1` (segment 0290, offset
00AE with load base 0), reached through the AdvBIOS software-interrupt
dispatcher at 0x292A. Details of AdvBIOS belong to its own document; only the
picture semantics are listed here. All **[V: code]**, and the first three
points additionally **[V: emulation]**.

- The file is first loaded whole to `DS:0454` (DS = 04E9); the routine gets a
  16-byte parameter block: four plane segments, `x` (in bytes) and `y`
  overrides, a mode word and a flag word.
- Position: if the parameter `x` is 0xFFFF the picture goes to the file's
  `(x >> 3, y)`; otherwise the caller's position replaces both. Pictures are
  always byte-aligned horizontally.
- Mode 0 = opaque: every byte of the rectangle is overwritten in all four
  planes. Mode != 0 = **colour 0 is transparent**: a mask (OR of the four plane
  bytes) is built per byte and only non-zero pixels are written (routine
  0x2A92/0x2B20/0x2B38). Checked under emulation on `NV19`, `NV28B`, `NVWIN`
  drawn over an all-colour-15 screen.
- Flag bit 0: copy the file's 16 palette words to the working palette at
  `DS:0022`. Flag bit 1: program the DAC from the working palette through one
  of 16 brightness tables (current fade level at `DS:0042`; table at
  `CS:049C + 16 * level`). So a picture can be drawn without touching the
  palette, and the palette can be taken without being shown yet.
- A second, near-identical unpack/XOR pair exists at image 0x300E/0x305C with
  its own row buffer; it serves another AdvBIOS function (blits via an
  intermediate buffer, 0x2FCC). Not analysed here. **[?]**

## 5. Pi files of the Windows release

### 5.1 Variant

Standard 16-colour Pi, big-endian header: **[V]** unless marked.

```
"Pi"
comment bytes ... 0x1A
dummy comment bytes ... 0x00
u8  mode            = 0 in all 123 files
u8  aspect x, y     = 0, 0
u8  planes          = 4
4   saver id        = "PC98" (96 files) or "MG  " (27 files)
u16 n, n bytes      saver-specific data: empty, or 5 bytes (32 files)
u16 width, u16 height
48  palette, 16 x (R, G, B) bytes
... bit stream, MSB first
```

- Saver data, when present, is `01, u16 x, u16 y` (big-endian): the screen
  position of a cropped picture. Interpreting it this way makes all 32
  cropped PIs land exactly on the corresponding GPC pixels. **[V]** The meaning
  of the leading `01` is **[I]** (a tag for "position").
- `"PC98"` files are conversions of the PC-98 art (plus the Windows-only
  `AREA`, `HSS01/02`, `NV56A`): empty comment, palette bytes are `v << 4`
  (low nibble 0). `"MG  "` files (the new Windows art `NV99A`...,
  `NVOP01/02`, and the re-edited `ROGO`) have arbitrary 8-bit palette bytes;
  `ROGO.PI` alone has a comment (`User:KIN`, `MPS.EXE version 1.02`, plus a
  `-magFF0000` dummy field). **[V]**
- Compression is the textbook Pi scheme (per-colour move-to-front colour codes
  `1x / 00x / 010xx / 011xxx`, five position codes `00 / 01 / 10 / 110 / 111`
  = 2-or-4 back / one row up / two rows up / up-right / up-left, Elias-gamma
  style pair counts, the first two pixels virtually filling two rows above the
  picture). No deviations found. **[V]** by the pixel equality below. The
  stream is followed by 3-6 unused bytes.

### 5.2 GPC vs PI results (`re-tools/gpc_verify.py`)

| check | result |
|---|---|
| GPC contents decoded with the stream consumed to its last byte | 103 / 103 |
| original AdvBIOS decoder under Unicorn: 4 planes + palette buffer equal to `gpc.py` | 103 / 103 |
| GPCs with a same-named PI | 85 |
| ... identical rectangle and pixels | 49 |
| ... identical on screen, PI has a different rectangle (cropped to the non-zero bounding box, or uncropped) | 32 |
| ... real pixel differences | 4 |
| ... palette identical / different | 80 / 5 |
| A+B half-screen GPC pairs equal to the single full-screen PI | 9 / 9 (pixels and both palettes) |
| GPCs with no PI counterpart at all | 0 (the 18 "no PI" files are exactly those 9 pairs) |

"On screen" = both pictures placed at their own x,y on a 640x400 canvas of
colour 0. In all 32 cropped cases everything the GPC has outside the PI
rectangle is colour 0. **[V]**

The differences, all in the data rather than the decoder (the original code
produces the same GPC pixels) **[V]**:

| picture | difference |
|---|---|
| `NV10` | 1 stray pixel in the GPC at (617,399), colour 1; absent in the PI |
| `NV03E` | 1 stray pixel at (222,399), colour 1; absent in the PI |
| `NV03F` | 1 stray pixel at (639,366), colour 11; absent in the PI |
| `ROGO` | 311 pixels in 345,272-437,287: the copyright line "(C)1993" was redrawn as "(C)1993.1996"; palette entry 14 is 000 on PC-98 and (7,15,7) on Windows |
| `MAP1`-`MAP4` | pixels identical; palette entries 0 and 1 are (0,5,5) and (0,4,4) on PC-98 but black on Windows (as 0GRB words: 505, 404 vs 000, 000) |

### 5.3 Windows-only pictures (no GPC of that name)

`AREA`, `HSS01`, `HSS02`, `NV56A`, `NV99A`-`NV99R`, `NV99CPY`, `NV99SC1`,
`NV99SC2A/B/C`, `NV99SC3`, `NVOP01`, `NVOP02` (30 files), plus the nine merged
full screens `NV12 NV15 NV16 NV32 NV40 NV41 NV48 NV51 NV55`. All are 640x400.
**[V]** Whether the PC-98 version shows equivalent content by other means
(text-layer drawing, script effects) is outside this document. **[?]**

## 6. Observations for an engine

### 6.1 Kinds of pictures

- **Full-screen backgrounds / event CGs**: 640x400 at 0,0 that never use
  colour 0 (47 contents). **[V]**
- **Half-screen pairs** `NVxxA` (x = 0) + `NVxxB` (x = 320), 320x400 each,
  normally no colour 0: `NV12 NV15 NV16 NV32 NV40 NV41 NV48 NV51 NV55`. Both
  halves carry the same palette. Probably split because one 640x400 picture of
  that complexity would exceed the 63 488-byte file buffer (the halves are
  29-36 KB each) and/or to allow a two-step reveal. **[I]**
  - `NV32A` is 328 wide: its columns 320-327 duplicate columns 0-7 of `NV32B`
    exactly, so draw order does not matter. **[V]**
  - `NV51A/B` do contain colour 0 (30 % / 21 %). **[V]**
- **Overlays / sprites with a cropped rectangle** (character busts, windows,
  buttons): `NV19 NV19A NV20A NV20B NV27 NV28A NV28B NV35 NV35B NV36A NV36B
  NV43 NV43A(B) NV43B NV44A NV44B NV44Z NV49A NV52 NVWIN SAVE`. Rectangles are
  8-pixel aligned in x and padded with colour 0 around the art. **[V]**
- **Overlays stored on a full 640x400 canvas** (mostly colour 0): `NV03A`-`F`,
  `NV03ALL`, `NV06A`, `NV09`, `NV10`, `NV11`, `NV28C`, `NV43A(C)`, `MAPWIN`,
  `NV56`, `CP`. **[V]**
- **Palette carrier**: `OPPAL.GPC` is 16x13 pixels of colour 0 (2-byte stream)
  with a 16-step grey ramp 000, 111, ... FFF; it exists only for its palette.
  The Windows `OPPAL.PI` is an all-zero 640x400 picture with the same ramp.
  **[V]** (use by the opening is **[I]**)
- `BL.GPC` is a 640x400 picture entirely of colour 1 (black in its palette):
  a screen clear. **[V]**

### 6.2 Transparency

- Nothing in the file marks a transparent colour. **[V]**
- Evidence that **colour 0 is the transparent index**: (a) the original decoder
  has a masked mode that skips exactly colour 0 (section 4) **[V]**; (b) every
  overlay is padded with colour 0 and the Windows conversion cropped them to
  the bounding box of non-zero pixels **[V]**; (c) full-screen pictures avoid
  colour 0 altogether and use index 1 for black **[V]**.
- Whether a given picture is drawn masked or opaque is the caller's (script's)
  choice, not a property of the file. **[V: code]** Which script commands pick
  which mode is for the script documentation. **[?]**
- Palette entry 0 is 000 in 81 contents, but (0,4,4) / (0,5,5) (words 404 /
  505) in 19, (0,5,0) (word 500) in `NV33`/`NVWIN` and (0,8,7) (word 807) in
  `NV54` (triples are r,g,b). Since those pictures do not use pixel value 0, entry 0 there sets
  the colour of whatever is *not* covered by the picture (border / cleared
  screen / text plane background). **[I]**

### 6.3 Palettes

- Every GPC has its own full 16-entry palette; there are no palette-less
  files. **[V]** Overlays repeat the palette of the scene they belong to
  (e.g. `NV19A` = `NV19`, `NV20A/B` = `NV20`, `NV43A/B` = `NV43`), with some
  exceptions where a few entries differ from the base scene (e.g. `NV28A/B/C`
  vs `NV28`, `NV36A/B` vs `NV36`, `NV44A/B/Z` vs `NV44` entries 12-13). An
  engine must decide per draw whether the overlay's palette is applied (flag
  bit 0/1 in the original). **[V]** for the data, **[?]** for what the scripts
  do.
- Entries 1-5 are `000 204 638 A8D ECF` (black + a blue ramp) in 53 contents
  and the near-identical `000 304 638 A8D ECF` in 21; entry 15 is FFF in 95.
  These look like the fixed UI/text colours shared by all scenes, entries 6-14
  being per-scene. **[I]**
- Word-to-RGB: `r = (w >> 4) & 15, g = (w >> 8) & 15, b = w & 15`. **[V]**

### 6.4 `NV43A.GPC`: disk B vs disk C

Same picture, different packaging. **[V]**

| | disk B | disk C |
|---|---|---|
| file size | 21 597 | 22 831 |
| rectangle | 304x358 at 272,42 | 640x400 at 0,0 |
| interleave | 1 | 1 |
| palette | identical | identical |
| non-zero pixels | bounding box 279,49-570,399 | same box, same pixels |

Placed on a colour-0 canvas the two are pixel-identical (0 differing pixels),
and both equal `NV43A.PI` (292x351 at 279,49). The only functional difference:
drawn *opaque*, the disk C copy also clears the rest of the screen to colour 0,
while the disk B copy only touches its rectangle; drawn masked they behave the
same. Which one a script expects depends on the draw mode it uses. **[?]**

### 6.5 Practical notes

- A decoder needs no information beyond the file; it is safe to ignore the
  size fields, but they are consistent and can be used for validation. **[V]**
- Widths and x are multiples of 8 in all NOVA files, so the "pad the width to
  8" rule never shows. `gpc.py` crops to the stated width. **[I]** for
  non-multiple-of-8 files (none here).
- The original draws straight into VRAM row by row, so (with N > 1) a partly
  drawn picture is visible. A port that wants the look must reproduce the pass
  order of 3.3; otherwise decode off-screen and present at once. **[I]**

## 7. Picture table

Columns: `il` = row interleave step; `filters` = set of row filter bytes
occurring; palette notes show entry 0 and any deviation of entries 1-5 from
`000 204 638 A8D ECF` or of entry 15 from `FFF` (0GRB words; full palettes are
in `resources/derived/images/gpc/index.tsv`); last column = comparison with the
Windows PI (section 5.2). One row per distinct content. All rows **[V]**; all
103 also match the original decoder under emulation.

| name | disks | WxH | x,y | il | filters | palette notes | kind | vs Windows PI |
|---|---|---|---|---|---|---|---|---|
| BL | A | 640x400 | 0,0 | 1 | 0,1 | 0=000 | full-screen | identical |
| CP | A | 640x400 | 0,0 | 1 | 0,1 | 0=000; 1-5=00C 0F0 0CC C00 C0C | overlay on full canvas (5% colour 0) | identical |
| MAP1 | BC | 640x400 | 0,0 | 16 | 0,1,2,4 | 0=505; 1-5=404 C3C BE2 535 DAD; 15=FFE | full-screen | identical; palette differs |
| MAP2 | BC | 640x400 | 0,0 | 16 | 0,1,2 | 0=505; 1-5=404 C3C BE2 535 DAD; 15=FFE | full-screen | identical; palette differs |
| MAP3 | B | 640x400 | 0,0 | 16 | 0,1,2 | 0=505; 1-5=404 C3C BE2 535 DAD; 15=FFE | full-screen | identical; palette differs |
| MAP4 | B | 640x400 | 0,0 | 16 | 0,1,2 | 0=505; 1-5=404 C3C BE2 535 DAD; 15=FFE | full-screen | identical; palette differs |
| MAPWIN | BC | 640x400 | 0,0 | 1 | 0,1 | 0=000; 1-5=404 C3C BE2 535 DAD; 15=FFE | overlay on full canvas (85% colour 0) | identical |
| NV00 | AD | 640x400 | 0,0 | 2 | 0,1 | 0=000 | full-screen | identical |
| NV01 | A | 640x400 | 0,0 | 2 | 0,1 | 0=000 | full-screen | identical |
| NV01L | A | 640x400 | 0,0 | 2 | 0,1 | 0=000 | full-screen | identical |
| NV02 | A | 640x400 | 0,0 | 2 | 0,1 | 0=000 | full-screen | identical |
| NV03 | BCD | 640x400 | 0,0 | 2 | 0,1,2 | 0=000 | full-screen | identical |
| NV03A | B | 640x400 | 0,0 | 1 | 0 | 0=000 | overlay on full canvas (97% colour 0) | same on screen (PI 103x136@457,229) |
| NV03ALL | B | 640x400 | 0,0 | 1 | 0 | 0=000 | overlay on full canvas (82% colour 0) | same on screen (PI 575x319@65,81) |
| NV03B | B | 640x400 | 0,0 | 1 | 0 | 0=000 | overlay on full canvas (98% colour 0) | same on screen (PI 50x185@424,103) |
| NV03C | B | 640x400 | 0,0 | 1 | 0 | 0=000 | overlay on full canvas (96% colour 0) | same on screen (PI 165x113@452,287) |
| NV03D | B | 640x400 | 0,0 | 1 | 0 | 0=000 | overlay on full canvas (96% colour 0) | same on screen (PI 124x143@172,231) |
| NV03E | B | 640x400 | 0,0 | 1 | 0 | 0=000 | overlay on full canvas (96% colour 0) | 1 px differ |
| NV03F | B | 640x400 | 0,0 | 2 | 0 | 0=000 | overlay on full canvas (96% colour 0) | 1 px differ |
| NV04 | A | 640x400 | 0,0 | 2 | 0,1 | 0=505 | full-screen | identical |
| NV05 | A | 640x400 | 0,0 | 2 | 0,1 | 0=505 | full-screen | identical |
| NV06 | A | 640x400 | 0,0 | 2 | 0,1 | 0=505 | full-screen | identical |
| NV06A | A | 640x400 | 0,0 | 2 | 0,1 | 0=505 | overlay on full canvas (86% colour 0) | same on screen (PI 320x400@320,0) |
| NV07 | A | 640x400 | 0,0 | 2 | 0,3 | 0=000 | full-screen | identical |
| NV08 | A | 640x400 | 0,0 | 2 | 0,1,2,3,4 | 0=505 | full-screen | identical |
| NV09 | A | 640x400 | 0,0 | 2 | 0,1 | 0=000; 1-5=010 204 638 A8D ECF | overlay on full canvas (68% colour 0) | same on screen (PI 400x370@200,30) |
| NV10 | A | 640x400 | 0,0 | 2 | 0,1 | 0=000 | overlay on full canvas (57% colour 0) | 1 px differ |
| NV11 | AD | 640x400 | 0,0 | 2 | 0,1 | 0=000 | overlay on full canvas (68% colour 0) | same on screen (PI 345x400@250,0) |
| NV12A | D | 320x400 | 0,0 | 2 | 0,1,2,5,9,12,14 | 0=404 | half-screen (left) | A+B = NV12.PI |
| NV12B | D | 320x400 | 320,0 | 4 | 0,1 | 0=404 | half-screen (right) | A+B = NV12.PI |
| NV13 | D | 640x400 | 0,0 | 2 | 0,1 | 0=404; 1-5=000 CCD 638 A8D 494 | full-screen | identical |
| NV14 | D | 640x400 | 0,0 | 2 | 0,1 | 0=000 | full-screen | identical |
| NV15A | D | 320x400 | 0,0 | 2 | 0,1 | 0=404; 1-5=000 204 250 A8D 491 | half-screen (left) | A+B = NV15.PI |
| NV15B | D | 320x400 | 320,0 | 2 | 0,1 | 0=404; 1-5=000 204 250 A8D 491 | half-screen (right) | A+B = NV15.PI |
| NV16A | C | 320x400 | 0,0 | 2 | 0,1 | 0=000; 1-5=000 879 483 A8D ECF | half-screen (left) | A+B = NV16.PI |
| NV16B | C | 320x400 | 320,0 | 2 | 0,1,2,3 | 0=000; 1-5=000 879 483 A8D ECF | half-screen (right) | A+B = NV16.PI |
| NV17 | C | 640x400 | 0,0 | 2 | 0,1 | 0=000 | full-screen | identical |
| NV18 | CD | 640x400 | 0,0 | 2 | 0,1 | 0=000 | full-screen | identical |
| NV19 | A | 304x387 | 272,13 | 2 | 0,1 | 0=000 | overlay, cropped (47% colour 0) | same on screen (PI 283x374@282,26) |
| NV19A | B | 136x122 | 344,101 | 1 | 0 | 0=000 | overlay, cropped (46% colour 0) | same on screen (PI 115x111@356,108) |
| NV20 | B | 640x400 | 0,0 | 2 | 0,1 | 0=000; 1-5=000 304 638 A8D ECF | full-screen | identical |
| NV20A | B | 168x129 | 80,165 | 1 | 0 | 0=000; 1-5=000 304 638 A8D ECF | overlay, cropped (72% colour 0) | same on screen (PI 640x400@0,0) |
| NV20B | B | 400x316 | 80,37 | 1 | 0,1 | 0=000; 1-5=000 304 638 A8D ECF | overlay, cropped (74% colour 0) | same on screen (PI 355x291@89,54) |
| NV21 | B | 640x400 | 0,0 | 2 | 0,1 | 0=000; 1-5=000 304 638 A8D ECF | full-screen | identical |
| NV22 | D | 640x400 | 0,0 | 2 | 0,1,2 | 0=000; 1-5=000 304 638 A8D ECF | full-screen | identical |
| NV23 | C | 640x400 | 0,0 | 2 | 0,1 | 0=000; 1-5=000 204 638 A8D F7B | full-screen | identical |
| NV24 | C | 640x400 | 0,0 | 2 | 0,1 | 0=000 | full-screen | identical |
| NV25 | CD | 640x400 | 0,0 | 2 | 0,1 | 0=000; 1-5=000 304 638 A8D ECF | full-screen | identical |
| NV26 | CD | 640x400 | 0,0 | 1 | 0,1 | 0=000 | full-screen | identical |
| NV27 | A | 304x392 | 200,8 | 2 | 0,1 | 0=000 | overlay, cropped (42% colour 0) | same on screen (PI 294x373@208,27) |
| NV28 | B | 640x400 | 0,0 | 2 | 0,1 | 0=000; 1-5=000 304 638 A8D ECF | full-screen | identical |
| NV28A | B | 384x365 | 32,35 | 1 | 0 | 0=000; 1-5=000 304 638 A8D ECF | overlay, cropped (54% colour 0) | same on screen (PI 365x339@42,61) |
| NV28B | B | 216x339 | 152,61 | 2 | 0 | 0=000; 1-5=000 304 638 A8D ECF | overlay, cropped (63% colour 0) | same on screen (PI 193x328@168,72) |
| NV28C | B | 640x400 | 0,0 | 2 | 0 | 0=000; 1-5=000 304 638 A8D ECF | overlay on full canvas (80% colour 0) | same on screen (PI 348x333@45,67) |
| NV29 | B | 640x400 | 0,0 | 2 | 0,1 | 0=000 | full-screen | identical |
| NV30 | D | 640x400 | 0,0 | 2 | 0,1 | 0=000; 1-5=000 304 638 A8D ECF | full-screen | identical |
| NV31 | CD | 640x400 | 0,0 | 2 | 0,1 | 0=000 | full-screen | identical |
| NV32A | C | 328x400 | 0,0 | 1 | 0,1,2 | 0=000; 1-5=000 304 638 A8D ECF | half-screen (left) | A+B = NV32.PI |
| NV32B | C | 320x400 | 320,0 | 1 | 0,1 | 0=000; 1-5=000 304 638 A8D ECF | half-screen (right) | A+B = NV32.PI |
| NV33 | BC | 640x400 | 0,0 | 2 | 0,1 | 0=500; 1-5=000 889 CCD A8D ECF | full-screen | identical |
| NV34 | D | 640x400 | 0,0 | 2 | 0,1 | 0=000 | full-screen | identical |
| NV35 | A | 400x400 | 24,0 | 1 | 0 | 0=000 | overlay, cropped (49% colour 0) | same on screen (PI 370x396@45,4) |
| NV35B | B | 152x160 | 168,73 | 1 | 0,1 | 0=000 | overlay, cropped (37% colour 0) | same on screen (PI 144x141@173,83) |
| NV36 | B | 640x400 | 0,0 | 2 | 0,1 | 0=000 | full-screen | identical |
| NV36A | B | 336x351 | 280,49 | 1 | 0 | 0=000 | overlay, cropped (51% colour 0) | same on screen (PI 317x315@293,85) |
| NV36B | B | 640x336 | 0,64 | 2 | 0 | 0=000 | overlay, cropped (55% colour 0) | same on screen (PI 640x322@0,78) |
| NV37 | B | 640x400 | 0,0 | 2 | 0,1 | 0=404 | full-screen | identical |
| NV38 | D | 640x400 | 0,0 | 2 | 0,1 | 0=000; 1-5=000 304 638 A8D ECF | full-screen | identical |
| NV39 | D | 640x400 | 0,0 | 2 | 0,1 | 0=404; 1-5=000 204 638 A8D 491 | full-screen | identical |
| NV40A | CD | 320x400 | 0,0 | 2 | 0,1 | 0=000; 1-5=000 778 638 A8D ECF | half-screen (left) | A+B = NV40.PI |
| NV40B | CD | 320x400 | 320,0 | 2 | 0 | 0=000; 1-5=000 778 638 A8D ECF | half-screen (right) | A+B = NV40.PI |
| NV41A | C | 320x400 | 0,0 | 2 | 0,1 | 0=000 | half-screen (left) | A+B = NV41.PI |
| NV41B | C | 320x400 | 320,0 | 2 | 0,1 | 0=000 | half-screen (right) | A+B = NV41.PI |
| NV42 | CD | 640x400 | 0,0 | 2 | 0,1 | 0=000; 1-5=000 304 638 A8D ECF | full-screen | identical |
| NV43 | A | 336x368 | 232,32 | 1 | 0 | 0=000 | overlay, cropped (42% colour 0) | same on screen (PI 314x360@241,40) |
| NV43A | B | 304x358 | 272,42 | 1 | 0 | 0=000 | overlay, cropped (37% colour 0) | same on screen (PI 292x351@279,49) |
| NV43A | C | 640x400 | 0,0 | 1 | 0 | 0=000 | overlay on full canvas (73% colour 0) | same on screen (PI 292x351@279,49) |
| NV43B | B | 304x366 | 248,34 | 1 | 0 | 0=000 | overlay, cropped (36% colour 0) | same on screen (PI 288x360@257,40) |
| NV44 | B | 640x400 | 0,0 | 2 | 0,1 | 0=000; 1-5=000 463 9C7 A8D 3C3 | full-screen | identical |
| NV44A | B | 232x207 | 104,123 | 2 | 0,1 | 0=000; 1-5=000 463 9C7 A8D 3C3 | overlay, cropped (58% colour 0) | same on screen (PI 218x205@111,123) |
| NV44B | B | 88x223 | 552,124 | 2 | 0 | 0=000; 1-5=000 463 9C7 A8D 3C3 | overlay, cropped (67% colour 0) | same on screen (PI 81x209@559,130) |
| NV44Z | B | 96x114 | 544,224 | 2 | 0,1 | 0=000; 1-5=000 463 9C7 A8D 3C3 | overlay, cropped (1% colour 0) | same on screen (PI 95x114@545,224) |
| NV45 | B | 640x400 | 0,0 | 1 | 0,1 | 0=000 | full-screen | identical |
| NV46 | D | 640x400 | 0,0 | 2 | 0,1 | 0=404 | full-screen | identical |
| NV47 | D | 640x400 | 0,0 | 2 | 0,1 | 0=404 | full-screen | identical |
| NV48A | C | 320x400 | 0,0 | 2 | 0,1 | 0=000 | half-screen (left) | A+B = NV48.PI |
| NV48B | C | 320x400 | 320,0 | 2 | 0,1 | 0=000 | half-screen (right) | A+B = NV48.PI |
| NV49 | BD | 640x400 | 0,0 | 2 | 0,1 | 0=000; 1-5=000 204 638 A8D DDE | full-screen | identical |
| NV49A | BD | 440x351 | 56,49 | 2 | 0,1 | 0=000; 1-5=000 204 638 A8D DDE | overlay, cropped (70% colour 0) | same on screen (PI 414x338@70,62) |
| NV50 | D | 640x400 | 0,0 | 4 | 0,1 | 0=404 | full-screen | identical |
| NV51A | C | 320x400 | 0,0 | 2 | 0 | 0=000; 1-5=000 304 638 A8D ECF | half-screen (left), 30% colour 0 | A+B = NV51.PI |
| NV51B | C | 320x400 | 320,0 | 2 | 0 | 0=000; 1-5=000 304 638 A8D ECF | half-screen (right), 20% colour 0 | A+B = NV51.PI |
| NV52 | B | 448x388 | 160,12 | 2 | 0 | 0=000 | overlay, cropped (44% colour 0) | same on screen (PI 420x374@169,26) |
| NV53 | B | 640x400 | 0,0 | 1 | 0,1 | 0=000; 1-5=000 304 638 A8D ECF | full-screen | identical |
| NV54 | B | 640x400 | 0,0 | 1 | 0,1 | 0=807; 1-5=000 304 638 A8D ECF | full-screen | identical |
| NV55A | B | 320x400 | 0,0 | 2 | 0,1 | 0=000; 1-5=000 322 252 ACA AA9; 15=DDD | half-screen (left) | A+B = NV55.PI |
| NV55B | B | 320x400 | 320,0 | 2 | 0,1 | 0=000; 1-5=000 322 252 ACA AA9; 15=DDD | half-screen (right) | A+B = NV55.PI |
| NV56 | B | 640x400 | 0,0 | 2 | 0,1 | 0=000; 1-5=000 304 638 A8D ECF | overlay on full canvas (53% colour 0) | identical |
| NV99 | BCD | 640x400 | 0,0 | 2 | 0,1 | 0=000; 1-5=000 322 061 A8D 5D5 | full-screen | identical |
| NVWIN | A | 528x103 | 56,297 | 2 | 0,1 | 0=500; 1-5=000 304 638 A8D ECF | overlay, cropped (50% colour 0) | same on screen (PI 527x103@57,297) |
| OPPAL | A | 16x13 | 0,0 | 1 | 0 | 0=000; 1-5=111 222 333 444 555 | palette carrier (all colour 0) | same on screen (PI 640x400@0,0) |
| ROGO | B | 640x400 | 0,0 | 2 | 0,1 | 0=000; 1-5=000 322 061 092 5D5 | full-screen | 311 px differ; palette differs |
| SAVE | B | 144x37 | 480,225 | 1 | 0,1 | 0=000; 1-5=404 C3C BE2 535 DAD; 15=FFE | overlay, cropped (18% colour 0) | same on screen (PI 132x33@485,227) |

## 8. Open questions

1. Meaning of the `"n*bys"` tag after the palette and of the always-zero words
   at header 0x1C / 0x24 and image +0x0E. None is read by the draw routine.
2. Whether image +4 is really a u32 (high word always 0 here).
3. Which AdvBIOS function numbers / script commands select opaque vs masked
   drawing, position override and the two palette flags (to be settled by the
   AdvBIOS and script documentation); in particular how `NV43A` is used on
   disk B vs disk C, and whether overlay palettes are applied.
4. Purpose of the second unpack/XOR routine pair at image 0x300E/0x305C
   (off-screen decode? partial redraw?).
5. Purpose of palette entry 0 in pictures that never use colour 0 (border /
   background colour is a guess).
6. How the PC-98 version presents what the Windows release has as the 30
   Windows-only pictures (`NV99A`-`R`, `NVOP01/02`, `AREA`, `HSS01/02`, ...).
7. GPA (animation) files are not used by NOVA's disks (no `PC98)GPAFILE`
   files found under `GPC/`); not covered.

## 9. Reproducing

```
python3 -I source/tools/gpc.py info resources/original/pc98/*/GPC/*.GPC
python3 -I source/tools/gpc.py png  resources/original/pc98/*/GPC/*.GPC \
        -o resources/derived/images/gpc --disk-prefix
python3 -I re-tools/pi.py png resources/original/win/*.PI -o resources/derived/images/pi
$EMU_PYTHON -I re-tools/gpc_verify.py --tsv resources/derived/images/gpc_verify.tsv
```

`gpc_verify.py` also runs under a bare `python3 -I`; it then skips the Unicorn
witness and says so.
