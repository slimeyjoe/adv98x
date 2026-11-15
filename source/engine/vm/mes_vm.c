/* SPDX-License-Identifier: GPL-3.0-or-later */
/* The interpreter: NV.OVL 0xDC97-0xEE46 (docs/re/interpreter.md, mes-format.md). Function
 * comments name the original routine and address. `vm_si` is the original's SI; `run` recurses
 * for blocks as the original does on the machine stack; the original's resets of SP (mes-jump,
 * exit, quit) are longjmps to the top level or to the sub-script's level. */
#include <setjmp.h>
#include <stdio.h>
#include <string.h>
#include "ax.h"
#include "bios/bios.h"
#include "gfx/textlayer.h"
#include "mod/mod.h"
#include "vm/mes.h"

uint16_t vm_si;
static jmp_buf top_jb, sub_jb;
enum { UNWIND_JUMP = 1, UNWIND_END = 2 };

/* where the built-in messages are (vm_set_messages) */
static uint16_t msg_addr[3] = { MES_MSG_SAVE, MES_MSG_EMPTY, MES_MSG_LOAD };

/* the text printed since the last statement that was not text, for the trace */
static uint8_t text_buf[512];
static int text_len;

#define M (ax.mem)

uint16_t vm_rd16(unsigned a)
{
    return (uint16_t)(M[a & 0xFFFF] | (M[(a + 1) & 0xFFFF] << 8));
}

void vm_wr16(unsigned a, unsigned v)
{
    M[a & 0xFFFF] = (uint8_t)v;
    M[(a + 1) & 0xFFFF] = (uint8_t)(v >> 8);
}

static uint8_t byte_at(unsigned a)
{
    return M[a & 0xFFFF];
}

/* ---- trace helpers ----------------------------------------------------------------------- */

static void text_flush(void)
{
    if (text_len && LRV_TRACING(&ax.sys)) {
        text_buf[text_len] = 0;
        lrv_sys_trace(&ax.sys, AX_TR_TEXT, 0, text_buf, 0, 0, 0, 0);
    }
    text_len = 0;
}

static void text_add(unsigned dx)
{
    if (!LRV_TRACING(&ax.sys))
        return;
    if (text_len + 3 >= (int)sizeof text_buf)
        text_flush();
    if (dx >> 8)
        text_buf[text_len++] = (uint8_t)(dx >> 8);
    text_buf[text_len++] = (uint8_t)dx;
}

static void trace_op(unsigned op, unsigned at)
{
    if (!LRV_TRACING(&ax.sys))
        return;
    ax.sys.script_pos = at;
    lrv_sys_trace(&ax.sys, AX_TR_OP, 0, 0, (int)op, 0, 0, 0);
}

/* ---- operands (get_number 0xEC54, reg_addr 0xECA3, var_addr 0xECC2) ------------------------ */

int vm_get_number(unsigned *v)
{
    unsigned b = byte_at(vm_si);
    if (b < 0x23 || b > 0x2C) {
        *v = 0xFFFF;
        return 0;
    }
    vm_si++;
    if (b < 0x28) {
        *v = b - 0x23;
    } else if (b == 0x28) {
        *v = byte_at(vm_si);
        vm_si++;
    } else {
        unsigned b1 = byte_at(vm_si), b2 = byte_at(vm_si + 1);
        vm_si += 2;
        *v = (((b - 0x29) * 64u & 0xFF) << 8) + b1 * 128u + (b2 & 0x7F);
        *v &= 0xFFFF;
    }
    return 1;
}


/* reg_addr: BX = byte of flag (w & 3FFh) - 1, DH = its bit; returns the token's value bit */
static int reg_addr(unsigned w, unsigned *bx, uint8_t *mask)
{
    *mask = (uint8_t)(1u << ((w - 1) & 7));
    *bx = (((w & 0x3FF) - 1) & 0xFFFF) >> 3;
    return (w >> 10) & 1;
}

/* var_addr: BX = 80h + index, CH = operand, CL = value & 15, AH = operation (bits 10-11) */
static void var_addr(unsigned w, unsigned *bx, unsigned *ch, unsigned *cl, unsigned *op)
{
    *ch = w & 0x0F;
    *bx = ((((w & 0x3F0) >> 4) - 1) + 0x80) & 0xFFFF;
    *cl = byte_at(*bx) & 0x0F;
    *op = (w >> 8) & 0x0C;
}

/* reg_assign 0xDF5E */
static void reg_assign(unsigned w)
{
    unsigned bx;
    uint8_t mask;
    if (reg_addr(w, &bx, &mask))
        M[bx] |= mask;
    else
        M[bx] &= (uint8_t)~mask;
    lrv_sys_trace(&ax.sys, AX_TR_FLAG, 0, 0, (int)((w & 0x3FF) - 1), (int)((w >> 10) & 1), 0, 0);
}

/* var_assign 0xDF6B */
static void var_assign(unsigned w)
{
    unsigned bx, ch, cl, op;
    var_addr(w, &bx, &ch, &cl, &op);
    if (op == 0x0C) {
        M[bx] = (uint8_t)((ch + M[bx]) & 0x0F);
    } else if (op == 0x04) {
        M[bx] = (uint8_t)(M[bx] - ch);
        M[bx] &= 0x0F;
    } else {
        M[bx] = (uint8_t)ch;
    }
    lrv_sys_trace(&ax.sys, AX_TR_FLAG, 0, 0, (int)bx, M[bx], 0, 0);
}

/* ---- scanners (skip_token 0xED3B, skip_block 0xEC22, skip_alt 0xECDF, copy_block 0xED25) ---- */

static int is_lead(unsigned b)
{
    return (b >= 0x81 && b <= 0x9F) || (b >= 0xE0 && b <= 0xFC);
}

