/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Menus: `menu` (AD) and `menu2` (AE), the interpreter's 0xE042-0xE47A (docs/re/interpreter.md §4).
 * The item table at 0xD026 holds 16 entries of {index, x1, y1, x2, y2}; x in byte columns, y
 * in lines. Items whose conditions fail are not laid out but keep their index. */
#include <string.h>
#include "ax.h"
#include "bios/bios.h"
#include "vm/mes.h"

#define M (ax.mem)
#define ITEM(i) (MES_MENU_ITEMS + 9u * (unsigned)(i))

/* menu_highlight 0xE3A1: invert item cx's rectangle (pointer hidden meanwhile) */
static void highlight(unsigned cx)
{
    unsigned bx = ITEM(cx & 0xFF);
    uint16_t rect[4];
    int i;
    mouse_show(0);
    if (M[bx] == 0xFF)
        return;
    for (i = 0; i < 4; i++)
        rect[i] = vm_rd16(bx + 1 + 2 * (unsigned)i);
    bt_invert_rect(rect);
    mouse_show(1);
}

/* menu_mouse_to_item 0xE238: the pointer to the item's right edge, one line above its bottom */
static void mouse_to_item(void)
{
    unsigned bx = ITEM(vm_rd16(MES_MENU_CUR));
    unsigned cx = ((vm_rd16(bx + 5) << 3) + 7 - 1) & 0xFFFF;
    unsigned dx = (vm_rd16(bx + 7) - 1) & 0xFFFF;
    mouse_set_pos(cx, dx);
}

/* menu_item_at_mouse 0xE259: AX = the item index under the pointer, BX = its table slot */
static unsigned item_at_mouse(unsigned *slot)
{
    unsigned x, y, i;
    mouse_state(&x, &y);
    x >>= 3;
    for (i = 0; i < 16; i++) {
        unsigned di = ITEM(i);
        if (M[di] == 0xFF)
            break;
        if (x < vm_rd16(di + 1) || x > vm_rd16(di + 5) || y < vm_rd16(di + 3) || y > vm_rd16(di + 7))
            continue;
        *slot = i;
        return M[di];
    }
    return 0xFFFF;
}

/* menu_layout_item 0xE2D8: run one item at its position in colour `ch`; AL = alt_exec's */
static int layout_item(unsigned bx, unsigned ch)
{
    int r;
    unsigned x, y;
    vm_wr16(MES_COLOUR, ch & 0xFF);
    if (vm_rd16(bx + 1) != 0xFFFF) {
        vm_wr16(MES_CUR_X, vm_rd16(bx + 1));
        vm_wr16(MES_CUR_Y, vm_rd16(bx + 3));
    } else {
        vm_wr16(MES_CUR_X, vm_rd16(bx - 8));
        vm_wr16(MES_CUR_Y, (vm_rd16(bx - 6) + 20) & 0xFFFF);
    }
    vm_wr16(MES_MENU_RECT, vm_rd16(MES_CUR_X));
    vm_wr16(MES_MENU_RECT + 2, vm_rd16(MES_CUR_Y));
    r = vm_alt_exec();
    bt_cursor(&x, &y);
    vm_wr16(MES_CUR_X, x);
    vm_wr16(MES_CUR_Y, y);
    vm_wr16(MES_MENU_RECT + 4, (x - 1) & 0xFFFF);
    vm_wr16(MES_MENU_RECT + 6, (y + 15) & 0xFFFF);
    return r;
}

/* menu_layout 0xE294: the head, then the items */
static void layout(void)
{
    unsigned cl = 0, bx = MES_MENU_ITEMS;
    uint16_t si;
    bt_set_cursor(vm_rd16(MES_FRAME), vm_rd16(MES_FRAME + 2));
    si = vm_si;
    vm_run_saved(si);
    vm_wr16(MES_MENU_COUNT, 0);
    for (;;) {
        if (layout_item(bx, 15) == 0) {
            int k;
            M[bx] = (uint8_t)cl;
            for (k = 0; k < 4; k++)
                vm_wr16(bx + 1 + 2 * (unsigned)k, vm_rd16(MES_MENU_RECT + 2 * (unsigned)k));
            bx += 9;
            vm_wr16(MES_MENU_COUNT, vm_rd16(MES_MENU_COUNT) + 1);
        }
        cl = (cl + 1) & 0xFF;
        if (M[(vm_si - 1) & 0xFFFF] != 0xA4)
            break;
    }
}

