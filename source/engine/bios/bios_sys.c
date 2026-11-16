/* SPDX-License-Identifier: GPL-3.0-or-later */
/* INT F1h, system services, waits and click maps (docs/re/advbios.md §4.1, §6.3, §6.4). The
 * waits count AdvBIOS's 20 ms ticks, which the engine derives from its frames (bios_frame_tick); each
 * iteration of a waiting loop is one frame, where the original polled in a busy loop. */
#include <string.h>
#include "ax.h"
#include "bios/bios.h"

void bios_init(void)
{
    struct ax_bios *b = &ax.bios;
    uint8_t *pic = b->picbuf;
    memset(b, 0, sizeof *b);
    b->picbuf = pic;
    /* AdvBIOS's initialised DGROUP (advbios.md §5.2 "Defaults") */
    b->win[0] = 0; b->win[1] = 0; b->win[2] = 79; b->win[3] = 399;
    b->colour = 15;
    b->delay_skip = 0xFFFF;
    b->lip_colour[0] = b->lip_colour[1] = 0x10;      /* never matches a colour */
    b->rng = 1;
    b->drive[0] = 0;
    b->drive[1] = 1;
    memset(ax.mailbox, 0, sizeof ax.mailbox);
    bg_init();
    mouse_init();
}

void bios_shutdown(void)
{
    bg_shutdown();
}

/* AdvBIOS's timer interrupt counts 20 ms ticks (DS:00F8); the engine's clock is the frame */
void bios_frame_tick(void *unused)
{
    (void)unused;
    ax.tick_acc += AX_TICK_NUM;
    while (ax.tick_acc >= AX_TICK_DEN) {
        ax.tick_acc -= AX_TICK_DEN;
        ax.tick++;
    }
}

/* ---- the keyboard (INT 18h) ------------------------------------------------------------- */

/* The presses the frames delivered so far go into the BIOS buffer as the PC-98 reports them:
 * scan code and character. A host key the PC-98 does not have is no press; a press that finds
 * the buffer full is lost, as on the machine. */
static void kbd_fill(void)
{
    struct ax_bios *b = &ax.bios;
    struct lrv_keypress k;
    struct lrv_pc98_key pk;
    while (lrv_sys_key_read(&ax.sys, &k))
        if (lrv_pc98_keypress(&k, 0, &pk) && b->kcount < BIOS_KEYQ)
            b->kbuf[(b->khead + b->kcount++) % BIOS_KEYQ] = pk;
}

int bios_key_sense(void)
{
    kbd_fill();
    return ax.bios.kcount > 0;
}

unsigned bios_key_read(void)
{
    struct ax_bios *b = &ax.bios;
    struct lrv_pc98_key k;
    kbd_fill();
    if (!b->kcount)
        return 0xFFFFu;
    k = b->kbuf[b->khead];
    b->khead = (b->khead + 1) % BIOS_KEYQ;
    b->kcount--;
    return ((unsigned)k.scan << 8) | k.chr;
}

int bios_key_down(int scan)
{
    uint8_t map[LRV_PC98_KEYMAP_BYTES];
    lrv_pc98_keymap(&ax.sys.in, 0, map);
    return lrv_pc98_key_down(map, scan);
}

/* RNGAdvance 0000:01FE: state * 000F4241h + 3619h, result = high word & 7FFFh */
unsigned bios_random(void)
{
    ax.bios.rng = ax.bios.rng * 0x000F4241u + 0x3619u;
    return (ax.bios.rng >> 16) & 0x7FFF;
}

/* wait_skip_check 0000:03B4 / text_skip_check 0000:0C48: SHIFT held (INT 18h AH=02h bit 0)
 * or the right button down (INT 33h AX=6) */
int bios_skip_held(void)
{
    return bios_key_down(LRV_PC98_K_SHIFT) || mouse_right() != 0;
}

/* AH=0Fh AL=0 (0000:0602): the STOP-key prompt arrives with M5; the host's quit request
 * (window close) counts as a confirmed quit */
