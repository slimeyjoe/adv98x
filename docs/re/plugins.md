# The machine-code plug-ins (`*.TCM`)

NOVA's scripts load five small pieces of 16-bit code with `load-mem` and call them with `exec-mem`
([interpreter.md](interpreter.md) §6). This document says what each one does, precisely enough to
replace it by a native module of the new engine.

| file | bytes | loaded at | NOVA calls | job |
|---|---|---|---|---|
| `CHGFONTH.TCM` | 16 | 8448 (0x2100) | `exec-mem 8448 1` in 112 scripts | bold text on/off |
| `PALCH.TCM` | 596 | 8704 (0x2200) | `exec-mem 8704 14 11 9 10 6` (S010, S010A, S010B) | set one palette colour, at once or gliding |
| `WHITEH.TCM` | 740 | 5376 (0x1500) | `exec-mem 5376 1 8` (MON01; `0 8` is defined there but never called) | whole-palette fade to / from white |
| `INPUTNAM.TCM` | 870 | 9984 (0x2700) | `exec-mem 9984 0 0 4 28 218 "カイル" 15 0` (MODE, 3 places) | keyboard name entry, writes `A:\NAME.DEF` |
| `ACTE1.TCM` | 4264 | 256 (0x0100) | `"INIT"`, `"GET n x y w h"`, `"PUT n x y ,FREE n"` (111 scripts) | screen-rectangle save/restore and more ("ACTE Spec1 Rel.8 1992/10/27 MD.dan Ides'") |

**How this was established.** Every plug-in was read completely in disassembly (names:
[listing/tcm-names.tsv](listing/tcm-names.tsv); regenerate the annotated listings with
`re-tools/tcmtool.py list`, they go to `resources/derived/listing/tcm-*.lst`). Each was also run under
unicorn with AdvBIOS, DOS and the hardware stubbed (`re-tools/tcmtool.py run FILE LOAD ARG…`, which prints
every interrupt call and port access). Statements below are marked

* **[E]** confirmed by such a run (and agreeing with the reading),
* **[R]** from reading the code only,
* **[I]** inferred (depends on hardware or on code outside the plug-in).

The emulation has no real clock: it counts VSYNC interrupts and VSYNC polls, so all *frame counts* are
[E] but all conversions to seconds are [I] (56.4 Hz, the 24 kHz PC-98 frame rate assumed in
[advbios.md](advbios.md) §7).

## 1. Common mechanics

**Call.** `exec-mem addr args…` near-calls DS:addr with DS = ES = the interpreter's segment, SI → the
argument block (word count, then one word per argument; a string argument is the address of its opening
`"` in the script), BX, DX, CX = the first three arguments.

**Entry stub** (PALCH, WHITEH, ACTE1; INPUTNAM has a variant, CHGFONTH none) [E]: the stub finds its own
load offset (`call $+3; pop`), turns the near return address into a far one (`pop ax; push cs; push ax`),
and far-jumps to *interpreter segment + offset/16* : *start of the real code*, so that the code sees itself
at offset 0 of its own CS and addresses its data as `cs:[file offset]`. DS is left alone (it still points
to the interpreter, which is how the arguments and script strings are read). PALCH, WHITEH and ACTE1
return at once, doing nothing, if the load offset is not a multiple of 16 (`exec-mem 8705 …` under
emulation: no call, CH = FFh). INPUTNAM does not check.

**Result.** All five return **CH = FFh**, which the interpreter treats as "no result": no flag and no
variable is ever changed by a plug-in [E]. AL/CL are garbage.

**Memory.** Each image uses a few bytes beyond the end of its file as uninitialised work area:

| plug-in | occupies (interpreter segment) | state that must survive between calls |
|---|---|---|
| CHGFONTH | 0x2100–0x210F | none |
| PALCH | 0x2200–0x2466 (file 0x254 + 0x13) | none (everything is re-initialised per call) |
| WHITEH | 0x1500–0x1863 (file 0x2E4 + 0x80) | none |
| INPUTNAM | 0x2700–0x2BA5 (file 0x366; buffers up to 0x39A + name + 256) | none |
| ACTE1 | 0x0100–0x11B9 (file 0x10A8 + 0x12) | **yes**: slot-table segment, error flag, page/overlay/view settings live in the image; the saved rectangles live in DOS memory blocks |

