# NV.OVL — the Adv98V 1.70.54 script interpreter

`NV.OVL` is the generic Adv98V interpreter ("Adv for PC-9801V Version 1.70.54, Copyright(C) Tuneup
1991,93"). It contains no game logic: it reads `.MES` scripts and turns them into calls to AdvBIOS
(`NV.OV1`, [advbios.md](advbios.md)). The script format itself is in [mes-format.md](mes-format.md).

Conventions: addresses are offsets in the unpacked image (one 64 KB segment, CS = DS = ES; file
offset in the unpacked MZ = address + 0x200). **verified** = read in the code; **inferred** = strong
evidence, not proven. The unpacked file is made by `re-tools/exeunpack.py`; names are in
`listing/nvovl-names.tsv`.

## 1. Binary

| Item | Value |
|---|---|
| File | `NV.OVL`, 6 528 bytes on disk A, dated 1993-05-15 12:00 |
| Packing | three "TC0" encryption layers (keys 0001h, 0053h, 4321h; LCG ×2711h +3619h, XOR with bits 6..13), then Microsoft EXEPACK (**verified**: `exeunpack.py` reproduces a runnable image; method after Valley Bell's `adv98_dec`) |
| Unpacked | MZ, no relocations, image 61 056 bytes (0xEE80), CS:IP 0000:0000, SS:SP 0EE8:1000 (the stack follows the image) |
| Code | 0x0000–0x0076 entry, 0x0100–0x014B helpers, 0xC000–0xC005 jump table, 0xDC97–0xEE46 interpreter: about 4.7 KB of code in all (**verified**) |
| Other builds | Dengeki Nurse's `ADV98V.OVL` (Valley Bell's reference) carries the same version string and has the same image size, but is not the same build: besides the start-script name at 0x1FC, 4 238 bytes differ, all from 0xC004 on (jump table, handler table, code) (**verified** by comparison; the differences were not analysed) |

The image is a fixed memory map, not just code: the script, its data and the plug-in code all live
in this one segment at fixed addresses, and scripts and plug-ins rely on them.

### 1.1 Memory map (**verified** unless marked)

| Address | Size | Contents |
|---|---|---|
| 0x0000 | 128 | **flags** ("registers"): 1024 bits, flag *n* = bit *n*&7 of byte *n*>>3 |
| 0x0080 | 26+ | **variables** A–Z, one byte each, values 0–15 (`var[i]` at 0x80+i; the encoding allows indexes up to 62, which would run into the fields below — no script does that) |
| 0x008D, 0x0092, 0x0095 | | variables N, S, V: written by the menu code (§4) |
| 0x009A | ≤ 99 | name of the current `.MES` file (ASCIIZ), set by `mes-jump`; part of the save |
| 0x00FD, 0x00FE | 1+1 | the two values of `set-drive` (§5.3); part of the save |
| 0x00FF | 1 | 0xFF in a written save file (validity mark) |
| 0x0100–0x8FFF | 36 608 | free memory for `load-mem` / `exec-file` (plug-in code and its data); default load address 0x0100 |
| 0x9000–0xBFFF | 12 288 | the current script (`mes-jump` loads the whole file here; the largest script is 10 787 bytes) |
| 0xC000 | 6 | `jmp restart` (0xDC97), `jmp run_saved` (0xDD66): entry points for plug-ins (§6) |
| 0xC006–0xD005 | 4 096 | sub-script buffer of `mes-call` (opcode C0) |
| 0xD006 | 2 | non-zero while a sub-script runs |
| 0xD008–0xD01F | | text state: script pointer, cursor x/y (D00A, D00C), colour (D00E), D010, speed pair (D012, D014), frame x1 y1 x2 y2 (D016–D01C), clear attribute (D01E) |
| 0xD020, 0xD022 | 2+2 | loop start pointers (main script, sub-script) |
| 0xD024 | 2 | block-nesting counter of the scanners |
| 0xD026 | 16×9 | menu item table: index byte, x1, y1, x2, y2 (words) |
| 0xD0B6 | 8 | rectangle of the item being laid out |
| 0xD0C6, C8, CA | | current item, item count, "cancel allowed" |
| 0xD0CC, 0xD0CE | 2+2 | menu key steps (opcode D3) |
| 0xD0D0 | 500 | `menu2` work buffer |
| 0xD2C4–0xD2CF | | `menu2` state, cycle counter (D2C8), last verb/noun pair (D2CA), screen mode (D2CC, D2CE) |
| 0xD2D0 | 20×76 | procedure slots of `define-proc` (cleared at start) |
| 0xD8C0 | 51×2 | opcode handler table, A6..D8 |
| 0xD930 | 7 | the name placeholder `＊＊＊` (81 96 ×3, 00) |
| 0xD937 | 26 | the player's name as a script fragment (default `＊＊＊`, FF FF) |
| 0xD959 | 2 | non-zero while the name is being printed |
| 0xD95B, 0xD987, 0xD9B5 | | built-in messages as script fragments: save failed / nothing saved there / load failed |
| 0xD9E3 | 16 | parameter block of `image-show`: plane segments A800 B000 B800 E000, x, y, p1, mode |
| 0xD9F3 | 128 | file-name buffer |
| 0xDA73 | 128 | argument block of `exec-mem`; command tail of `exec-file` |
| 0xDB01–0xDB09 | | PSP segment, call target, saved SP (main, sub-script), return address |
| 0xDB0B, 0xDB17 | | `A:\NAME.DEF`, `A:\FLAGx` |
| 0xDB20 | 256 | save-file buffer |

## 2. Start-up (0x0000, **verified**)

1. Shrink the memory block to image + stack (`INT 21h/4Ah`); failure → error 1.
2. Check AdvBIOS: the `INT F1h` vector must point into a segment whose bytes at +2 are
   `++ AdvBIOS98 ++` (string at 0x01EC), and `INT F1h, AH=0` must return version ≥ 0.54 (AL.AH ≥ 0036h)
   with BH = 0; otherwise error 4 "AdvBIOS not exist, or illegal version."
3. Copy the start script name (0x01FC: `NV.Ini`; this is the only place a game configures the
   interpreter) to the file-name buffer; no name → error 2 "missing .MES filename."
4. Clear the procedure slots and jump to 0xC000 → `restart` (0xDC97).

Errors print `ERROR: ` + text and exit through `INT 21h/4Ch` with code FFh (0x0113).

`restart` (0xDC97): clear 0x0000–0x00FF and 0x0100–0x8FFF, copy the script name to 0x009A,
register the abort handler 0xDD31 with AdvBIOS (`F1h AX=1000h`), load the script to 0x9000
(`F2h AH=0`; failure → "ERROR: cannot find message file."), `F6h AX=0FFFh CX=0 DX=9F63h`,
`out 68h,0Fh`, remember SP (0xDB05) with the exit routine 0xDD1B as return address, and run from
0x9000. Returning from the top level — an end marker in the main script or `exit` — prints the
banner at 0xDC81 and ends the program.

## 3. The run loop — `run` 0xDE2F (**verified**)

`run` executes statements at SI until an end marker (FF FF or FF FE; SI is left after it) or one of
the block bytes A0–A4 (SI is left after that byte), and returns. Blocks are executed by calling `run`
again, so nesting uses the machine stack. Per statement:

1. `F1h AX=0F01h`, then `AX=0F00h`: if either returns non-zero the interpreter unwinds to the
   top level (0xDD14) and exits (abort request).
2. Name substitution: if the bytes at SI equal `＊＊＊`, the fragment at 0xD937 (the player's name) is
   run instead and SI skips the placeholder.
3. Decode by the first byte (details in mes-format.md): two-byte character → control codes
   `＠ ＄ ｛ ｝` or print; `!` → print the ASCIIZ string through `F6h AH=0Ah`; 00–0F flag assignment;
   10–1F variable operation; A5 → print 0Dh (new line); 2D–7F → print hiragana (82h, byte+72h);
   everything else is an opcode: handler = table[byte − A6h].

There is no check that the byte is a valid opcode: any other byte (20h, 22h–2Ch at statement level,
80h, A0h.., D9h+) indexes outside the table. Scripts never do this.

Characters are printed one at a time with `F6h AH=9, DX=code`; after each the cursor is read back
(`F6h AH=6` → CX, DX) into 0xD00A / 0xD00C.

`run_saved` (0xDD66) wraps `run` for code that must not disturb the text state: it pushes the
twelve state words 0xD008–0xD01E, runs, pops them and re-applies frame, colour, speed and cursor to
AdvBIOS (0xDE01: `F6h AH=1, 3, 7, 5`). It is used for seg-call segments, menu heads, the built-in
messages and the plug-in entry at 0xC003. Procedures (`proc`) are run by a bare `run`.

## 4. Menus (**verified**)

`menu` (AD, 0xE042) and `menu2` (AE, 0xE3CB) share the selection code at 0xE048.

Layout (0xE294, 0xE2D8): operands are (x, y) pairs for the items in order; an item without a pair
goes 20 pixels below the previous one. x is in 8-pixel columns, y in pixels. The statements before
the opening A2 (the head) are run first. Then each item's conditions are evaluated (0xE335) and, if
they hold, its statements are run at the item position with colour 15; the item's rectangle is
start position → (cursor x − 1, cursor y + 15) after printing. Items whose conditions fail are not
listed but still count for the item index. At most 16 items.

Selection (0xE0C7): the first item is highlighted (`F6h AH=0Eh`, SI → rectangle: invert) and the
mouse pointer is moved onto it (`INT 33h AX=4`; AdvBIOS provides the MS-mouse API).
- Mouse: moving over another item highlights it; a left click (`INT 33h AX=5`) on the highlighted
  item selects; a right click (`AX=6`) cancels.
- Keys (`INT 18h`, PC-98 scan codes): 3Ch/48h (→, numpad 6) forward by the D3 "column step" with
  wrap to 0; 3Bh/46h (←, 4) back with wrap to the last; 3Ah/43h (↑, 8) back by the "row step", 3Dh/4Bh
  (↓, 2) forward by it, both without wrap; 1Ch/34h (Return, Space) select; 00h/0Fh (Esc, Tab) cancel.
- Cancel is honoured only where allowed (second level of `menu2`); otherwise it is ignored.

Result: variable **S** (0x92) = index of the chosen item. `menu2` is a two-level verb/noun menu:
the verbs are shown with the head's layout; after a choice (**V** = verb index) the text frame is
cleared and that verb's nouns are shown the same way with cancel allowed; cancel returns to the
verbs. On selection **N** = noun index. If the (V, N) pair differs from the previous `menu2` result
the cycle counter of `branch-cycle` (0xD2C8) is set so that the next cycle starts at alternative 0.
A verb with an empty noun list selects at once (0xE0D2: empty table → select); S and N then hold
FFh, which variable tests read as 15.

## 5. Persistence and disks

### 5.1 Save files `A:\FLAGn` (**verified**: 0xEE13, 0xEDD0, 0xEDF5)

A save is the 256 bytes 0x0000–0x00FF: flags, variables, the current script name, the drive bytes,
and FFh in the last byte. `flag-save n` writes it (`F2h AH=1`), `flag-load n` reads it and then
jumps to the script named in it — a game resumes at the **start of the script that was current when
it was saved**, with flags and variables as saved. `flag-load n m` with m ≠ 0 merges instead: bit 0 of
m copies the flags (bytes 0x00–0x7F), bit 1 the variables A–Z, and nothing jumps; a missing file
counts as all zeros. `save-check n` sets flags 1000+i for i < n (n ≤ 10) to whether `FLAGi` exists and
is valid (256 bytes, last byte ≠ 0).

In NOVA: FLAG0–2 are the three save slots; the existence of FLAG3, FLAG4 and FLAG5 is how the game
remembers that the 2nd story, the 3rd story and the Sound/Graphic modes are unlocked (MODE.MES:
`save-check 5`, menu entries conditional on R1003–R1005) (**verified** in the script; which scripts
write them: script-catalog, to do).

### 5.2 Player name (**verified**: 0xEBE2)

`name-load` (D2) reads `A:\NAME.DEF` (256 bytes) and copies its first 26 bytes to 0xD937. The file
holds the name as script text ending in FF FF (the shipped file: …). Wherever a script contains
`＊＊＊`, the name is printed. Writing the file is the job of the plug-in `INPUTNAM.TCM`.

### 5.3 Drives (**verified** calls, AdvBIOS semantics in advbios.md)

`set-drive a b` stores b at 0xFD+(a&1) and calls `F2h AH=4, AL=a&1, DL=b`. The save code calls it
with (0, 0) before touching `A:\FLAGx` and restores the stored value afterwards. Scripts name
pictures with a drive letter (`B:\GPC\NV03.GPC`) or without (`\GPC\NVWIN.GPC`); the four floppies
carry different picture sets and one name with different contents (`NV43A.GPC` on B and C), so the
drive mapping decides which file is read.

## 6. Plug-ins and external code (**verified**)

- `load-mem "file" [addr]` (C8): read a file to DS:addr (default 0x0100).
- `exec-mem addr args…` (CD, 0xE9A1): build the argument block at 0xDA73 — word 0 = count, then one
  word per argument: a number, or for a string the address of its opening quote inside the script —
  and near-call DS:addr with SI → block, BX, DX, CX = the first three arguments, DS = ES = the
  interpreter segment. The plug-in returns in CH what the interpreter should do with the result:
  CH < 0 nothing; CH = 0 → flag AX = (CL ≠ 0); CH > 0 → variable letter AL = CL & 15.
  (The flag path has an off-by-one: setting uses flag AX, clearing uses flag AX − 1; 0xE9F6–0xEA21.)
- `exec-file "file" addr [entry]` (B0): load to addr and call entry (default addr); without numbers
  it runs a DOS program with the rest of the string as command tail (`INT 21h/4B00h`).
- Plug-ins can run script code through the far-callable entry at 0xC003 (`run_saved`).
- `decrypt key` (D5, 0xEA88): key ≠ 0 decrypts the rest of the script buffer in place
  (`byte = ror(byte, 4) xor key`) and remembers the first 16-byte boundary after the next FEh byte;
  key = 0 calls the code there with BX = 0xEA84. Only `NV.INI` uses it (§7).

NOVA's five plug-ins are documented in [plugins.md](plugins.md) (to do).

## 7. `NV.INI`: start script and copy protection (**verified**)

`NV.INI` is a script: it sets the screen mode and text frame, prints the version banner, then
`decrypt 79` reveals the rest: a loop that calls the appended machine code (`decrypt 0`), and either
jumps to `MES\RUN.MES` or asks for the disk (「ドライブ２に「ＮＯＶＡ」のディスクＢを…」).

The appended code (0x9120 after loading) is the copy protection. It reads drive information and a
sector through the floppy BIOS (`INT 1Bh`), compares 256 bytes with a reference inside itself, and on
success writes the two bytes `CD F3` (`int F3h`) to the address passed in BX = 0xEA84. That address
is in the middle of the `image-show` handler, where the shipped interpreter has `sub al,al` instead
of the interrupt call: **without the patch no picture is ever shown**. It returns variable N = 15 (ok) or
0. In the dump used here the conditional jump after the first test is an unconditional `jmp`
(0x925F), i.e. the check is skipped and the patch always applied; whether that is the original
state or the dumper's fix is unknown (**open**).

A reimplementation ignores all of this: `image-show` simply works, and `NV.INI` need not be run
(what it sets up — screen mode 3 0 0, frame 0 0 79 399, colour 15, drives 0/1 — is repeated by
`RUN.MES`).

## 8. Services the interpreter uses

Everything the interpreter does to the machine goes through these calls (AH = function unless
AX is given). Semantics are AdvBIOS's and described in advbios.md; this is the complete list of
call sites (**verified**).

| Interrupt | Functions used | For |
|---|---|---|
| F1h system | 00 version; 01 random source (branch-random); 06 (sys-CA, DX); 07 wait for key; 08 timed wait (CX, AL); 09 `AX=09FFh` fade step delay; 0A delay (CX, AL); 0C (input "file", DX → name); 0D (input, AL = n & 3 → AL); 0E `AX=0E04h`; 0F00/0F01 abort poll; 1000 set abort handler (DX); 1003 restore | timing, input, abort |
| F2h files | 00 load file DX → DS:BX (CF = error); 01 write CX bytes from BX to file DX; 04 select drive (AL slot, DL value); 05 read at most CX bytes of file DX to BX (AX = length); 06 (DX = name, BX = buffer; before exec-file's DOS EXEC); 0800/0801 (DL) after a load | files |
| F3h graphics | 00 / 08 get the picture load address (ES); 01 show picture (SI → block; the patched call, §7); 09, 0A00, 0B, 0C, 0E (gfx opcodes C2–C5, unused by NOVA); 10; 11 set brightness AL; 12 get brightness; 110F | pictures, fades |
| F4h sound | 00 load + play music file BX; 01 play; 02 stop; 03 fade out (DL speed); 04 (DL); 07 (CX = n − 64); 10 effect file BX; 11 effect number BX | music, effects |
| F6h text | 01 set frame (SI → x1 y1 x2 y2); 03 colour AL; 05 set cursor CX, DX; 06 get cursor; 07 speed (DX, AL); 08 (text-CB, DX); 09 put character DX; 0A put ASCIIZ string at SI; 0B clear frame with AL; 0C00; 0E invert rectangle SI; 0F (text-C6: CH CL DH DL AL); 10 (op-B8: CX, AL); 1200; 0FFF | text |
| 33h mouse | 0 reset, 1 show, 2 hide, 3 position/buttons, 4 set position, 5 press info, 6 release info, 7, 0Dh, 0Eh | menus |
| 18h BIOS | 00/01 keyboard read/sense (menus, key flush 0xEDA3); 40h/41h display on/off, 42h display mode (screen-mode) | keys, display |
| 21h DOS | 09 print, 0C flush, 4Ah, 4B00h exec, 4Ch exit, 35F1h get vector | start-up, exec-file |
| ports | 68h ← 0Fh / 08h (mode flip-flop 1), 6Ah ← 01h (16-colour mode) | screen-mode |

## 9. Open questions

* Whether the `jmp` at 0x925F of `NV.INI`'s code (protection bypass) is original.
* What the protection reads exactly (track/sector, the meaning of "[T131]" in the dump's name);
  irrelevant for a reimplementation.
* How this build differs from Dengeki Nurse's interpreter of the same version number.
* Meaning of the AdvBIOS calls marked only by number in §8: see advbios.md.