/* skip_token: the length the scanners step over; strings are not units */
void vm_skip_token(void)
{
    unsigned ah = byte_at(vm_si);
    vm_si++;
    if (ah == 0x21) {                   /* `!`: to and over the NUL */
        while (byte_at(vm_si++))
            ;
        return;
    }
    if (ah >= 0x23 && ah < 0x28)
        return;
    if (ah == 0x28) {
        vm_si++;
        return;
    }
    if (ah >= 0x29 && ah < 0x2D) {
        vm_si += 2;
        return;
    }
    if ((ah & 0xF0) == 0x00 || (ah & 0xF0) == 0x10 || is_lead(ah))
        vm_si++;
}

void vm_skip_block(int open, int close)
{
    uint16_t saved = vm_rd16(MES_SCAN_LEVEL);
    unsigned level = 1;
    vm_wr16(MES_SCAN_LEVEL, 1);
    for (;;) {
        unsigned b = byte_at(vm_si);
        vm_si++;
        if ((int)b == open) {
            level++;
        } else if ((int)b == close) {
            if (--level == 0)
                break;
        } else {
            vm_si--;
            vm_skip_token();
        }
    }
    vm_wr16(MES_SCAN_LEVEL, saved);
}

/* returns 0 after an A4 at level 1, FFh after the closing A3 */
static int skip_alt(void)
{
    unsigned level = 1;
    for (;;) {
        unsigned b = byte_at(vm_si);
        vm_si++;
        if (b == 0xA4) {
            if (level == 1)
                return 0;
        } else if (b == 0xA2) {
            level++;
        } else if (b == 0xA3) {
            if (--level == 0)
                return 0xFF;
        } else {
            vm_si--;
            vm_skip_token();
        }
    }
}

unsigned vm_copy_block(unsigned bx, int open, int close)
{
    uint16_t start = vm_si, end, n, i;
    vm_skip_block(open, close);
    end = vm_si;
    n = (uint16_t)(end - start);
    for (i = 0; i < n; i++)
        M[(bx + i) & 0xFFFF] = M[(uint16_t)(start + i)];
    vm_si = start;
    return end;
}

/* ---- text state (state_push 0xDD86, state_pop 0xDDC6, state_apply 0xDE01) ------------------ */

#define STATE_WORDS 12
static const uint16_t state_addr[STATE_WORDS] = {
    0xD008, 0xD00A, 0xD00C, 0xD00E, 0xD010, 0xD014, 0xD012, 0xD016, 0xD018, 0xD01A, 0xD01C,
    0xD01E
};

struct text_state { uint16_t w[STATE_WORDS]; };

static void state_push(struct text_state *s)
{
    int i;
    for (i = 0; i < STATE_WORDS; i++)
        s->w[i] = vm_rd16(state_addr[i]);
    vm_wr16(MES_TEXT_STATE, vm_si);
}

void vm_state_apply(void)
{
    uint16_t rect[4];
    int i;
    for (i = 0; i < 4; i++)
        rect[i] = vm_rd16(MES_FRAME + 2 * (unsigned)i);
    bt_set_window(rect);
    bt_set_colour(vm_rd16(MES_COLOUR) & 0xFF);
    bt_set_delay(vm_rd16(MES_SPEED), vm_rd16(MES_SPEED_SKIP) & 0xFF);
    bt_set_cursor(vm_rd16(MES_CUR_X), vm_rd16(MES_CUR_Y));
}

static void state_pop(const struct text_state *s)
{
    int i;
    for (i = 0; i < STATE_WORDS; i++)
        vm_wr16(state_addr[i], s->w[i]);
    vm_state_apply();
}

void vm_read_cursor(void)
{
    unsigned x, y;
    bt_cursor(&x, &y);
    vm_wr16(MES_CUR_X, x);
    vm_wr16(MES_CUR_Y, y);
}

void vm_set_cursor_from_state(void)
{
    bt_set_cursor(vm_rd16(MES_CUR_X), vm_rd16(MES_CUR_Y));
}

static void print(unsigned dx)
{
    text_add(dx);
    bt_draw_char(dx);
    vm_read_cursor();
}

/* run_saved 0xDD66 */
void vm_run_saved(unsigned si)
{
    struct text_state s;
    vm_si = (uint16_t)si;
    state_push(&s);
    vm_run();
    state_pop(&s);
}

/* text_clear_default 0xE00A (and op AA with an operand: 0xE00D) */
static void text_clear(unsigned attr)
{
    text_flush();
    bt_fill_window((int)(attr & 0xFF));
    vm_wr16(MES_CUR_X, vm_rd16(MES_FRAME));
    vm_wr16(MES_CUR_Y, vm_rd16(MES_FRAME + 2));
}

void vm_text_clear_default(void)
{
    text_clear(vm_rd16(MES_CLEAR_ATTR));
}

/* ---- the run loop (run 0xDE2F) ----------------------------------------------------------- */

static void op_dispatch(unsigned op);

static void unwind_end(void)
{
    text_flush();
    longjmp(top_jb, UNWIND_END);
}

void vm_quit(void)
{
    unwind_end();
}