So a native replacement needs per-instance state only for ACTE1. Reloading a file (`load-mem`) resets
that plug-in's in-image state to the file's contents — significant for ACTE1 (§6.5).

## 2. CHGFONTH — bold text switch

Sixteen bytes, no stub [E]:

```
AL = (argument count & FFh) ? (arg1 & 1) : 0
INT F6h AH=13h          ; AdvBIOS: bold off (0) / on (1)
CH = FFh ; near return
```

* `exec-mem 8448 1` → bold on; even numbers or no argument → bold off; only bit 0 of the first argument
  counts (3 → on, 2 → off) [E].
* A string argument would be taken as its address (bit 0 of it). Nothing else is touched.
* Bold is AdvBIOS state (advbios.md §4.2 AH=13h, §5.2); it stays on until changed.

## 3. PALCH — change one palette colour

### 3.1 Arguments

`exec-mem addr index c0 c1 c2 [speed]`

| argument | range | meaning |
|---|---|---|
| index | 0..15 | palette entry |
| c0 | 0..15 | **blue** (bits 3–0 of the 0GRB word) |
| c1 | 0..15 | **red** (bits 7–4) |
| c2 | 0..15 | **green** (bits 11–8) |
| speed | 0..255 | optional; its presence selects the glide; VSYNCs per step |

The colour word is `c2<<8 | c1<<4 | c0` [E] — so the argument order is **blue, red, green**. NOVA's
`14 11 9 10 6` is: colour 14 → `A9B` (G=10, R=9, B=11), speed 6.

Errors: fewer than 4 arguments, index or a component > 15, speed > 255 → nothing is drawn or changed
(the interrupt hooks of §3.4 are still installed and removed) [E]. Arguments after the fifth are ignored.

### 3.2 Four arguments: set at once [E]

`INT F3h AH=15h, AL=index, BX=colour, CL=0Fh`: store the entry in AdvBIOS's palette buffer and program
that hardware colour immediately with brightness row 15 (i.e. unscaled, whatever the current brightness
is; the stored brightness is not changed). No wait.

### 3.3 Five arguments: glide in 15 steps [E]

```
cur = INT F3h AH=16h (AL=index) → BX            ; current entry of the palette buffer
for each component i in (blue, red, green):
    d[i]    = |target[i] − cur[i]|
    step[i] = d[i] + 1                           ; 1..16
    acc[i]  = 0
repeat 15 times:
    for each component:
        acc += step
        if acc ≥ 16: acc −= 16; cur += (target ≥ start ? +1 : −1)
    wait `speed` VSYNC interrupts                ; speed 0: no wait
    INT F3h AH=15h, AL=index, BX=cur, CL=0Fh
```

Closed form (checked against 40 random emulated runs): after step k (1..15) a component is
`start ± floor(k·(d+1)/16)`. After step 15 that is exactly the target. All 15 colours are written even
when they repeat. NOVA's call with colour 14 = `3C5` before gives
`3C5 4C5 4C6 5B6 5B7 6B7 6B8 7A8 7A8 8A9 8A9 99A 99A A9B A9B`.

Timing: each step waits for `speed` increments of a counter driven by the VSYNC interrupt, then writes.
The first wait can be up to one frame short. Total = 15·speed frames; NOVA: 90 frames ≈ 1.6 s [I]. The
call blocks; no input is read, nothing can skip it, no animation or quit check runs.

### 3.4 Side effects [R, partly E]

* While it runs, PALCH owns INT 0Ah (VSYNC, IRQ2): its handler counts, sends EOI, re-arms the interrupt
  (`out 64h`) and does **not** chain. It also wraps INT 18h (PC-98 keyboard/CRT BIOS) so that the VSYNC
  request is re-armed after every BIOS call [I: purpose]. Both vectors are restored on exit.
* On exit it masks IRQ2 unconditionally (`in 02h; or 4; out 02h`) rather than restoring the old mask.
  AdvBIOS only polls VSYNC (advbios.md §7), so this is harmless in NOVA.