static void move_to(unsigned n)
{
    highlight(vm_rd16(MES_MENU_CUR));
    vm_wr16(MES_MENU_CUR, n);
    highlight(n);
}

/* menu_select 0xE048: returns 0 on a choice (S = the item's index), FFFFh on cancel */
static unsigned menu_select(int kind)
{
    static const uint16_t saved_addr[11] = {
        0xD008, 0xD00A, 0xD00C, 0xD00E, 0xD014, 0xD012, 0xD016, 0xD018, 0xD01A, 0xD01C, 0xD01E
    };
    uint16_t saved[11];
    unsigned emu, result = 0, i, bx;
    for (i = 0; i < 11; i++)
        saved[i] = vm_rd16(saved_addr[i]);
    emu = mouse_emulation();
    mouse_set_emulation(0);
    vm_wr16(MES_SPEED, 0);
    vm_wr16(MES_SPEED_SKIP, 0xFFFF);
    bt_set_delay(0, 0xFF);
    vm_wr16(MES_COLOUR, 15);
    bt_set_colour(15);
    for (i = 0; i < 16; i++) {
        M[ITEM(i)] = 0xFF;
        vm_wr16(ITEM(i) + 1, 0xFFFF);
    }
    for (bx = MES_MENU_ITEMS;; bx += 9) {
        unsigned v;
        if (!vm_get_number(&v))
            break;
        vm_wr16(bx + 1, v);
        vm_get_number(&v);
        vm_wr16(bx + 3, v);
    }
    layout();
    mouse_show(1);
    vm_wr16(MES_MENU_CUR, 0);
    if (M[MES_MENU_ITEMS] == 0xFF)
        goto choose;                    /* an empty list selects at once */
    highlight(0);
    mouse_to_item();
    if (LRV_TRACING(&ax.sys)) {
        static const uint8_t none[1] = { 0 };
        const uint8_t *items[1] = { none };
        lrv_sys_trace_items(&ax.sys, AX_TR_MENU, items, 0, kind);
    }
    lrv_sys_trace(&ax.sys, LRV_TR_WAIT, 0, 0, AX_WAIT_MENU, 0, (int)vm_rd16(MES_MENU_COUNT), 0);
    for (;;) {
        /* wait until no button is down, flush the keys */
        while (mouse_buttons()) {
            if (bios_quit_poll())
                vm_quit();
            lrv_sys_frame_wait(&ax.sys);
        }
        while (bios_key_sense())
            bios_key_read();
        for (;;) {
            unsigned n, slot = 0, key;
            if (bios_quit_poll())
                vm_quit();              /* abort_poll0: unwinds to the top level */
            if (mouse_right())
                goto cancel;
            n = item_at_mouse(&slot);
            if (n != 0xFFFF) {
                if (slot != vm_rd16(MES_MENU_CUR)) {
                    move_to(slot);
                } else if (mouse_left()) {
                    goto choose;
                }
            }
            if (!bios_key_sense()) {
                lrv_sys_frame_wait(&ax.sys);
                continue;
            }
            key = bios_key_read() >> 8;
            if (bios_quit_poll())
                vm_quit();
            if (key == 0x3C || key == 0x48) {           /* → */
                unsigned a = (vm_rd16(MES_MENU_CUR) + vm_rd16(MES_MENU_STEP_X)) & 0xFFFF;
                if (a >= vm_rd16(MES_MENU_COUNT))
                    a = 0;
                move_to(a);
                mouse_to_item();
            } else if (key == 0x3B || key == 0x46) {    /* ← */
                int a = (int16_t)(vm_rd16(MES_MENU_CUR) - vm_rd16(MES_MENU_STEP_X));
                if (a < 0)
                    a = vm_rd16(MES_MENU_COUNT) - 1;
                move_to((unsigned)a & 0xFFFF);
                mouse_to_item();
            } else if (key == 0x3A || key == 0x43) {    /* ↑ */
                int a = (int16_t)(vm_rd16(MES_MENU_CUR) - vm_rd16(MES_MENU_STEP_Y));
                if (a < 0)
                    a += vm_rd16(MES_MENU_STEP_Y);
                move_to((unsigned)a & 0xFFFF);
                mouse_to_item();
            } else if (key == 0x3D || key == 0x4B) {    /* ↓ */
                unsigned a = (vm_rd16(MES_MENU_CUR) + vm_rd16(MES_MENU_STEP_Y)) & 0xFFFF;
                if (a >= vm_rd16(MES_MENU_COUNT))
                    a = (a - vm_rd16(MES_MENU_STEP_Y)) & 0xFFFF;
                move_to(a);
                mouse_to_item();
            } else if (key == 0x00 || key == 0x0F) {
                goto cancel;
            } else if (key == 0x1C || key == 0x34) {
                goto choose;
            }
            break;                      /* back to waiting for the buttons to be up */
        }
        continue;
cancel:
        if (vm_rd16(MES_MENU_CANCEL)) {
            result = 0xFFFF;
            goto leave;
        }
    }
choose:
    {
        unsigned cur = vm_rd16(MES_MENU_CUR);
        M[MES_VAR_S] = M[ITEM(cur)];
        result = 0;
    }
leave:
    lrv_sys_trace(&ax.sys, LRV_TR_WAIT, 0, 0, AX_WAIT_MENU, 1,
                  result ? AX_LEAVE_SKIP : AX_LEAVE_KEY, 0);
    lrv_sys_trace(&ax.sys, AX_TR_MENU_SEL, 0, 0, result ? -1 : M[MES_VAR_S], kind, 0, 0);
    mouse_show(0);
    mouse_set_emulation(emu);
    for (i = 11; i-- > 0;)
        vm_wr16(saved_addr[i], saved[i]);
    vm_state_apply();
    return result;
}