void vm_run(void)
{
    for (;;) {
        unsigned ah, al, w;
        /* abort_poll1 / abort_poll0: the player quits -> unwind to the top level and end */
        if (bios_quit_flag() || bios_quit_poll())
            unwind_end();
        /* the name placeholder (0xDE37) */
        if (!vm_rd16(MES_IN_NAME)) {
            unsigned k = 0;
            while (byte_at(MES_NAME_MARK + k) && byte_at(vm_si + k) == byte_at(MES_NAME_MARK + k))
                k++;
            if (!byte_at(MES_NAME_MARK + k)) {
                uint16_t si = vm_si;
                vm_wr16(MES_IN_NAME, 0xFFFF);
                vm_si = MES_PLAYER;
                vm_run();
                vm_si = (uint16_t)(si + k);
                vm_wr16(MES_IN_NAME, 0);
            }
        }
        ah = byte_at(vm_si);
        al = byte_at(vm_si + 1);
        w = (ah << 8) | al;
        ax.sys.script_pos = vm_si;
        vm_si += 2;
        if (w == 0xFFFF || w == 0xFFFE)
            return;
        if (ah >= 0xA0 && ah < 0xA5) {
            vm_si--;
            return;
        }
        if (is_lead(ah)) {
            if (w == 0x8197)                        /* ＠ */
                continue;
            if (w == 0x8190) {                      /* ＄ */
                text_flush();
                bios_wait_input();
                vm_text_clear_default();
                continue;
            }
            if (w == 0x816F) {                      /* ｛ */
                vm_wr16(vm_rd16(MES_SUB_ACTIVE) ? MES_LOOP_SUB : MES_LOOP_MAIN, vm_si);
                continue;
            }
            if (w == 0x8170) {                      /* ｝ */
                static uint32_t spin_frame, spins;
                vm_si = vm_rd16(vm_rd16(MES_SUB_ACTIVE) ? MES_LOOP_SUB : MES_LOOP_MAIN);
                /* a loop that waits for nothing (END.MES ends in `｛＠｝`) spins forever in the
                 * original; here it lets a frame pass every 1000 rounds, so the window stays
                 * alive and the player can quit */
                if (ax.sys.frame != spin_frame) {
                    spin_frame = ax.sys.frame;
                    spins = 0;
                } else if (++spins >= 1000) {
                    spins = 0;
                    text_flush();
                    lrv_sys_frame_wait(&ax.sys);
                }
                continue;
            }
            print(w);
            continue;
        }
        if (ah == 0x21) {                           /* `!` half-width string */
            uint16_t s = (uint16_t)(vm_si - 1);
            uint8_t buf[512];
            unsigned n = 0;
            while (n < sizeof buf - 1 && byte_at(s + n) && byte_at(s + n) != 0xFF) {
                buf[n] = byte_at(s + n);
                n++;
            }
            buf[n] = 0;
            if (LRV_TRACING(&ax.sys)) {
                unsigned i;
                for (i = 0; i < n; i++)
                    text_add(buf[i]);
            }
            bt_draw_string(buf);
            vm_si = s;
            while (byte_at(vm_si++))
                ;
            vm_read_cursor();
            continue;
        }
        if ((ah & 0xF0) == 0x00) {
            text_flush();
            reg_assign(w);
            continue;
        }
        if ((ah & 0xF0) == 0x10) {
            text_flush();
            var_assign(w);
            continue;
        }
        vm_si--;
        if (ah == 0xA5) {
            print(0x0D);
            continue;
        }
        if (ah >= 0x2D && ah <= 0x7F) {
            print(0x8200 | ((ah + 0x72) & 0xFF));
            continue;
        }
        text_flush();
        op_dispatch(ah);
    }
}

/* alt_exec 0xE335: the conditions of an alternative; run it (0) or skip it (FFh) */
int vm_alt_exec(void)
{
    for (;;) {
        unsigned ah = byte_at(vm_si), al, w;
        if (ah == 0xA3 || ah == 0xA4) {
            skip_alt();
            return 0xFF;
        }
        al = byte_at(vm_si + 1);
        vm_si += 2;
        w = (ah << 8) | al;
        if ((ah & 0xF0) == 0x00) {
            unsigned bx;
            uint8_t mask;
            int want = reg_addr(w, &bx, &mask);
            if (((M[bx] & mask) != 0) != want) {
                skip_alt();
                return 0xFF;
            }
        } else if ((ah & 0xF0) == 0x10) {
            unsigned bx, ch, cl, op;
            int ok;
            var_addr(w, &bx, &ch, &cl, &op);
            ok = op == 0x0C ? ch <= cl : op == 0x04 ? ch >= cl : ch == cl;
            if (!ok) {
                skip_alt();
                return 0xFF;
            }
        } else {
            vm_si -= 2;
            vm_set_cursor_from_state();
            vm_run();
            return 0;
        }
    }
}

/* ---- file names -------------------------------------------------------------------------- */

/* copy_string 0xEDC1: from SI up to the closing quote, ASCIIZ at `dst` in memory */
static void copy_string(unsigned dst)
{
    unsigned i = 0;
    for (;;) {
        uint8_t c = byte_at(vm_si);
        vm_si++;
        if (c == '"')
            break;
        M[(dst + i++) & 0xFFFF] = c;
    }
    M[(dst + i) & 0xFFFF] = 0;
}

static const char *mem_str(unsigned a)
{
    static char buf[128];
    unsigned i;
    for (i = 0; i < sizeof buf - 1 && byte_at(a + i); i++)
        buf[i] = (char)byte_at(a + i);
    buf[i] = 0;
    return buf;
}

/* load a file into interpreter memory at `addr`: -1 when it cannot be read (CF) */
static long load_to(const char *name, unsigned addr)
{
    return bios_file_load(name, M + (addr & 0xFFFF), 0x10000u - (addr & 0xFFFF));
}

/* ---- opcodes ----------------------------------------------------------------------------- */

static void op_text_frame(void)                 /* A6, 0xDF8B */
{
    unsigned v;
    uint16_t rect[4];
    int i;
    vm_get_number(&v); vm_wr16(MES_FRAME, v); vm_wr16(MES_CUR_X, v);
    vm_get_number(&v); vm_wr16(MES_FRAME + 2, v); vm_wr16(MES_CUR_Y, v);
    vm_get_number(&v); vm_wr16(MES_FRAME + 4, v);
    vm_get_number(&v); vm_wr16(MES_FRAME + 6, v);
    for (i = 0; i < 4; i++)
        rect[i] = vm_rd16(MES_FRAME + 2 * (unsigned)i);
    bt_set_window(rect);
    vm_set_cursor_from_state();
}

static void op_text_pos(void)                   /* A7 */
{
    unsigned x, y;
    vm_get_number(&x);
    vm_wr16(MES_CUR_X, x);
    vm_get_number(&y);
    vm_wr16(MES_CUR_Y, y);
    bt_set_cursor(x, y);
}

static void op_text_color(void)                 /* A8 */
{
    unsigned v;
    vm_get_number(&v);
    vm_wr16(MES_COLOUR, v);
    if (vm_get_number(&v)) {
        vm_wr16(MES_D010, v);
        if (vm_get_number(&v))
            vm_wr16(MES_CLEAR_ATTR, v);
    }
    bt_set_colour(vm_rd16(MES_COLOUR) & 0xFF);
}