* The palette buffer entry ends at the target colour. Brightness is untouched.

## 4. WHITEH — fade the whole palette to / from white

### 4.1 Arguments

`exec-mem addr mode speed`

| mode | action |
|---|---|
| 0 | **from white**: start at all-`FFF`, end at the 16 words in the *mailbox* (below) |
| 1 | **to white**: start at the current palette buffer, end at all-`FFF` |
| 2 | mode 1, then mode 0 |

speed 0..255. Fewer than 2 arguments, mode > 2 or speed > 255 → nothing (hooks installed and removed) [E].

This is the opposite of what the numbers suggest at first sight: NOVA's only executed call,
`exec-mem 5376 1 8` in MON01 (procedure 8, followed by `text-clear 15`), is a fade **to** white [E].
MON01 also defines procedure 7 = `exec-mem 5376 0 8` but never calls it.

The *mailbox* is the 16-word buffer whose address `INT F3h AH=FFh` returns (0290:045C, advbios.md §4.3).
Nothing in NOVA's `NV.OVL`, `NV.OV1` or the other plug-ins calls that service, and AdvBIOS never writes
the buffer, so in NOVA it holds 16 zero words: mode 0 would fade white → black, and mode 2 would flash to
white and then go to black [R; who is meant to fill the mailbox is an open question].

### 4.2 Arithmetic [E]

Per colour and component v (0..15) of the reference palette (mode 1: the current palette; mode 0: the
mailbox): `step = 16 − v` (1..16), `acc = 0`. Each of the 15 steps does `acc += step`; on reaching 16,
`acc −= 16` and the working component moves by one (mode 1: up from v; mode 0: down from 15).

Closed form (checked against 40 emulated runs with random palettes), after step k = 1..15:

* mode 1: `v + floor(k·(16 − v)/16)` → 15 at k = 15
* mode 0: `15 − floor(k·(16 − v)/16)` → v at k = 15

Example, mode 1 on the default palette entry `007`: `117 228 338 449 559 66A 77A 88B 99C AAC BBD CCD DDE
EEE FFF`. In mode 2 the accumulators are cleared between the two halves.

Each step's 16 words are sent with `INT F3h AH=13h, AL=0Fh, DS:SI=palette`: replace the palette buffer,
**set brightness to 15**, wait for the next VSYNC (inside AdvBIOS) and program all 16 hardware colours.

### 4.3 Timing

Let s = the speed argument. [E for the counts, I for the mapping to frames]

* s = 0: no intermediate steps at all — one palette write with the final state.
* s ≥ 1: 15 palette writes; before each, WHITEH waits s − 1 VSYNC interrupts, and AdvBIOS's AH=13h then
  waits for the start of the next VSYNC. Since the interrupt arrives at VSYNC start, that is **s frames
  per step**, 15·s in total. NOVA: s = 8 → 120 frames ≈ 2.1 s.
* Mode 2: the stored speed is decremented once per half, so the second half runs at s − 1 frames per
  step (and is a single jump when s = 1).

Blocking, no input, not skippable.

### 4.4 Side effects [R, partly E]

* INT 0Ah hooked while running (this handler *does* chain to the previous one), INT 18h wrapped as in
  PALCH; vectors and the interrupt mask are restored exactly.
* Afterwards the AdvBIOS palette buffer holds the final palette (mode 1: all white) and the brightness
  is 15 regardless of what it was. The old palette is not kept anywhere; the script must load a new one.

## 5. INPUTNAM — name entry

### 5.1 Arguments

`exec-mem addr a b maxlen x y ["default" [colour [background]]]`

| # | NOVA | meaning |
|---|---|---|
| 1, 2 | 0, 0 | read and ignored [R] |
| 3 | 4 | maximum number of characters; 0 or > 6 → 6 |
| 4 | 28 | x of the field, in byte columns (8 px); if x + 2·maxlen > 79 it becomes 80 − 2·maxlen |
| 5 | 218 | y of the field in pixel lines; > 383 → 383 |
| 6 | `"カイル"` | default name: the bytes between the quotes, copied as they are (Shift-JIS in the script: 83 4A 83 43 83 8B). No length check — the buffer is 16 bytes [R] |
| 7 | 15 | text colour (& 15); default 15 |
| 8 | 0 | background colour (& 15); default 0 |