void vm_op_menu(void)                           /* AD 0xE042 */
{
    vm_wr16(MES_MENU_CANCEL, 0);
    menu_select(0);
}

/* AE 0xE3CB: the verbs with the head's layout; then the chosen verb's nouns, cancel allowed */
void vm_op_menu2(void)
{
    unsigned si, bx, cl, ax_;
    /* copy the head and the verbs (without their noun lists) to the work buffer at 0xD0D0 */
    si = vm_copy_block(MES_MENU2_BUF, 0xA3, 0xA2);
    bx = MES_MENU2_BUF + (si - vm_si);
    vm_si = (uint16_t)si;
    vm_wr16(MES_MENU2_SI, si);
    vm_wr16(MES_MENU2_BX, bx);
    for (;;) {
verbs:
        for (;;) {
            unsigned end = vm_copy_block(bx, 0xA1, 0xA0);
            bx += end - vm_si;
            vm_si = (uint16_t)end;
            M[(bx - 1) & 0xFFFF] = 0xA4;
            vm_skip_block(0xA0, 0xA1);
            if (M[vm_si] == 0xA3)
                break;
        }
        M[(bx - 1) & 0xFFFF] = 0xA3;
        vm_wr16(bx, 0xFFFF);
        vm_si = MES_MENU2_BUF;
        vm_wr16(MES_MENU_CANCEL, 0);
        menu_select(1);
        M[MES_VAR_V] = M[MES_VAR_S];
        vm_text_clear_default();
        /* the chosen verb's nouns */
        vm_si = vm_rd16(MES_MENU2_SI);
        bx = vm_rd16(MES_MENU2_BX);
        cl = (M[MES_VAR_S] + 1) & 0xFF;
        do
            vm_skip_block(0xFF, 0xA0);
        while (--cl & 0xFF);
        bx = vm_rd16(MES_MENU2_BX);
        {
            unsigned end = vm_copy_block(bx, 0xA0, 0xA1);
            bx += end - vm_si;
        }
        M[(bx - 1) & 0xFFFF] = 0xA3;
        vm_si = MES_MENU2_BUF;
        vm_wr16(MES_MENU_CANCEL, 0xFFFF);
        ax_ = menu_select(2);
        if (ax_ == 0)
            break;
        vm_text_clear_default();
        vm_si = vm_rd16(MES_MENU2_SI);
        bx = vm_rd16(MES_MENU2_BX);
        goto verbs;
    }
    M[MES_VAR_N] = M[MES_VAR_S];
    ax_ = M[MES_VAR_S] | (M[MES_VAR_V] << 8);
    if (ax_ != vm_rd16(MES_MENU2_LAST))
        vm_wr16(MES_CYCLE, 0x0F);
    vm_wr16(MES_MENU2_LAST, ax_);
    vm_si = vm_rd16(MES_MENU2_SI);
    vm_skip_block(0xA2, 0xA3);
}