int bios_quit_poll(void)
{
    if (lrv_sys_quitting(&ax.sys))
        ax.bios.quit_flag = 1;
    return ax.bios.quit_flag ? 0xFFFF : 0;
}

int bios_quit_flag(void)
{
    return ax.bios.quit_flag ? 0xFFFF : 0;
}

/* kbd_drain 0000:035A */
static void kbd_drain(void)
{
    while (bios_key_sense())
        bios_key_read();
}

/* wait_release_flush 0000:033C: until the left button is up and no key is waiting */
static void wait_release_flush(void)
{
    for (;;) {
        if (mouse_left()) {
            if (bios_quit_poll())
                return;
            lrv_sys_frame_wait(&ax.sys);
            continue;
        }
        if (!bios_key_sense())
            return;
        bios_key_read();
    }
}

static int advance_key(void)
{
    unsigned k = bios_key_read() >> 8;
    return k == LRV_PC98_K_RETURN || k == LRV_PC98_K_SPACE;
}

/* apiF1_07_WaitInput 0000:02FC */
void bios_wait_input(void)
{
    int leave = AX_LEAVE_KEY;
    bg_anim_mode(1);
    wait_release_flush();
    lrv_sys_trace(&ax.sys, LRV_TR_WAIT, 0, 0, AX_WAIT_KEY, 0, 0, 0);
    for (;;) {
        bg_anim_poll();
        bios_random();
        if (bios_quit_poll()) {
            leave = AX_LEAVE_QUIT;
            break;
        }
        if (mouse_left()) {
            leave = AX_LEAVE_CLICK;
            break;
        }
        if (bios_key_sense()) {
            if (advance_key())
                break;
            continue;                   /* other keys are discarded */
        }
        lrv_sys_frame_wait(&ax.sys);
    }
    kbd_drain();
    bg_anim_mode(0);
    lrv_sys_trace(&ax.sys, LRV_TR_WAIT, 0, 0, AX_WAIT_KEY, 1, leave, 0);
}

/* apiF1_08_WaitInputTimeout 0000:0364 */
void bios_wait_input_timeout(unsigned ticks, int skippable)
{
    uint32_t end;
    int leave = AX_LEAVE_TIMEOUT;
    bg_anim_mode(1);
    wait_release_flush();
    end = ax.tick + (ticks & 0xFFFF);
    lrv_sys_trace(&ax.sys, LRV_TR_WAIT, 0, 0, AX_WAIT_KEY, 0, (int)ticks, 0);
    while ((int32_t)(end - ax.tick) > 0) {
        bg_anim_poll();
        if (bios_quit_poll()) {
            leave = AX_LEAVE_QUIT;
            break;
        }
        if (skippable && bios_skip_held()) {
            leave = AX_LEAVE_SKIP;
            break;
        }
        if (mouse_left()) {
            leave = AX_LEAVE_CLICK;
            break;
        }
        if (bios_key_sense()) {
            if (advance_key()) {
                leave = AX_LEAVE_KEY;
                break;
            }
            continue;
        }
        lrv_sys_frame_wait(&ax.sys);
    }
    kbd_drain();
    bg_anim_mode(0);
    lrv_sys_trace(&ax.sys, LRV_TR_WAIT, 0, 0, AX_WAIT_KEY, 1, leave, 0);
}

static void timed(unsigned ticks, int skippable, int anim)
{
    uint32_t end = ax.tick + (ticks & 0xFFFF);
    int traced = ticks > 1, leave = AX_LEAVE_TIMEOUT;
    if (anim)
        bg_anim_mode(1);
    if (traced)
        lrv_sys_trace(&ax.sys, LRV_TR_WAIT, 0, 0, AX_WAIT_TICKS, 0, (int)ticks, 0);
    while ((int32_t)(end - ax.tick) > 0) {
        if (anim)
            bg_anim_poll();
        if (bios_quit_poll()) {
            leave = AX_LEAVE_QUIT;
            break;
        }
        if (skippable && bios_skip_held()) {
            leave = AX_LEAVE_SKIP;
            break;
        }
        lrv_sys_frame_wait(&ax.sys);
    }
    if (anim)
        bg_anim_mode(0);
    if (traced)
        lrv_sys_trace(&ax.sys, LRV_TR_WAIT, 0, 0, AX_WAIT_TICKS, 1, leave, 0);
}