Nothing happens (immediate return) if there are fewer than 5 arguments or AdvBIOS is older than 0.53
(`INT F1h AH=00h` must return BH = 0 and AH ≥ 35h or AL ≠ 0) [E for the argument count, R for the
version test].

### 5.2 Screen

The field is a row of 16×16-pixel cells: cell *i* covers columns x+2i .. x+2i+1, lines y .. y+15. Drawing
a character into a cell [E]:

1. `INT F6h AH=0Dh` fill rectangle (x+2i, y, x+2i+1, y+15) with the background colour,
2. `INT F6h AH=05h` cursor to (x+2i, y), `AH=03h` text colour, `AH=09h` draw the character (so the
   current AdvBIOS text settings apply, including bold from CHGFONTH).

The plug-in draws only: the typed characters in cells 0..count−1 and the cursor `▼` (Shift-JIS 81A5) in
cell *count* — which is cell *maxlen*, one past the last character, when the field is full. Nothing else:
no frame, no prompt, and **the default name is never displayed**. (NOVA's script prints the prompt and
`－－－－` at column 28, line 228 itself; the cells overlap the top 6 lines of those dashes.) On exit the
cursor cell is overwritten with a full-width space (8140) and the text colour that was current at entry
is restored (`AH=04h` / `AH=03h`). The AdvBIOS text cursor is left after the last cell drawn.

### 5.3 Keys [E]

Keys are read straight from the PC-98 BIOS: `INT 18h AH=01h` (sense) then `AH=00h` (blocking read); a key
is used only if the buffer was empty at the sense, otherwise it is thrown away — type-ahead is flushed.
The mouse is not read; there is no quit check and no animation while waiting.

| key | action |
|---|---|
| Return (scan code 1Ch) | finish — if nothing was typed and there is no default name, ignored |
| BS (0Eh), DEL (39h), ← (3Bh) | erase the last character (cursor cell cleared, cursor moves back) |
| `0`–`9`, `A`–`Z`, `a`–`z` (character code) | the full-width form: `０` 824F.., `Ａ` 8260.., `ａ` 8281.. |
| half-width kana A6h–DDh (keyboard in kana mode) | the **hiragana**: ｦ→を, ｧｨｩｪｫ→ぁぃぅぇぉ, ｬｭｮ→ゃゅょ, ｯ→っ, ｰ→ー (815B), ｱ…ﾝ→あ…ん |
| ﾞ (DEh) | previous character one of かきくけこ さしすせそ たちつてと はひふへほ → its voiced form (code + 1); otherwise ignored |
| ﾟ (DFh) | previous character one of はひふへほ → ぱぴぷぺぽ (code + 2); otherwise ignored |
| anything else (space, punctuation, A0h–A5h, ≥ E0h, function keys) | ignored |

A character key is ignored when *maxlen* characters are present. There is no romaji conversion, no
katakana, no kanji, no cursor movement inside the name.

### 5.4 Result: `A:\NAME.DEF` [E]

On Return the plug-in builds: the name — the typed characters, 2 bytes each, Shift-JIS, lead byte first;
or, if nothing was typed, the default string — followed by FFh bytes, and writes the first **256 bytes**:

```
INT F2h AX=0400h, DL=0          ; expect disk 0 in drive index 0 (prompts in floppy mode)
INT F2h AH=01h, DS:DX="A:\NAME.DEF", ES:BX=buffer, CX=256
```

repeating both calls until 256 bytes were written. Examples: typing `a ｶ ﾞ ﾊ ﾟ Z` →
`82 81 82 AA 82 CF 82 79 FF FF …` (ａがぱＺ); Return alone → `83 4A 83 43 83 8B FF FF …` (カイル). The
interpreter's `name-load`, which the script runs next, reads the file back (interpreter.md §5.2). The
plug-in returns nothing to the script.

## 6. ACTE1 — screen blocks, pages, images

### 6.1 Command string

`exec-mem 256 "command[,command…]"` — only the first argument is used and it must be a string [R: with
no argument or a number the plug-in parses whatever that word points to].