static void op_text_speed(void)                 /* A9 */
{
    unsigned a, b;
    vm_get_number(&a);
    vm_wr16(MES_SPEED, a);
    vm_get_number(&b);
    vm_wr16(MES_SPEED_SKIP, b);
    bt_set_delay(a, (int)(b & 0xFF));
}

static void op_text_clear(void)                 /* AA */
{
    unsigned v;
    if (vm_get_number(&v))
        text_clear(v);
    else
        vm_text_clear_default();
}

static void op_wait(void)                       /* AB */
{
    unsigned t, k;
    if (!vm_get_number(&t)) {
        bios_wait_input();
        return;
    }
    vm_get_number(&k);
    bios_wait_input_timeout(t, (k & 0xFF) != 0);
}

static void op_delay(void)                      /* AC */
{
    unsigned t, k;
    if (!vm_get_number(&t) || !t)
        return;
    vm_get_number(&k);
    bios_delay_anim(t, (k & 0xFF) != 0);
}

/* seg_scan 0xE481: the first later segment whose conditions hold, run with the text state
 * saved */
static void op_seg_call(void)                   /* AF */
{
    uint16_t si = vm_si;
    while (vm_rd16(vm_si) != 0xFFFF)
        vm_si++;
    vm_si += 2;
    for (;;) {
        unsigned ah = byte_at(vm_si), al = byte_at(vm_si + 1), w = (ah << 8) | al;
        vm_si += 2;
        if (w == 0xFFFE)
            break;
        if ((ah & 0xF0) == 0x00 || (ah & 0xF0) == 0x10) {
            int ok;
            if ((ah & 0xF0) == 0x00) {
                unsigned bx;
                uint8_t mask;
                int want = reg_addr(w, &bx, &mask);
                ok = ((M[bx] & mask) != 0) == want;
            } else {
                unsigned bx, ch, cl, op;
                var_addr(w, &bx, &ch, &cl, &op);
                ok = op == 0x0C ? ch <= cl : op == 0x04 ? ch >= cl : ch == cl;
            }
            if (ok)
                continue;
            /* skip to the next segment: the next FF FF (or FF FE: none left) */
            for (;;) {
                if (byte_at(vm_si++) != 0xFF)
                    continue;
                al = byte_at(vm_si++);
                if (al == 0xFE)
                    goto done;
                if (al == 0xFF)
                    break;
            }
            continue;
        }
        vm_si -= 2;
        vm_run_saved(vm_si);
        break;
    }
done:
    vm_si = si;
}

static void op_exec_file(void)                  /* B0 */
{
    unsigned addr, entry;
    vm_si++;
    copy_string(MES_FILENAME);
    if (!vm_get_number(&addr)) {
        lrv_log(ax.hal, LRV_LOG_WARN, "exec-file %s: DOS programs are not run",
                mem_str(MES_FILENAME));
        return;
    }
    vm_wr16(MES_CALL_TARGET, addr);
    if (!mod_load(mem_str(MES_FILENAME), addr))
        load_to(mem_str(MES_FILENAME), addr);
    if (vm_get_number(&entry))
        vm_wr16(MES_CALL_TARGET, entry);
    if (mod_exec(vm_rd16(MES_CALL_TARGET)) < 0)
        lrv_log(ax.hal, LRV_LOG_ERROR, "exec-file %s: no module", mem_str(MES_FILENAME));
}

/* mes-jump 0xE59A / 0xE5A1: load the script named at 0x9A and run it from the top level */
static void jump_to_name(void)
{
    vm_wr16(MES_SUB_ACTIVE, 0);
    if (load_to(mem_str(MES_NAME), MES_SCRIPT) < 0)
        lrv_log(ax.hal, LRV_LOG_ERROR, "mes-jump: cannot load %s", mem_str(MES_NAME));
    text_flush();
    longjmp(top_jb, UNWIND_JUMP);
}

static void op_mes_jump(void)                   /* B1 */
{
    vm_si++;
    copy_string(MES_NAME);
    jump_to_name();
}

/* branch_select 0xE5CA: run alternative `n` of the block at vm_si (after its A2), wrapping */
static void branch_select(unsigned n)
{
    uint16_t start = vm_si;
    n &= 0xFF;
    while (n) {
        n--;
        if (skip_alt() != 0)
            vm_si = start;
    }
    vm_run();
    vm_si = start;
    vm_skip_block(0xA2, 0xA3);
}

static void op_branch_random(void)              /* B2 */
{
    vm_si++;
    branch_select((bios_random() >> 3) & 15);
}

static void op_branch_cycle(void)               /* B3 */
{
    unsigned c = (vm_rd16(MES_CYCLE) + 1) & 15;
    vm_wr16(MES_CYCLE, c);
    vm_si++;
    branch_select(c);
}

static void op_branch_var(void)                 /* B4 */
{
    unsigned bl = byte_at(vm_si);
    vm_si += 2;
    branch_select(byte_at(0x80 + ((bl - 0x41) & 0xFF)));
}

static void op_branch_reg(void)                 /* B5 */
{
    unsigned n, bx;
    uint8_t mask;
    vm_get_number(&n);
    reg_addr((n + 1) & 0xFFFF, &bx, &mask);
    vm_si++;
    branch_select((M[bx] & mask) ? 1 : 0);
}

static void op_input(void)                      /* B6 */
{
    if (byte_at(vm_si) == '"') {
        vm_si++;
        copy_string(MES_FILENAME);
        bios_load_clickmap(mem_str(MES_FILENAME));
    } else {
        unsigned emu = mouse_emulation(), var, n, id;
        mouse_set_emulation(0xFFFF);
        var = (byte_at(vm_si) & 0x1F) - 1;
        vm_si++;
        if (!vm_get_number(&n))
            n = 0;
        id = bios_click_wait((int)(n & 3)) & 15;
        M[(0x80 + var) & 0xFFFF] = (uint8_t)id;
        mouse_set_emulation(emu);
    }
}

