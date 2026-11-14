/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The Adv98V 1.70.54 interpreter (NV.OVL): docs/re/interpreter.md, mes-format.md.
 *
 * The interpreter's segment is modelled as real memory, `ax.mem` (64 KB), with the original
 * layout: flags at 0x0000, variables at 0x0080, script name 0x009A, drive bytes 0x00FD/FE, free
 * memory for plug-ins and data 0x0100-0x8FFF, the script at 0x9000, the sub-script buffer at
 * 0xC006, and the interpreter's variables from 0xD000 at their original addresses. The VM
 * executes script bytes exactly as NV.OVL does: the same operand reader and block scanners, `run`
 * recursing for blocks, unwinding to the top level on mes-jump / exit / quit. */
#ifndef AX_VM_MES_H
#define AX_VM_MES_H

#include <stdint.h>

/* interpreter memory map (interpreter.md §1.1) */
#define MES_FLAGS        0x0000
#define MES_VARS         0x0080
#define MES_VAR_N        0x008D
#define MES_VAR_S        0x0092
#define MES_VAR_V        0x0095
#define MES_NAME         0x009A          /* current script name */
#define MES_DRIVES       0x00FD
#define MES_FREE         0x0100
#define MES_SCRIPT       0x9000
#define MES_SUB          0xC006
#define MES_SUB_ACTIVE   0xD006
#define MES_TEXT_STATE   0xD008          /* 12 words: script ptr, x, y, colour, D010, speed, frame, attr */
#define MES_CUR_X        0xD00A
#define MES_CUR_Y        0xD00C
#define MES_COLOUR       0xD00E
#define MES_D010         0xD010
#define MES_SPEED        0xD012          /* ticks per character */
#define MES_SPEED_SKIP   0xD014
#define MES_FRAME        0xD016          /* x1, y1, x2, y2 */
#define MES_CLEAR_ATTR   0xD01E
#define MES_LOOP_MAIN    0xD020
#define MES_LOOP_SUB     0xD022
#define MES_SCAN_LEVEL   0xD024
#define MES_MENU_ITEMS   0xD026          /* 16 x {index, x1, y1, x2, y2} */
#define MES_MENU_RECT    0xD0B6
#define MES_MENU_CUR     0xD0C6
#define MES_MENU_COUNT   0xD0C8
#define MES_MENU_CANCEL  0xD0CA
#define MES_MENU_STEP_X  0xD0CC
#define MES_MENU_STEP_Y  0xD0CE
#define MES_MENU2_BUF    0xD0D0
#define MES_MENU2_SI     0xD2C4
#define MES_MENU2_BX     0xD2C6
#define MES_CYCLE        0xD2C8
#define MES_MENU2_LAST   0xD2CA
#define MES_SCREEN_MODE  0xD2CC
#define MES_SCREEN_OLD   0xD2CE
#define MES_PROCS        0xD2D0          /* 20 x 76 bytes */
#define MES_NAME_MARK    0xD930          /* ＊＊＊ */
#define MES_PLAYER       0xD937          /* the player's name as a script fragment, 26 bytes */
#define MES_IN_NAME      0xD959
#define MES_MSG_SAVE     0xD95B          /* built-in messages (script fragments) */
#define MES_MSG_EMPTY    0xD987
#define MES_MSG_LOAD     0xD9B5
#define MES_SHOW_BLOCK   0xD9E3          /* image-show parameter block */
#define MES_FILENAME     0xD9F3
#define MES_ARGS         0xDA73          /* exec-mem argument block */
#define MES_CALL_TARGET  0xDB03
#define MES_SAVEBUF      0xDB20          /* 256 bytes */

void vm_init(void);
/* Run the game from the start script (the profile's, NV.INI's target) until it ends: an end
 * marker in the main script, `exit`, or the player quitting. */
void vm_run_game(const char *start);

/* memory access for the plug-in modules and the services */
uint16_t vm_rd16(unsigned a);
void vm_wr16(unsigned a, unsigned v);
/* the run loop entry the plug-ins call through 0xC003 (run_saved) */
void vm_run_saved(unsigned si);

/* the built-in messages of the current language, installed by vm_init (game/run.c) */
void vm_set_messages(const uint8_t *frags, uint32_t size);

/* mes_menu.c */
void vm_op_menu(void);                  /* AD */
void vm_op_menu2(void);                 /* AE */

/* the player quits: unwind to the top level and end (abort_unwind 0xDD14) */
void vm_quit(void);

/* shared with mes_menu.c */
extern uint16_t vm_si;
int  vm_get_number(unsigned *v);        /* 1 = present */
void vm_run(void);
void vm_skip_block(int open, int close);
void vm_skip_token(void);               /* skip_token 0xED3B: one token as the scanners see it */
unsigned vm_copy_block(unsigned bx, int open, int close);   /* returns the end (DX) */
int  vm_alt_exec(void);                 /* 0 = ran, 0xFF = skipped */
void vm_text_clear_default(void);
void vm_state_apply(void);
void vm_set_cursor_from_state(void);
void vm_read_cursor(void);

#endif
