# `.MES` scripts (Adv98V 1.70.54)

The script format as the interpreter `NV.OVL` reads it ([interpreter.md](interpreter.md); handler
addresses refer to it). Everything here is **verified** against the interpreter's code and
checked on data: `source/tools/mes.py` parses all 119 Japanese scripts, `NV.INI` and the 117
scripts of the English translation with every byte accounted for, and its block boundaries agree
with the interpreter's own block scanner in every block (`re-tools/mesdis.py check`). Opcode names
are ours where lime-juice (Fuzion, after tomyun's juice) had none or the code showed a different
meaning; its names are given for reference.

## 1. File

No header. A file is a sequence of **segments**, each ended by `FF FF`; the last is followed by
`FF FE`. `mes-jump` loads a file to 0x9000 and runs it from its first byte. The first segment is
the script's body. The later segments are handlers for `seg-call` and start with conditions (§4).

`NV.INI` alone carries machine code after the `FF FE` (interpreter.md §7).

## 2. Tokens

| First byte | Length | Meaning |
|---|---|---|
| 00–0F | 2 | flag token: `w = b0<<8 | b1`; flag number = `(w & 3FFh) − 1`; bit 10 = value |
| 10–1F | 2 | variable token: index = `((w & 3F0h) >> 4) − 1` (0 = A); `w & 0Fh` = operand; bits 10–11: 00/10 set or equal, 11 add or ≥, 01 subtract or ≤ |
| 21 `!` | to NUL | half-width string, printed as is (`F6h AH=0Ah`), ends with a 00 byte |
| 22 `"` | to `"` | string operand (file names, plug-in commands); only valid as an operand |
| 23–27 | 1 | number 0–4 |
| 28 | 2 | number = next byte |
| 29–2C | 3 | number = `(b0 − 29h)·16384 + b1·128 + (b2 & 7Fh)` |
| 2D–7F | 1 | hiragana: prints Shift-JIS `82h, byte + 72h` |
| 81–9F, E0–FC | 2 | Shift-JIS character, printed; four codes are control codes (§3) |
| A0–A4 | 1 | block structure: A2 open, A3 close, A4 separator; A0 / A1 open and close a noun list in `menu2` |
| A5 | 1 | new line (prints 0Dh) |
| A6–D8 | 1 + operands | opcodes (§5) |
| FF FF, FF FE | 2 | end of segment, end of file |

Numbers are operands only; a handler asks for each of its operands and gets "absent" when the
next byte is not 23–2C. Most operands are therefore optional, and where it matters the table in §5
says what absence means.

The block scanners (skip an alternative, skip to the end of a block: 0xEC22, 0xECDF, 0xED3B) step
over tokens with exactly the lengths of this table, with two consequences. Strings are not
skipped as units — their bytes are stepped over one by one as if they were tokens — so a string
containing a byte 21h, 28h–2Ch, a lead byte or A0–A4 can derail a scan (half-width katakana ｢ ｣ ､
are A2 A3 A4). And `FF` is not special to them. No script of the game is affected (checked).

## 3. Text

Printed characters go to the text frame at the cursor with the current colour (§5, A6–AA). Control
codes inside text:

| Code | Character | Effect |
|---|---|---|
| 81 97 | ＠ | nothing |
| 81 90 | ＄ | wait for a key (`F1h AH=7`), then clear the frame and home the cursor |
| 81 6F | ｛ | remember this position (one slot for the main script, one for a sub-script) |
| 81 70 | ｝ | jump back to the remembered position: an endless loop, left by `mes-jump`, `exit` or a load |
| 81 96 ×3 | ＊＊＊ | the player's name (interpreter.md §5.2) |

Half-width text exists only as the `!…00` string token. The English translation writes its text
that way — see [english-release.md](english-release.md) (to do).

## 4. Conditions

A condition list is a run of flag and variable tokens; all must hold. In a condition a flag token
tests for its value bit; a variable token tests `var == n`, `var ≥ n` (add form) or `var ≤ n`
(subtract form). The same tokens at statement level assign: flag := value; `var := n`,
`var := (var + n) & 15`, `var := (var − n) & 15`.

Conditions appear at the start of: each alternative of `if` / `when`, each menu item, each verb and
noun of `menu2`, and each segment after the first.

## 5. Opcodes

Operands: `n` number, `"s"` string, `L` a letter byte. `{…}` is a block `A2 … A3`; alternatives in
it are separated by A4. "NOVA" = how often the opcode occurs in the 119 Japanese scripts.

| Op | Name (lime-juice) | Operands | Effect | Handler | NOVA |
|---|---|---|---|---|---|
| A6 | text-frame | x1 y1 x2 y2 | set the text frame (columns of 8 px; pixels) and put the cursor at its origin | DF8B | 1473 |
| A7 | text-pos | x y | set the cursor | DFBF | 3 |
| A8 | text-color | c [a [b]] | colour c; a → 0xD010 (unused by the interpreter); b → the attribute `text-clear` uses by default | DFD4 | 548 |
| A9 | text-speed (text-delay) | a b | `F6h AH=7, DX=a, AL=b` | DFF2 | 0 |
| AA | text-clear (text-reset) | [n] | clear the frame with attribute n (default: stored one), cursor to the frame origin | E005 | 744 |
| AB | wait | [t [k]] | no operand: wait for a key. With t: `F1h AH=8, CX=t, AL=k` | E01E | 6560 |
| AC | delay | t [k] | `F1h AH=0Ah, CX=t, AL=k` (absent k = FFh); nothing if t is absent or 0 | E031 | 1172 |
| AD | menu (menu1) | (x y)* head { items } | choice menu; result in S (interpreter.md §4) | E042 | 67 |
| AE | menu2 | (x y)* head { (verb A0 nouns A1)* } | verb / noun menu; results in V, N, S | E3CB | 3 |
| AF | seg-call | – | run the first later segment whose conditions hold (text state saved and restored), then continue | E47B | 23 |
| B0 | exec-file | "s" [addr [entry]] | load and call machine code, or run a DOS program | E4F3 | 0 |
| B1 | mes-jump | "s" | load a script and run it from the top level (the stack is reset) | E59A | 225 |
| B2 | branch-random | { alts } | run alternative `(F1h AH=1 result >> 3) & 15`, counting cyclically | E5BC | 0 |
| B3 | branch-cycle (branch-index) | { alts } | run the next alternative each time (counter 0–15, cyclic; reset by a new `menu2` choice) | E5E6 | 0 |
| B4 | branch-var | L { alts } | run alternative number = variable L | E5F6 | 0 |
| B5 | branch-reg | n { alts } | run alternative 0 or 1 = flag n | E608 | 0 |
| B6 | input (execute-var) | L n \| "s" | variable L := `F1h AH=0Dh, AL=n&3` (low 4 bits), mouse hidden meanwhile; or `F1h AH=0Ch, DX → "s"` | E61B | 22 |
| B7 | screen-mode (mouse) | m [a b] | m>>1 → 400-line (1) or 200-line (0) display mode (`INT 18h AH=42h`); display on unless a ≠ 0 (off); 16-colour mode; mouse reset if the mode changed | E65F | 119 |
| B8 | – | [a [b]] | `F6h AH=10h, CX=a (0), AL=b (1)` | E6B1 | 0 |
| B9 | define-proc | n { body } | copy the block to procedure slot n (20 slots of 76 bytes; a longer body runs into the next slots) | E6C8 | 680 |
| BA | proc | n | run slot n | E6DF | 19679 |
| BB | repeat | n { body } | run the body n times | E6F2 | 0 |
| BC | if | { alts } | run the first alternative whose conditions hold | E708 | 276 |
| BD | when | { alts } | run every alternative whose conditions hold | E71F | 0 |
| BE | flag-save | n | write the save file n; on failure show the built-in message | E72A | 14 |
| BF | flag-load | n [m] | m absent/0: load save n and jump to its script; else merge (bit 0 flags, bit 1 variables) | E753 | 3 |
| C0 | mes-call (mes-load?) | "s" | load a script of at most 4096 bytes to the sub-script buffer and run it; not nestable | E7E9 | 0 |
| C1 | – | n "s" | load a picture file to buffer n&1 (`F3h AH=8`) | E83D | 0 |
| C2 | – | n "s" | `F3h AH=0Bh, AL=n`, SI → string | E859 | 0 |
| C3 | – | a b | `F3h AH=0Ch, CX=a, AL=b` | E867 | 0 |
| C4 | – | a b | `F3h AX=0A00h`; `F3h AH=9, AL=a&1, BL=b+B1h` | E875 | 0 |
| C5 | – | a b | `F3h AH=0Eh, CX=a, AL=b`; `F3h AX=0A00h` | E88D | 0 |
| C6 | – | a b c d e | `F6h AH=0Fh, CH=a CL=b DH=c DL=d AL=e` | E8A0 | 2 |
| C7 | save-check | n | flags 1000..1000+n−1 := save file exists | E8BC | 1 |
| C8 | load-mem | "s" [addr] | read a file to DS:addr (default 0x100) | E901 | 228 |
| C9 | image-file | "s" | read a picture file into the picture buffer | E919 | 1038 |
| CA | – (print-var) | [n] | `F1h AH=6, DX=n` (default 370h) | E92D | 0 |
| CB | – | [n] | `F6h AH=8, DX=n` | E942 | 0 |
| CC | reg-clear | [a [b]] | clear all flags, or flags a..b | E950 | 0 |
| CD | exec-mem | addr args… | call a plug-in (interpreter.md §6) | E9A1 | 673 |
| CE | set-drive | a b | drive slot a&1 := b | EA32 | 254 |
| CF | image-show (image-mem) | p [mode [x y]] | show the loaded picture: `F3h AH=1` with the block at 0xD9E3 (p, mode & 3 default 3, x y default FFFFh) | EA4A | 1260 |
| D0 | sound | "s" \| n [m] \| `se` "s" \| `se` n | "s": stop, load and play a music file. n=1: play (or, with m: `F4h AH=7, CX=min(m,128)−64`); 2: fade out, speed m (default 20); 3: `F4h AH=4`, same operand; other: stop. `se`: sound effect by file or number | EAD6 | 562 |
| D1 | fade | k [n [m]] | brightness 0–15. k=0: down to 0, k=1: up to 15, k=2: to level n; the step delay is n (m for k=2), 0 or absent = at once | EB63 | 997 |
| D2 | name-load | – | read `A:\NAME.DEF` | EBE2 | 7 |
| D3 | menu-step | a b | key steps of the menus: ←/→ move by a, ↑/↓ by b | EC14 | 118 |
| D4 | exit | – | leave the script level: ends a sub-script, or the program | E828 | 1 |
| D5 | decrypt | key | interpreter.md §6 | EA88 | 2 (NV.INI) |
| D6–D8 | – | – | nothing | EC21 | 0 |

NOVA uses 30 of the 51 opcodes. Its scripts drive the graphics almost entirely through three
idioms: `image-file` + `image-show`, `fade`, and the plug-in `ACTE1.TCM` (`exec-mem 256 "GET …"` /
`"PUT …,FREE …"`: save and restore the screen under the text window).

## 6. Defects in the original scripts

| Script | Offset | Defect | Consequence |
|---|---|---|---|
| BLG2.MES | 0x7D6 | an `if` alternative is not closed before the segment ends | none: the alternative ends in a loop jump |
| S018.MES | 0x1679 | same | none: the alternative ends in `mes-jump` |
| NOVA3.MES | 0x891 | a stray A3 after the last statement | none: it follows a `mes-jump` |

The English translation's versions of these three files parse without defects.

## 7. Open questions

* The effect of the calls given only by number in §5 (A9, B6, B8, C2–C6, CA, CB, D0 n=3 and m):
  see advbios.md.
* `wait t k` / `delay t k`: the meaning of k (the scripts use `delay t` and `delay t 0`).