Parsing rules [E unless marked]:

* A command is recognised by its **first character only**, upper- or lower-case (`GET`, `get`, `Gxx` are
  the same). The rest of the word is skipped up to the next space, tab, `"` or `,`.
* Operands are unsigned decimal numbers separated by spaces/tabs; digits only (no sign, no hex), 16-bit
  wrap-around, a missing number is 0.
* After a command, blanks are skipped; a `,` continues with the next command, which must start
  **immediately** after the comma; anything else (normally the closing `"`) ends the string. So
  `"PUT 0 7 296 ,FREE 0"` runs both, `"GET 9 1 2 3 4, FREE 9"` runs only the GET.
* An unknown first letter ends the string silently (it is only counted, for the HALT screen). `EXIT` and
  `HALT` also end the string.
* Result: always CH = FFh.

Units everywhere: **x and w in byte columns (8 pixels), 0..79; y and h in pixel lines, 0..399**. All
four planes (A800, B000, B800, E000) are processed. Screen rows are 80 bytes apart.

### 6.2 Commands

"NOVA" marks the ones NOVA uses; all others are unused there.

| command | operands | action |
|---|---|---|
| **INIT** (NOVA) | – | clear the error flag; if a slot table exists, free all blocks and the table (as EXIT); allocate a new table of 64 empty slots (DOS `INT 21h AH=48h`, 32 paragraphs; a failure is not checked [R]); reset the per-command counters. Page, overlay and view settings are *not* reset |
| **GET** (NOVA) | n x y w h | save the rectangle into slot n: if the slot is in use its block is freed; a block of w·h·4 bytes is allocated from DOS; the four planes are copied into it one after the other (plane-sequential, row-major, w bytes per row). w·h must be < 16384 ("Oversize"). No clipping, no check of x/y/n (n > 63 corrupts memory [R]) |
| **PUT** (NOVA) | n x y | draw slot n with its top-left at (x, y), clipped to the view rectangle. n > 63 → error; empty slot → error "Accessed null pointer". The block stays allocated. Opaque mode: if the *show* and *acce* page numbers are equal, first wait for the start of the next VSYNC (port A0h bit 5), then copy. Overlay mode: pixels of colour 0 in the block leave the screen unchanged; done through a temporary DOS block; no VSYNC wait |
| **FREE** (NOVA) | n | free slot n's block and mark the slot empty; nothing if empty; n > 63 → error. Works even in the error state |
| SHOW | p | p = 0/1: remember as *show* page, wait for VSYNC start, `out A4h,p` (displayed page); else error |
| ACCE | p | p = 0/1: remember as *acce* page, `out A6h,p` (page mapped for drawing); else error |
| OVER | f | f ≠ 0: overlay (transparent) mode on; 0: off. Affects PUT, COPY, MOVE and LOAD |
| VIEW | x0 y0 x1 y1 | set the clipping rectangle for PUT (inclusive corners; initial 0 0 79 399). Error if x1 < x0, y1 < y0, x1 > 79 or y1 > 399 (the values are stored anyway) |
| COPY | sp x y w h dp x2 y2 | copy a rectangle from page sp at (x, y) to page dp at (x2, y2), through a temporary DOS block; overlay mode makes source colour 0 transparent. Pages ≤ 1, x ≤ 80, y ≤ 400, w·h < 16384, else error. No clipping, no VSYNC wait. **Leaves *acce* = dp** (port A6h too) |
| MOVE | x y w h x2 y2 | copy a rectangle within the current drawing page; rows top to bottom, bytes left to right, plane by plane (opaque) — overlapping moves down/right smear; overlay mode: source colour 0 transparent. x, x2 < 80, y, y2 < 400, w·h < 16384, else error. No clipping |
| WAIT | n | wait for n VSYNC starts (polled on port A0h); 0 = none |
| LOAD | file | load and draw a GPC picture: name = the next token (up to 40 characters; ends at blank, `,` or `"`); `INT F3h AH=00h` (buffer), `INT F2h AH=00h` (read file), `INT F3h AH=01h` with the block {A800, B000, B800, E000, x=FFFFh, y=FFFFh, transparent = overlay flag, flags = 3}: position from the file, into the current drawing page, the file's palette is copied to the palette buffer and programmed (advbios.md §5.3). A read error is not checked |
| EXIT | – | free all blocks and the slot table. No command except INIT is safe afterwards [R] |
| HALT | – | debugging screen on the PC-98 text layer (graphics display off meanwhile): the 64 slots (segment, w, h), state GREEN/ERROR, show/acce/over values, free DOS memory, per-command call counters; waits for input (`INT F1h AH=07h`), clears the text layer, graphics back on |