/* apiF1_09_Delay 0000:03F0 */
void bios_delay(unsigned ticks, int skippable)
{
    timed(ticks, skippable, 0);
}

/* apiF1_0A_DelayAnim 0000:040E */
void bios_delay_anim(unsigned ticks, int skippable)
{
    timed(ticks, skippable, 1);
}

/* AH=04h / 05h: the beeper (port 37h); its sound arrives with M5 */
void bios_beep(int on)
{
    ax.beeper_on = on;
}

/* AH=06h: DX = 0 -> 880, else clamped to 19..32767 */
void bios_set_pitch(unsigned dx)
{
    dx &= 0xFFFF;
    if (!dx)
        dx = 880;
    if (dx < 19)
        dx = 19;
    if (dx > 32767)
        dx = 32767;
    ax.bios.pitch = dx;
}

/* ---- click maps (advbios.md §6.3) ------------------------------------------------------- */

/* apiF1_0C_LoadHitMap 0000:0462 */
int bios_load_clickmap(const char *name)
{
    uint8_t f[0x7D5];
    long n = bios_file_read(name, f, sizeof f);
    unsigned need, bl, cl, bh, ch, i;
    lrv_sys_trace(&ax.sys, AX_TR_LOAD, name, 0, -1, (int)n, 0, 0);     /* a0 = -1: a click map */
    uint8_t *map = &ax.bios.clickmap[0][0];
    if (n < 5 || f[0] != 0)
        return -1;
    need = ((unsigned)f[3] * f[4] + 1) / 2 + 5;
    if (need > (unsigned)n)
        return -1;
    memset(map, 0, sizeof ax.bios.clickmap);
    bl = f[1];
    bh = (uint8_t)(f[3] + f[1]);
    cl = f[2];
    ch = (uint8_t)(f[4] + f[2]);
    /* hitmap_put_nibble 0000:04F3: cell (bl, cl), 80 cells per row, ORed in */
#define PUT(v) do { unsigned c_ = cl * 80u + bl; if (c_ < 4000u) map[c_] |= (uint8_t)((v) & 15); } while (0)
    for (i = 5; cl < ch; i++) {
        uint8_t b = i < (unsigned)n ? f[i] : 0;
        PUT(b >> 4);
        bl = (uint8_t)(bl + 1);
        if (bl >= bh) {
            cl = (uint8_t)(cl + 1);
            bl = f[1];
        }
        if (cl >= ch)
            break;
        PUT(b);
        bl = (uint8_t)(bl + 1);
        if (bl >= bh) {
            cl = (uint8_t)(cl + 1);
            bl = f[1];
        }
    }
#undef PUT
    return 0;
}

/* apiF1_0D_WaitHitMap 0000:0518: AL bit 0 = ignore the right button, bit 1 = ignore clicks
 * outside every region */
unsigned bios_click_wait(int flags)
{
    unsigned id = 0, x, y;
    mouse_show(1);
    lrv_sys_trace(&ax.sys, LRV_TR_WAIT, 0, 0, AX_WAIT_CLICK, 0, flags, 0);
restart:
    while (mouse_buttons()) {
        if (bios_quit_poll())
            break;
        lrv_sys_frame_wait(&ax.sys);
    }
    for (;;) {
        if (bios_quit_poll()) {
            id = 0;
            break;
        }
        mouse_state(&x, &y);
        if (mouse_right()) {
            if (flags & 1)
                goto restart;
            id = 0;
            break;
        }
        if (mouse_left()) {
            id = ax.bios.clickmap[(y >> 3) % 50][(x >> 3) % 80] & 15;
            if (id || !(flags & 2))
                break;
            goto restart;
        }
        lrv_sys_frame_wait(&ax.sys);
    }
    mouse_show(0);
    lrv_sys_trace(&ax.sys, LRV_TR_WAIT, 0, 0, AX_WAIT_CLICK, 1, AX_LEAVE_CLICK, (int)id);
    return id;
}