static void op_screen_mode(void)                /* B7 */
{
    unsigned m, a, b;
    vm_get_number(&m);
    vm_wr16(MES_SCREEN_MODE, (m >> 1) & 0x7FFF);
    /* INT 18h AH=42h: 400 (m bit 1) or 200 lines; the engine shows 400 */
    if (vm_get_number(&a)) {
        vm_get_number(&b);
        lrv_screen_set_display_on(&ax.screen, a == 0);
    } else {
        lrv_screen_set_display_on(&ax.screen, 1);
    }
    if (vm_rd16(MES_SCREEN_MODE) != vm_rd16(MES_SCREEN_OLD)) {
        vm_wr16(MES_SCREEN_OLD, vm_rd16(MES_SCREEN_MODE));
        mouse_reset();
    }
}

static void op_scroll(void)                     /* B8 */
{
    unsigned a, b;
    if (!vm_get_number(&a))
        a = 0;
    if (!vm_get_number(&b))
        b = 1;
    bt_scroll((int)(b & 0xFF), a);              /* INT F6h AH=10h, AL = b, CX = a */
}

static void op_define_proc(void)                /* B9 */
{
    unsigned n;
    vm_get_number(&n);
    vm_si++;
    vm_si = (uint16_t)vm_copy_block((MES_PROCS + n * 0x4C) & 0xFFFF, 0xA2, 0xA3);
}

static void op_proc(void)                       /* BA */
{
    unsigned n;
    uint16_t si;
    vm_get_number(&n);
    si = vm_si;
    vm_si = (uint16_t)(MES_PROCS + n * 0x4C);
    vm_run();
    vm_si = si;
}

static void op_repeat(void)                     /* BB */
{
    unsigned n;
    uint16_t start;
    uint32_t count;
    vm_get_number(&n);
    vm_si++;
    start = vm_si;
    count = n ? n : 0x10000u;                   /* `loop` with CX = 0 runs 65536 times */
    while (count--) {
        vm_run();
        vm_si = start;
    }
    vm_skip_block(0xA2, 0xA3);
}

static void op_if(void)                         /* BC */
{
    uint16_t start;
    vm_si++;
    start = vm_si;
    for (;;) {
        if (vm_alt_exec() == 0)
            break;
        if (byte_at(vm_si - 1) == 0xA3)
            break;
    }
    vm_si = start;
    vm_skip_block(0xA2, 0xA3);
}

static void op_when(void)                       /* BD */
{
    vm_si++;
    do
        vm_alt_exec();
    while (byte_at(vm_si - 1) != 0xA3);
}

/* save files A:\FLAGn (0xEDD0 save_read, 0xEDF5 save_load, 0xEE13 save_write) */
static const char *save_name(unsigned n)
{
    static char name[12] = "A:\\FLAGx";
    name[7] = (char)('0' + n);
    return name;
}

/* AX = the last byte, sign-extended (CBW), or 0 */
static unsigned save_read(unsigned n)
{
    long len;
    n &= 0xFF;
    if (n >= 10)
        return 0;
    len = bios_file_read(save_name(n), M + MES_SAVEBUF, 256);
    if (len != 256)
        return 0;
    return (unsigned)(uint16_t)(int16_t)(int8_t)M[MES_SAVEBUF + 255];
}

static unsigned save_write(unsigned n)
{
    n &= 0xFF;
    if (n >= 10)
        return 0xFFFF;
    memcpy(M + MES_SAVEBUF, M, 256);
    M[MES_SAVEBUF + 255] = 0xFF;
    if (bios_file_write(save_name(n), M + MES_SAVEBUF, 256) < 0)
        return 0xFFFF;
    return 0;
}

static void message(int k)
{
    uint16_t si = vm_si;
    vm_run_saved(msg_addr[k]);
    vm_si = si;
}

static void op_flag_save(void)                  /* BE */
{
    unsigned n;
    bios_select_drive(0, 0);
    if (!vm_get_number(&n))
        n = 0;
    if (save_write(n) != 0)
        message(0);
    bios_select_drive(0, byte_at(MES_DRIVES));
}

static void op_flag_load(void)                  /* BF */
{
    unsigned n, m;
    bios_select_drive(0, 0);
    if (!vm_get_number(&n))
        n = 0;
    if (!vm_get_number(&m) || m == 0) {
        if (save_read(n) == 0) {
            message(1);
            bios_select_drive(0, byte_at(MES_DRIVES));
            return;
        }
        if (save_read(n) == 0) {                /* save_load: read again, then copy */
            message(2);
            bios_select_drive(0, byte_at(MES_DRIVES));
            return;
        }
        memcpy(M, M + MES_SAVEBUF, 256);
        lrv_sys_trace(&ax.sys, AX_TR_LOAD, save_name(n), 0, (int)n, 1, 0, 0);
        bios_select_drive(0, byte_at(MES_DRIVES));   /* F2h AX=0800h/0801h: drive state */
        jump_to_name();
    }
    if (save_read(n) == 0)
        memset(M + MES_SAVEBUF, 0, 256);
    if (m & 1)
        memcpy(M, M + MES_SAVEBUF, 0x80);
    if (m & 2)
        memcpy(M + MES_VARS, M + MES_SAVEBUF + 0x80, 0x1A);
    lrv_sys_trace(&ax.sys, AX_TR_LOAD, save_name(n), 0, (int)n, 2, (int)m, 0);
    bios_select_drive(0, byte_at(MES_DRIVES));
}

static void op_mes_call(void)                   /* C0 */
{
    long len;
    vm_si++;
    copy_string(MES_FILENAME);
    len = bios_file_read(mem_str(MES_FILENAME), M + MES_SUB, 0x1000);
    if (len > 0x1000 || len <= 2 || vm_rd16(MES_SUB_ACTIVE))
        return;
    vm_wr16(MES_SUB_ACTIVE, 0xFFFF);
    {
        uint16_t si = vm_si;
        struct text_state s;
        jmp_buf outer;
        memcpy(outer, sub_jb, sizeof outer);
        vm_si = MES_SUB;
        state_push(&s);
        if (!setjmp(sub_jb))
            vm_run();
        memcpy(sub_jb, outer, sizeof outer);
        state_pop(&s);
        vm_si = si;
    }
    vm_wr16(MES_SUB_ACTIVE, 0);
}