Emulation checks [E]: NOVA's five strings parse as listed (allocation sizes 29952 = 72·104·4 and
55200 = 69·200·4 bytes, FREE after PUT); GET → scribble → PUT restores exactly columns 7..78, lines
296..399 of all four planes of the current page and nothing else; PUT is clipped at the right/bottom
screen edge and by VIEW on the left/top (the matching part of the block is drawn); overlay PUT/MOVE/COPY
keep the destination where the source colour is 0; opaque PUT takes one VSYNC when show = acce and none
otherwise; SHOW/ACCE/COPY write ports A4h/A6h as described; LOAD passes the parameter block above, with
+0Ch = FFFFh after `OVER 1`.

### 6.3 Pages

ACTE1 never asks the system which page is displayed or mapped: its *show* and *acce* variables start at
0 and change only through SHOW, ACCE and COPY. GET, PUT, MOVE and LOAD simply use segments A800h… , i.e.
**whatever page the interpreter has selected for drawing at that moment**. As NOVA uses none of the page
commands, both variables stay 0, so every PUT in NOVA is preceded by a wait for VSYNC start
(≤ 1 frame ≈ 18 ms [I]) — whether or not the drawing page is actually visible.

### 6.4 Errors [E]

Wrong values produce a message on text line 23 — `ACTE] > CMD : text`, with texts "Accessed null
pointer", "Out of memory", "Oversize", "Overspec number nn" — with the graphics display switched off
(`INT 18h AH=41h`), wait for input (`INT F1h AH=07h`), then the text layer is cleared, graphics switched
back on (`AH=40h`) and the **error flag** set. While it is set, PUT, GET, COPY, MOVE and LOAD do nothing
and end the command string (so a following `,FREE n` is not executed either); only INIT clears it.

The error routine is defective: it pops one word more than it pushed. Where the caller had nothing on the
stack (bad numbers, oversize) execution happens to continue in the string loop with a wrong string
pointer; where the caller had saved registers (empty slot in PUT, out of memory in GET) the routine
returns to a garbage address — under emulation `"PUT 3 0 0"` on an empty slot jumps to offset = DS value
and runs wild. In practice any ACTE1 error is fatal for the game. NOVA's scripts never trigger one (every
PUT follows a GET of the same slot).

### 6.5 Memory behaviour worth knowing

* Saved rectangles are DOS memory blocks, one per slot, w·h·4 bytes (max 65532); the slot table (512
  bytes) is another. The interpreter shrinks its own block at start-up, so DOS has the memory.
* 111 scripts each do `load-mem "ACTE1.tcm" 256` followed by `"INIT"`. Reloading the file zeroes the
  table pointer inside the image, so that INIT cannot free the previous table: **every script change
  leaks the old 512-byte table** and any slot not yet FREEd [E: reload + INIT allocates a second table
  without freeing the first]. Functionally invisible (a new script starts
  with 64 empty slots) unless memory runs out, which would be the fatal "Out of memory" above.
* NOVA's use is strictly paired: procedure 0/2 = `GET s 7 296 72 104` (then the text window is drawn),
  procedure 1/3 = `PUT s 7 296 ,FREE s`, s = 0 or 1; one script uses `GET 0 0 160 69 200` /
  `PUT 0 0 160 ,FREE 0`. Rectangles in pixels: (56, 296) 576×104 and (0, 160) 552×200.

## 7. What a native replacement must do

A native module is selected by the file name given to `load-mem` (case-insensitive) and bound to the load
address; `exec-mem` on that address calls it with the argument list. None returns a result (flags and
variables stay untouched).

### 7.1 CHGFONTH