static void op_exit(void)                       /* D4 */
{
    text_flush();
    if (vm_rd16(MES_SUB_ACTIVE))
        longjmp(sub_jb, 1);
    longjmp(top_jb, UNWIND_END);
}

/* C1..C5: animation cells and scripts (advbios.md §5.4), unused by NOVA: M5 */
static void op_anim(unsigned op)
{
    unsigned a, b;
    if (op == 0xC1 || op == 0xC2) {
        vm_get_number(&a);
        vm_si++;
        if (op == 0xC1)
            copy_string(MES_FILENAME);
        else
            while (byte_at(vm_si++) != '"')
                ;
    } else if (op == 0xC4) {
        vm_get_number(&a);
        vm_get_number(&b);
    } else {
        vm_get_number(&a);
        vm_get_number(&b);
    }
    lrv_log(ax.hal, LRV_LOG_WARN, "opcode %02X (animation cells): not implemented yet (M5)", op);
}

static void op_curtain(void)                    /* C6: INT F6h AH=0Fh, CH CL DH DL, AL */
{
    unsigned v[5];
    int i;
    for (i = 0; i < 5; i++)
        vm_get_number(&v[i]);
    tl_curtain((int)(v[4] & 0xFF), (int)(v[0] & 0xFF), (int)(v[1] & 0xFF), (int)(v[2] & 0xFF),
               (int)(v[3] & 0xFF));
}

static void op_save_check(void)                 /* C7 */
{
    unsigned n, c;
    bios_select_drive(0, 0);
    if (!vm_get_number(&n))
        n = 10;
    else if (++n > 10)
        n = 10;
    for (c = n & 0xFFFF; c; c--) {
        unsigned valid = save_read(c - 1) == 0xFFFF;
        reg_assign((c + 0x3E8 + (valid ? 0x400 : 0)) & 0xFFFF);
    }
    bios_select_drive(0, byte_at(MES_DRIVES));
}

static void op_load_mem(void)                   /* C8 */
{
    unsigned addr;
    vm_si++;
    copy_string(MES_FILENAME);
    if (!vm_get_number(&addr))
        addr = 0x100;
    if (!mod_load(mem_str(MES_FILENAME), addr))
        load_to(mem_str(MES_FILENAME), addr);
}

static char picture_name[64];

static void op_image_file(void)                 /* C9 */
{
    uint32_t cap;
    uint8_t *buf = bg_picture_buffer(&cap);
    long n;
    vm_si++;
    copy_string(MES_FILENAME);
    n = bios_file_load(mem_str(MES_FILENAME), buf, cap);
    if (n >= 0) {
        ax.bios.piclen = (uint32_t)n;
        snprintf(picture_name, sizeof picture_name, "%.63s", mem_str(MES_FILENAME));
    }
}

static void op_pitch(void)                      /* CA */
{
    unsigned v;
    if (!vm_get_number(&v))
        v = 0;
    bios_set_pitch(v ? v : 0x370);
}

static void op_char_beep(void)                  /* CB */
{
    unsigned v;
    if (!vm_get_number(&v))
        v = 0;
    bt_set_beep(v);
}

static void op_reg_clear(void)                  /* CC */
{
    unsigned a, b, i;
    if (!vm_get_number(&a)) {
        memset(M, 0, 0x80);
        return;
    }
    if (!vm_get_number(&b)) {
        b = a;
        a = 0;
    }
    if (b > 0x3FF)
        b = 0x3FF;
    for (i = a; i <= b; i++)
        M[(i >> 3) & 0xFFFF] &= (uint8_t)~(1u << (i & 7));
}

static void op_exec_mem(void)                   /* CD */
{
    unsigned addr, v, cnt = 0, bx = MES_ARGS + 2;
    long cx;
    vm_get_number(&addr);
    vm_wr16(MES_CALL_TARGET, addr);
    vm_wr16(MES_ARGS, 0);
    vm_wr16(bx, 0xFFFF);
    vm_wr16(bx + 2, 0xFFFF);
    vm_wr16(bx + 4, 0xFFFF);
    for (;;) {
        if (byte_at(vm_si) == '"') {
            vm_wr16(bx, vm_si);
            cnt++;
            bx += 2;
            do
                vm_si++;
            while (byte_at(vm_si) != '"');
            vm_si++;
            continue;
        }
        if (!vm_get_number(&v))
            break;
        vm_wr16(bx, v);
        cnt++;
        bx += 2;
    }
    vm_wr16(MES_ARGS, cnt);
    cx = mod_exec(addr);
    if (cx < 0) {
        lrv_log(ax.hal, LRV_LOG_ERROR, "exec-mem %u: no module loaded there", addr);
        return;
    }
    /* the result (0xE9F0): CH < 0 nothing; CH = 0 -> flag AX := CL != 0, where setting uses
     * flag AX and clearing flag AX - 1 (the original's off-by-one); CH > 0 -> variable letter
     * AL := CL & 15 */
    {
        unsigned rcx = (unsigned)cx & 0xFFFF, rax = ((unsigned long)cx >> 16) & 0xFFFF;
        unsigned ch = rcx >> 8, cl = rcx & 0xFF;
        if (ch & 0x80)
            return;
        if (ch == 0) {
            if (cl) {
                M[((rax & 0x3FF) >> 3) & 0xFFFF] |= (uint8_t)(1u << (rax & 7));
            } else {
                unsigned fb;
                uint8_t mask;
                reg_addr(rax, &fb, &mask);
                M[fb] &= (uint8_t)~mask;
            }
        } else {
            M[(0x80 + (((rax & 0xFF) - 0x41) & 0xFF)) & 0xFFFF] = (uint8_t)(cl & 15);
        }
    }
}

static void op_set_drive(void)                  /* CE */
{
    unsigned a, b;
    vm_get_number(&a);
    vm_get_number(&b);
    M[MES_DRIVES + (a & 1)] = (uint8_t)b;
    bios_select_drive((int)(a & 1), (int)(b & 0xFF));
}

static void op_image_show(void)                 /* CF */
{
    unsigned p, mode, x, y;
    const unsigned blk = MES_SHOW_BLOCK;
    vm_get_number(&p);
    vm_wr16(blk + 0x0C, p);
    vm_wr16(blk + 0x08, 0xFFFF);
    vm_wr16(blk + 0x0A, 0xFFFF);
    vm_wr16(blk + 0x0E, 3);
    if (vm_get_number(&mode)) {
        vm_wr16(blk + 0x0E, mode & 3);
        if (vm_get_number(&x) && vm_get_number(&y)) {
            vm_wr16(blk + 0x08, x);
            vm_wr16(blk + 0x0A, y);
        }
    }
    /* the call the copy protection patches in at 0xEA84 (interpreter.md §7) */
    lrv_sys_trace(&ax.sys, AX_TR_PICTURE, picture_name, 0, vm_rd16(blk + 8), vm_rd16(blk + 10),
              vm_rd16(blk + 12), vm_rd16(blk + 14));
    if (bg_draw_gpc(ax.bios.picbuf, ax.bios.piclen, vm_rd16(blk + 8), vm_rd16(blk + 10),
                    vm_rd16(blk + 12) != 0, vm_rd16(blk + 14)) != 0)
        lrv_log(ax.hal, LRV_LOG_WARN, "image-show: no picture in the buffer");
}

static void op_decrypt(void)                    /* D5 */
{
    unsigned key, a, end;
    vm_get_number(&key);
    if (!key) {
        lrv_log(ax.hal, LRV_LOG_WARN, "decrypt 0: NV.INI's machine code is not run");
        return;
    }
    for (a = vm_si; a < 0xC000; a++)
        M[a] = (uint8_t)((((M[a] >> 4) | (M[a] << 4)) & 0xFF) ^ (key & 0xFF));
    for (end = vm_si; end < 0xC000 && M[end] != 0xFE; end++)
        ;
    (void)end;
}

static void op_sound(void)                      /* D0 */
{
    unsigned w = vm_rd16(vm_si) | 0x2020, n, m;
    if (w == 0x6573) {                          /* "se" */
        vm_si += 2;
        while (byte_at(vm_si) == ' ')
            vm_si++;
        if (byte_at(vm_si) == '"') {
            vm_si++;
            copy_string(MES_FILENAME);
            snd_effect_file(mem_str(MES_FILENAME));
        } else {
            vm_get_number(&n);
            snd_effect((int)n);
        }
        return;
    }
    if (byte_at(vm_si) == '"') {
        vm_si++;
        copy_string(MES_FILENAME);
        snd_stop();
        snd_load_play(mem_str(MES_FILENAME));
        return;
    }
    vm_get_number(&n);
    if (n == 1) {
        if (vm_get_number(&m)) {
            if (m > 0x80)
                m = 0x80;
            snd_volume((int)m - 0x40);
        } else {
            snd_play();
        }
    } else if (n == 2 || n == 3) {
        unsigned dl = vm_get_number(&m) ? (m & 0xFF) : 0x14;
        if (n == 2)
            snd_fade_out((int)dl);
        else
            snd_fade_in((int)dl);
    } else {
        snd_stop();
    }
}

/* fade 0xEB63 */
static void fade_down(unsigned target)
{
    unsigned n, bl;
    if (!vm_get_number(&n))
        n = 0;
    if (!n) {
        bg_set_brightness((int)target);
        return;
    }
    bl = (unsigned)bg_brightness();
    for (;;) {
        bg_set_brightness((int)bl);
        if (!(bl > target))
            break;
        bios_delay(n, 1);
        bl = (bl - 1) & 0xFF;
    }
}

static void fade_up(unsigned target)
{
    unsigned n, bl;
    if (!vm_get_number(&n))
        n = 0;
    if (!n) {
        bg_set_brightness((int)target);
        return;
    }
    bl = (unsigned)bg_brightness();
    for (;;) {
        bg_set_brightness((int)bl);
        if (!(bl < target))
            break;
        bios_delay(n, 1);
        bl = (bl + 1) & 0xFF;
    }
}

static void op_fade(void)                       /* D1 */
{
    unsigned k, v;
    if (!vm_get_number(&k))
        return;
    if (k == 0) {
        fade_down(0);
    } else if (k == 1) {
        fade_up(15);
    } else if (k == 2) {
        if (!vm_get_number(&v))
            return;
        v &= 15;
        if ((unsigned)bg_brightness() <= v)
            fade_up(v);
        else
            fade_down(v);
    } else {
        vm_get_number(&v);
    }
}

static void op_name_load(void)                  /* D2 */
{
    bios_select_drive(0, 0);
    if (bios_file_read("A:\\NAME.DEF", M + MES_SAVEBUF, 256) >= 0)
        memcpy(M + MES_PLAYER, M + MES_SAVEBUF, 26);
    bios_select_drive(0, byte_at(MES_DRIVES));
}

static void op_menu_step(void)                  /* D3 */
{
    unsigned a, b;
    vm_get_number(&a);
    vm_wr16(MES_MENU_STEP_X, a);
    vm_get_number(&b);
    vm_wr16(MES_MENU_STEP_Y, b);
}