* NOVA and generic: `bold = argc ? arg1 & 1 : 0`. [E]

### 7.2 PALCH

* NOVA: `index, blue, red, green, speed` → glide palette entry *index* from its current value to the
  target in 15 steps with the arithmetic of §3.3, one step per `speed` frames (56.4 Hz [I]), blocking
  and unskippable; the entry is shown at full brightness regardless of the current brightness. [E]
* Generic: also the 4-argument immediate form; ignore the call if argc < 4, any of the four > 15, or
  speed > 255; speed 0 = all 15 writes without waiting (visually: jump). [E]

### 7.3 WHITEH

* NOVA: mode 1, speed 8: fade all 16 entries to `FFF` in 15 steps (§4.2), 8 frames per step, blocking;
  afterwards palette buffer = white and brightness = 15. [E; frames-per-step I]
* Generic: mode 0 (from white to the mailbox palette — provide the 16-word mailbox of INT F3h AH=FFh,
  zero-initialised), mode 2 (to white at s, back at s − 1 frames per step), speed 0 = single jump,
  ignore invalid arguments. [E]

### 7.4 INPUTNAM

* NOVA: field of 4 cells at column 28, line 218, colours 15 on 0; cursor `▼`; keys of §5.3 (a port may
  feed it from its own text input, mapping to the same Shift-JIS codes: full-width digits and letters,
  hiragana, `ー`); Return with nothing typed takes `カイル`; then write 256 bytes to `NAME.DEF` (name in
  Shift-JIS, FFh padding) — or store the same 26+ bytes wherever the engine's `name-load` reads them.
  The default name is not shown. [E]
* Generic: argument defaults and clamps of §5.1 (maxlen 1..6, x/y clamps, optional default and colours),
  the AdvBIOS version check is irrelevant natively. [E]

### 7.5 ACTE1

* NOVA: `INIT` (drop all slots, clear error), `GET n x y w h` (save a w·8 × h pixel rectangle of the
  current drawing page at (x·8, y) into slot n, replacing its content), `PUT n x y` (draw it back,
  opaque, clipped to the screen; then let one frame boundary pass), `FREE n`; slots 0 and 1; commands
  joined by `,`. Reloading the file followed by INIT must leave 64 empty slots. [E]
* Generic: the whole table of §6.2 — 64 slots, w·h < 16384, VIEW clipping (PUT only), OVER transparency
  (colour 0) for PUT/COPY/MOVE/LOAD, SHOW/ACCE/COPY page handling including "COPY leaves the drawing
  page at the destination", MOVE's forward copy order, WAIT in frames, LOAD of a GPC with its palette,
  first-letter command matching and the parsing rules of §6.1. Errors can be treated as fatal (they are
  in the original, §6.4); HALT is a debugging aid and can be a no-op. [E for behaviour listed in §6.2's
  emulation checks, R for the rest]

## 8. Open questions

1. **WHITEH's mailbox** (INT F3h AH=FFh buffer): no code in NOVA writes it. Is it filled by scripts or
   plug-ins of other Adv98V games, or by another AdvBIOS build (e.g. on image load)? Until known, mode 0
   and mode 2 end in black in a faithful implementation. NOVA never executes them.
2. **Real-time rates** rest on 56.4 Hz VSYNC and on the VSYNC interrupt arriving at the start of the
   pulse (which makes AdvBIOS's own wait in AH=13h a full extra frame per WHITEH step). Not measured on
   hardware or a cycle-accurate emulator.
3. **Why PALCH/WHITEH wrap INT 18h**: presumably a BIOS call can drop the pending VSYNC request; not
   verified against a BIOS listing. Irrelevant for a native module.
4. **Which page is the drawing page** when NOVA's procedures 0–3 run is the interpreter's business
   (interpreter.md / `screen-mode`); ACTE1 just uses it.
5. **INPUTNAM arguments 1 and 2** are ignored by this build (NOVA passes 0 0); their intended meaning is
   unknown.
6. ACTE1 behaviour after its own bugs (error path, GET with n > 63 or w/h = 0, COPY's out-of-memory
   path, EXIT without INIT) is undefined and was not characterised further.