static void op_dispatch(unsigned op)
{
    uint16_t at = (uint16_t)(vm_si - 1);
    trace_op(op, at);
    switch (op) {
    case 0xA6: op_text_frame(); break;
    case 0xA7: op_text_pos(); break;
    case 0xA8: op_text_color(); break;
    case 0xA9: op_text_speed(); break;
    case 0xAA: op_text_clear(); break;
    case 0xAB: op_wait(); break;
    case 0xAC: op_delay(); break;
    case 0xAD: vm_op_menu(); break;
    case 0xAE: vm_op_menu2(); break;
    case 0xAF: op_seg_call(); break;
    case 0xB0: op_exec_file(); break;
    case 0xB1: op_mes_jump(); break;
    case 0xB2: op_branch_random(); break;
    case 0xB3: op_branch_cycle(); break;
    case 0xB4: op_branch_var(); break;
    case 0xB5: op_branch_reg(); break;
    case 0xB6: op_input(); break;
    case 0xB7: op_screen_mode(); break;
    case 0xB8: op_scroll(); break;
    case 0xB9: op_define_proc(); break;
    case 0xBA: op_proc(); break;
    case 0xBB: op_repeat(); break;
    case 0xBC: op_if(); break;
    case 0xBD: op_when(); break;
    case 0xBE: op_flag_save(); break;
    case 0xBF: op_flag_load(); break;
    case 0xC0: op_mes_call(); break;
    case 0xC1: case 0xC2: case 0xC3: case 0xC4: case 0xC5: op_anim(op); break;
    case 0xC6: op_curtain(); break;
    case 0xC7: op_save_check(); break;
    case 0xC8: op_load_mem(); break;
    case 0xC9: op_image_file(); break;
    case 0xCA: op_pitch(); break;
    case 0xCB: op_char_beep(); break;
    case 0xCC: op_reg_clear(); break;
    case 0xCD: op_exec_mem(); break;
    case 0xCE: op_set_drive(); break;
    case 0xCF: op_image_show(); break;
    case 0xD0: op_sound(); break;
    case 0xD1: op_fade(); break;
    case 0xD2: op_name_load(); break;
    case 0xD3: op_menu_step(); break;
    case 0xD4: op_exit(); break;
    case 0xD5: op_decrypt(); break;
    case 0xD6: case 0xD7: case 0xD8: break;
    default:
        /* the original indexes outside its handler table; no script does this */
        lrv_log(ax.hal, LRV_LOG_ERROR, "%s %04X: byte %02X is not an opcode",
                ax.sys.script_name ? ax.sys.script_name : "", at, op);
        lrv_sys_trace(&ax.sys, LRV_TR_ERROR, 0, 0, (int)op, (int)at, 0, 0);
        break;
    }
}

/* ---- start-up -------------------------------------------------------------------------- */

void vm_init(void)
{
    static const uint8_t mark[7] = { 0x81, 0x96, 0x81, 0x96, 0x81, 0x96, 0 };
    static const uint8_t player[8] = { 0x81, 0x96, 0x81, 0x96, 0x81, 0x96, 0xFF, 0xFF };
    static const uint16_t show_block[8] = { 0xA800, 0xB000, 0xB800, 0xE000, 0xFFFF, 0xFFFF, 0, 0xFFFF };
    int i;
    if (!ax.mem)
        ax.mem = lrv_xalloc(ax.hal, 0x10000 + 16);
    memset(M, 0, 0x10000 + 16);
    /* the interpreter's initialised data (NV.OVL image) */
    memcpy(M + MES_NAME_MARK, mark, sizeof mark);
    memcpy(M + MES_PLAYER, player, sizeof player);
    for (i = 0; i < 8; i++)
        vm_wr16(MES_SHOW_BLOCK + 2 * (unsigned)i, show_block[i]);
    vm_wr16(MES_COLOUR, 15);
    vm_wr16(MES_SPEED_SKIP, 0xFFFF);
    vm_wr16(MES_FRAME + 4, 79);
    vm_wr16(MES_FRAME + 6, 399);
    vm_wr16(MES_MENU_STEP_X, 1);
    vm_wr16(MES_MENU_STEP_Y, 1);
    vm_wr16(MES_SCREEN_MODE, 1);
    vm_wr16(MES_SCREEN_OLD, 1);
    text_len = 0;
}

void vm_set_messages(const uint8_t *frags, uint32_t size)
{
    /* three fragments ending in FF FF; at their original addresses when they fit there (the
     * original's own), else in memory the model has free above the interpreter (0xEE80-) */
    uint32_t i = 0, start = 0;
    unsigned k = 0, fits = 1, at = 0xEE80;
    uint32_t len[3] = { 0, 0, 0 }, off[3] = { 0, 0, 0 };
    for (; i + 1 < size && k < 3; i++)
        if (frags[i] == 0xFF && frags[i + 1] == 0xFF) {
            off[k] = start;
            len[k] = i + 2 - start;
            k++;
            start = i + 2;
            i++;
        }
    if (k < 3)
        return;
    if (len[0] > MES_MSG_EMPTY - MES_MSG_SAVE || len[1] > MES_MSG_LOAD - MES_MSG_EMPTY ||
        len[2] > MES_SHOW_BLOCK - MES_MSG_LOAD)
        fits = 0;
    for (k = 0; k < 3; k++) {
        unsigned a = fits ? (k == 0 ? MES_MSG_SAVE : k == 1 ? MES_MSG_EMPTY : MES_MSG_LOAD) : at;
        if (a + len[k] > 0x10000)
            return;
        memcpy(M + a, frags + off[k], len[k]);
        msg_addr[k] = (uint16_t)a;
        at += len[k];
    }
}

void vm_run_game(const char *start)
{
    volatile int first = 1;
    int r;
    /* restart 0xDC97: the start script's name at 0x9A, loaded to 0x9000 */
    if (!first)
        return;
    strncpy((char *)M + MES_NAME, start, 0xFD - MES_NAME - 1);
    if (load_to(start, MES_SCRIPT) < 0) {
        lrv_fatal(ax.hal, "cannot find message file %s", start);
        return;
    }
    tl_curtain(0xFF, 0, 0, 0x9F, 0x63);  /* restart 0xDCF6: F6h AX=0FFFh, DX=9F63h */
    r = setjmp(top_jb);
    if (r == 0 || r == UNWIND_JUMP) {
        ax.sys.script_name = (const char *)M + MES_NAME;
        lrv_sys_trace(&ax.sys, AX_TR_SCRIPT, (const char *)M + MES_NAME, 0, 0, 0, 0, 0);
        if (r == 0) {                   /* restart 0xDD0E: the start script by a bare `run` */
            vm_si = MES_SCRIPT;
            vm_run();
        } else {                        /* mes-jump 0xE5B6: through run_saved */
            vm_run_saved(MES_SCRIPT);
        }
    }
    text_flush();
    first = 0;
}
