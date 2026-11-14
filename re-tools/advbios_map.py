#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""advbios_map - carry Valley Bell's labels for AdvBIOS 0.54 over to NOVA's NV.OV1.

Valley Bell's annotated IDA disassembly (Adv98V/DengekiNurse/ADVBIOS.DEC2.asm,
https://github.com/ValleyBell/ -- GPL-2 code / CC-BY-SA docs; credit: Valley Bell)
describes the AdvBIOS build shipped with "Dengeki Nurse".  NOVA ships a build
of the same version whose code is byte-identical apart from data addresses and
whose data segment is 48 bytes shorter.  This tool

  1. walks the .asm text next to the Dengeki Nurse binary and recovers the
     image address of every label (IDA auto names carry their address;
     user-named labels get theirs by decoding the binary in step with the
     text),
  2. for every code label builds a byte pattern of the code that follows it
     in which 16-bit displacement / immediate operands are wildcards and
     searches NOVA's image for it (so the match does not assume that the two
     builds are aligned),
  3. pairs the wildcarded operands of matched code to learn how data
     addresses moved (DN DGROUP offset -> NOVA DGROUP offset) and maps data
     labels through that table (falling back to the shift of the nearest
     mapped neighbour, marked "interp"),
  4. writes  SEG:OFF<TAB>name<TAB>comment  for NOVA.  Names from the NOVA
     analysis (table NOVA_NAMES below, plus an optional --own TSV) take
     precedence and are merged; VB-derived rows are marked "VB" in the
     comment and a replaced VB name is kept as "[VB: name]".

Usage:
  advbios_map.py --asm ADVBIOS.DEC2.asm --dn ADVBIOS.DEC2.OVL --nova NV.OV1
                 [--own own.tsv] [--no-own] [--all] --out advbios-names.tsv

  --all   also emit IDA auto-named *functions* (sub_xxxxx) that matched, as
          "dn_sub_xxxxx" (useful to cross-reference with the .asm)
"""
import argparse
import collections
import difflib
import re
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dis16 import Image, Analysis, load_names  # noqa: E402

IDA_BASE = 0x10000          # IDA loaded the image at segment 1000h
AUTO = re.compile(r'^(sub|loc|locret|byte|word|dword|unk|off|asc|stru|algn|'
                  r'nullsub|seg)_([0-9A-F]+)$')
DIRECTIVES = {'assume', 'align', 'db', 'dw', 'dd', 'org', 'end', 'public',
              'extrn', '.686p', '.mmx', '.model'}
LABEL_LINE = re.compile(r'^([A-Za-z_@?$][\w@?$]*)(:|\s+proc\s+(near|far)|'
                        r'\s+(db|dw|dd)\b|\s*=|\s+endp|\s+ends|\s+segment)?')

# Names from the analysis of NOVA's own NV.OV1 (docs/re/advbios.md).
# SEG:OFF|name|comment   (comment starting with "data" = not code)
NOVA_NAMES = """\
0000:0010|main|main(argc, argv): DoMainInit, then spawn child "NV.Ovl" with our arguments
0000:00A2|init_screen_state|16-colour mode, default palette, clear both pages, show page 0, mouse reset, default beep pitch
0000:01EC|apiF1_00_GetVersion|AX=3600h (AH=54 minor), BH=0
0000:02A4|apiF1_04_BeepOn|port 37h <- 06h
0000:02AA|apiF1_05_BeepOff|port 37h <- 07h
0000:02B0|apiF1_06_SetBeepFreq|DX=pitch (0 -> 880); programs PIT counter 1 (3FDFh/3FDBh)
0000:02FC|apiF1_07_WaitInput|wait for click / Return / Space, animations running
0000:033C|wait_release_flush|wait until left button released and key buffer empty
0000:035A|kbd_drain|drop all pending keys (INT 18h AH=1/0)
0000:0364|apiF1_08_WaitInputTimeout|like 07 with CX-tick timeout, AL=skippable
0000:03B4|wait_skip_check|if [00F6]: NZ when SHIFT held or right button down
0000:03CC|anim_poll|every 2 ticks call anim_step (0290:07F4)
0000:03E0|anim_poll_far|far wrapper used by INT F3 AH=0F
0000:03F0|apiF1_09_Delay|wait CX ticks (quit check + optional skip), no animation
0000:040E|apiF1_0A_DelayAnim|wait CX ticks with animations
0000:0438|apiF1_0B_FlushKeys|reset BIOS keyboard buffer (0:0524..0528)
0000:0462|apiF1_0C_LoadHitMap|read click-map file DS:DX and expand to 80x50 nibble map
0000:04F3|hitmap_put_nibble|
0000:0518|apiF1_0D_WaitHitMap|wait for a click, return region id under the cursor
0000:057E|apiF1_0E_TickCallback|AL=0 set /1 get /2 start /3 stop /4 reset periodic far callback
0000:0600|tick_callback_default|retf
0000:0602|apiF1_0F_QuitCheck|AL=0 STOP-key quit prompt /1 get flag /2 disable /3 enable
0000:0708|apiF1_10_ExitProcs|AL=0 register /1 remove /2 call+remove /3 call all (max 15)
0000:0789|exitproc_find_bx|
0000:07B2|exitproc_remove|
0000:0808|exitproc_index_of|
0000:082A|exitproc_new_handle|
0000:0846|apiF1_11_GetCpuType|AL=0..5 (8086,V30,186,286,386,486+), AH=1 if PE set
0000:08A0|tick_rearm|INT 1Ch AH=02h CX=2 ES:BX=Int_ClockTick (one-shot 20 ms)
0000:0936|apiF6_00_DetectEGC|AX=FFFFh if EGC present else 0 (cached in [0196])
0000:09F0|egc_on|
0000:0A04|egc_off|
0000:0A26|apiF6_01_SetWindow|DS:SI -> x0,y0,x1,y1 (x in 8-px columns, y in lines)
0000:0A5C|clamp_sort_pair|
0000:0A6E|apiF6_02_GetWindow|ES:DI <- 4 words
0000:0A7A|apiF6_03_SetColor|AL&0Fh
0000:0A80|apiF6_04_GetColor|
0000:0A88|apiF6_05_SetCursor|CX=column, DX=line
0000:0A92|apiF6_06_GetCursor|
0000:0AA0|apiF6_07_SetCharDelay|DX=ticks per char, AL=skippable flag
0000:0AAA|apiF6_08_SetCharBeep|DX=beep ticks per char (0=off)
0000:0BBE|draw_glyph_opaque_unused|unreferenced plane-wise glyph writer
0000:0C36|text_wait_ticks|wait CX ticks, abort on text_skip_check
0000:0C48|text_skip_check|if [01A8]: NZ when SHIFT held or right button down
0000:0C60|is_punctuation_jis|AX=1 for JIS 2121..212A, 2144, 2145 [VB: GetJISCharWait]
0000:0C7C|text_newline|x=x0; y+=20, wrap to y0 when y+20 >= y1
0000:0CC8|apiF6_0B_ClearWindow|fill window with colour AL, cursor home
0000:0CE0|apiF6_0C_ClearScreen|fill 640x400 with colour AL
0000:0CEC|apiF6_0D_FillRect|DS:SI -> rect, AL=colour
0000:0CF8|rect_to_vram|DI=offset, CX=bytes, DX=lines
0000:0D12|grcg_fill|TDW fill
0000:0D64|apiF6_0E_InvertRect|DS:SI -> rect, XOR all planes
0000:0D90|xor_plane_rect|
0000:0DA6|apiF6_0F_TextCurtain|text-layer semigraphic dissolve; AL<=7 cover with colour, else uncover
0000:0E56|curtain_cell|
0000:0EA2|apiF6_10_ScrollWindow|AL=0 up 1 down 2 left 3 right, CX=steps
0000:0EA6|apiF6_11_ScrollRect|same on rect DS:SI
0000:0EEE|scroll_dispatch|
0000:0F56|scroll_vertical|
0000:0F86|scroll_horizontal|
0000:0FA4|scroll_v_step_cpu|
0000:102E|scroll_h_step_cpu|
0000:109A|scroll_v_step_egc|
0000:10F4|scroll_h_step_egc_unused|unreferenced
0000:1168|egc_setup_copy|
0000:1188|xy_to_vram|
0000:1198|apiF6_12_Nop|returns nothing [VB: apiF6_12_GetBold]
0000:119C|apiF6_13_Bold|AL=0/1 set bold, AL>1 get -> AL
0000:1316|tram_put_kanji|
0000:1338|wait_no_input|drain keys, wait buttons released
0000:134A|wait_any_input|wait for key or button
0000:135C|beep_30_vsync|
0000:1466|apiF2_03_GetDiskId|AL=drive index -> AL=disk number or FFh+CF
0000:1496|read_volume_label|AL=drive (0=A) -> 11 chars at [1878]; AX=0 ok
0000:153C|label_matches_boot|compare first 10 chars with boot-disk label
0000:15B8|tram_save_box|
0000:15FC|tram_restore_box|
0000:1662|apiF2_05_ReadFileN|DS:DX name, ES:BX buffer, CX max -> AX bytes
0000:16A4|apiF2_06_MakePath|DS:DX name -> ES:BX normalised "X:name"
0000:16FA|apiF2_08_SetExpectedDisk|AL=drive index, DL=disk number
0000:179E|selfcheck_banner|checksum of DS:0000..00DF must be A177h
0000:17B6|atexit_init|
0000:17BC|atexit_add|max 16 near procs
0000:180C|spawn|INT 21h AX=4B00h, program name = arg, tail built from argv
0000:1864|build_cmdtail|
0000:191C|cpu_detect|
0000:198E|parse_cmdline|builds argc/argv from PSP:80h
0000:1A4E|show_confidential_notice_unused|unreferenced: verify + print XOR-FFh notice
01AB:0206|mouse_reset|
01AB:01A8|mouse_irq_mask|
01AB:01BC|mouse_irq_unmask|
01AB:01FC|api33_00_Reset|AX=FFFFh
01AB:023E|api33_01_Show|
01AB:0250|api33_02_Hide|
01AB:025A|cursor_erase_if_shown|
01AB:0266|cursor_draw_if_shown|
01AB:0272|api33_03_GetState|AX=left, BX=right, CX=x, DX=y
01AB:028E|api33_04_SetPos|CX,DX
01AB:02B8|api33_05_LeftButton|AX
01AB:02C0|api33_06_RightButton|AX
01AB:02C8|api33_07_Buttons|AL=left, AH=right
01AB:02D0|api33_08_IsShown|AX
01AB:02D8|api33_09_SetShape|ES:DX shape (FFFFh=default), BX/CX hot spot
01AB:0316|api33_0A_WaitFrames|wait CX mouse interrupts (1/120 s), AX=frame counter
01AB:0320|mouse_wait_frames|
01AB:0354|api33_0C_SetHandler|CX=event mask, ES:DX far handler
01AB:036E|api33_0D_SetKeyEmu|CX!=0: cursor keys/Return/Esc drive the mouse
01AB:0382|api33_0E_GetKeyEmu|
01AB:038A|api33_0F_Nop|
01AB:038C|api33_10_SetXRange|CX,DX
01AB:03C0|api33_11_SetYRange|CX,DX
01AB:01F6|api33_ret0|functions 0Bh, 12h and above: AX=0
01AB:03F4|clamp|
01AB:0AC6|mouse_read_dx|bus mouse X delta + cursor-key emulation
01AB:0B2A|mouse_read_dy|
01AB:0B8E|mouse_read_buttons|
01AB:0BD6|mouse_call_handler|
01AB:0C40|mouse_port_rw|
01AB:0C4A|mouse_read_delta|two nibbles via 7FDDh/7FD9h
01AB:0C62|cursor_restore_bg|
01AB:0C78|cursor_draw|save background, draw
01AB:0CC0|cursor_clip|
01AB:0D2C|cursor_set_default|
01AB:0D44|cursor_load_shape|
01AB:0DA0|vram_save_rect|
01AB:0DCE|vram_restore_rect|
01AB:0DFC|cursor_blit|GRCG RMW
0290:0098|apiF3_Error|functions 03-05, 17h+: CF=1
0290:009E|apiF3_00_GetLoadBuffer|ES:BX=04E9:0454, CX=F800h
0290:00AE|apiF3_01_DrawGPC|DS:SI -> 8-word parameter block
0290:0136|gpc_row_put_opaque|
0290:0192|gpc_row_put_masked|colour 0 transparent
0290:01F4|gpc_row_xor_prev|
0290:0257|gpc_row_unfilter|
0290:0294|gpc_row_unpack|
0290:02DE|gpc_parse_header|
0290:0322|gpc_copy_palette|
0290:0336|apiF3_02_GetGPCInfo|ES:DI <- x,y,w,h,interlace,palette far ptr
0290:037A|apiF3_10_DefaultPalette|
0290:038A|apiF3_11_SetBrightness|AL=0..15, waits VSYNC, programs all 16 colours
0290:03D6|apiF3_12_GetBrightness|
0290:03DE|apiF3_13_SetPalette|DS:SI 16 words 0GRB, AL=brightness (FFh: no output)
0290:03F4|apiF3_14_GetPalette|ES:DI <- 16 words, AX=brightness
0290:0404|apiF3_15_SetColor|AL=index, BX=0GRB, CL=brightness (FFh: no output)
0290:044A|apiF3_16_GetColor|AL=index -> BX, AX=brightness
0290:059C|apiF3_06_AnimMode|AL=0 set CX&3 (returns old) / else get
0290:05B6|apiF3_07_Nop|
0290:05BC|apiF3_08_GetAnimBuffer|AL&1 -> ES:BX=14AF:0000/8000, CX=8000h
0290:05D4|apiF3_09_DrawAnimFrame|AL=bank, BL=frame char (B1h+n)
0290:070E|anim_row_unpack|
0290:075C|anim_row_unfilter|
0290:079C|anim_row_store|
0290:07F4|anim_step|advance both animation scripts by one step
0290:08BA|apiF3_0A_AnimRun|AL=0 stop+clear counters / FFh start
0290:08DA|apiF3_0B_SetAnimScript|AL=slot, DS:SI string
0290:091C|apiF3_0C_AnimCounter|AL bit0 slot; bit7=0 set CX / 1 get CX
0290:093A|apiF3_0D_AnimTrigger|increment slot AL counter
0290:094C|apiF3_0E_SetAnimColor|AL=slot, CL=text colour that triggers it
0290:0978|apiF3_0F_AnimPoll|
0328:0000|usd_install_once|
0328:001C|sound_init|far; detect, install INT F4, play built-in init sequence
0328:0090|usd_remove|
0328:00A5|sound_deinit|far
0328:00A9|usd_hook_f4|
0328:00DA|usd_unhook_f4|
0328:00FC|usd_is_installed|compare "USDdrv" at INT F4 handler+2
0328:011D|IntF4_USDdrv|jmp short; "USDdrv",0; saved ES; data seg; old vector
0328:0130|usd_dispatch|
0328:01B7|apiF4_06_Enable|AL=0 set CX&3 (bit0 music, bit1 SE) -> AX old; else get
0328:01E0|apiF4_00_LoadMusic|DS:BX file name -> 2B0F:0000
0328:01FB|apiF4_10_LoadSE|DS:BX file name -> 2B0F:3000
0328:0216|apiF4_01_PlayMusic|
0328:0222|usd_start_music|
0328:0236|apiF4_07_ReplayMusic|
0328:025A|apiF4_11_PlaySE|BX=entry index
0328:0277|apiF4_02_Stop|
0328:027D|apiF4_03_FadeOut|
0328:028E|apiF4_04_FadeIn|
0328:02AB|usd_volume_full|
0328:02BB|usd_volume_min|
0328:02CC|usd_read_file|INT F2 AH=0
0328:02DD|usd_start_bank_entry|
0328:02F5|usd_start_song|
0328:02FE|usd_bind_and_start|fix up .USO header, call seq_start
0328:03AF|apiF4_80_Install|
0328:03ED|apiF4_81_Remove|
0328:0408|usd_stop|
0328:0427|apiF4_05_Fade|BX=period, CX=step, DX
0328:0445|apiF4_20_ReadJoysticks|AX=stick 1, BX=stick 2 (via OPN ports A/B)
0328:04C9|apiF4_21_IsPresent|AL=FFh if OPN found
0328:04CE|apiF4_86_RegAccess|CX=mode, BX=reg/data
0328:04E9|usdtrap_install|
0328:052F|usdtrap_remove|
0328:0557|USDtrap|jmp short; "USDtrap"; chained vector; copyright
0328:05BA|opn_init|far; detect YM2203 at 188h, hook IRQ, start timers
0328:06AE|opn_shutdown|far
0328:0720|opn_irq|sound interrupt handler (vector 14h or 15h)
0328:0768|opn_timer_ack|
0328:0B73|opn_reg_access|far (mode, value)
0328:0BD1|seq_start|far (count, far ptr records, owner)
0328:0CA0|seq_stop|far (owner or 0=all)
0328:0CE2|seq_reset_channels|far
0328:0D71|seq_channel_ptr|AL=0..5 -> BX work area (FM 57h bytes at 0956, SSG 58h at 0A5B)
0328:0D96|seq_set_fade|far (period, step, flag)
0328:0DDA|seq_tick|far; per-interrupt sequencer
0328:1B9B|opn_read_reg|AL=reg -> AL
0328:1BB5|opn_write_reg|AL=reg, AH=data
0328:1BEB|opn_select_delay|far; picks I/O delay routine by CPU type
3018:00EE|child_name|data "NV.Ovl",0 - program spawned by main
3018:00F6|wait_skippable|data byte: AL of INT F1 08/09/0A
3018:00F8|wait_ticks|data word: counted down by Int_ClockTick
3018:00FC|anim_ticks|data word: animation divider (reload 2)
3018:00FE|rng_state|data dword
3018:0102|tickcb_period|data word
3018:0104|tickcb_count|data word
3018:0106|tickcb_active|data word
3018:017E|anim_run|data word: written by F3/0A, never read
3018:0180|anim_mode|data word: bit0 animation stepping enabled, bit1 frame drawing enabled
3018:0182|anim_color|data 2 bytes: text colour that triggers slot 0/1 (10h = none)
3018:0184|anim_counter|data 2 words: pending repeats of slot 0/1
3018:0188|anim_script_ptr|data 2 words
3018:018C|vram_seg|data 4 words A800 B000 B800 E000
3018:0194|tvram_seg|data word A000
3018:0196|egc_state|data word: 1 untested, FFFF present, 0 absent
3018:0198|text_window|data 4 words x0,y0,x1,y1
3018:01A0|text_x|data word (column)
3018:01A2|text_y|data word (line)
3018:01A4|text_color|data byte
3018:01A6|char_delay|data word
3018:01A8|char_skippable|data word
3018:01AA|char_beep|data word
3018:01AC|curtain_rect|data 4 bytes x0,y0,x1,y1 in 160x100 units
3018:01B0|curtain_color|data byte
3018:01B2|curtain_stride|data word 62
3018:01B4|curtain_phases|data word 31
3018:01B6|semigraphic_bits|data 8 bytes
3018:0216|label_xfcb|data extended FCB (attr 08h) for DOS 2 label search
3018:03C1|error_msg_attr|data byte 65h
3018:03C2|expected_disk|data 2 bytes: disk number expected in drive index 0/1
3018:03C4|psp_seg|data word
3018:0546|notice_checksum|data word (only used by the unreferenced notice printer)
3018:0548|errorMsgList|data 4 words: runtime error message pointers (name: VB)
3018:05CA|tickcb_ptr|data far pointer
3018:05CE|tram_line_save|data 240 bytes
3018:06BE|quit_flag|data word
3018:06C0|quit_disabled|data word
3018:06C2|exitproc_tab|data 16 x {word handle, far ptr}
3018:0722|exitproc_count|data word
3018:0724|hitmap_file|data 7D5h bytes
3018:0EF9|hitmap|data 2000 bytes: 80x50 nibbles
3018:16CA|OldIntF3Vec|data far pointer
3018:16CE|anim_script0|data 150 bytes
3018:1764|anim_script1|data 150 bytes
3018:1800|glyph_buf|data 34 bytes: INT 18h AH=14h result
3018:1822|scroll_count|data word
3018:1828|saved_dta|data far pointer
3018:182C|path_buf|data 64 bytes
3018:186E|boot_label|data 10 bytes
3018:1878|cur_label|data 11 bytes
3018:1883|dos_major|data byte
3018:1884|tram_box_save|data 468 bytes
3018:1B48|atexit_count|data word
3018:1B4A|atexit_tab|data 16 words
3018:1B6A|cmd_tail|data 128 bytes
3018:1BEA|exec_block|data 14 bytes
3018:1C02|argc|data word
3018:1C04|argv|data word
01AB:0176|mouse_inactive|data word: FFFFh until installed
01AB:0402|mouse_int_no|data byte 15h
01AB:0403|mouse_imr_mask|data byte DFh
01AB:0404|mouse_buttons|data 2 bytes left, right
01AB:0406|mouse_range|data 4 words xmin,ymin,xmax,ymax
01AB:040E|cursor_w|data word: bytes+1
01AB:0410|cursor_h|data word
01AB:0412|cursor_hot|data 2 words
01AB:0416|mouse_pos|data 2 words x,y
01AB:041E|cursor_drawn_pos|data 2 words
01AB:0428|mouse_keyemu|data word
01AB:042A|cursor_shown|data word
01AB:042E|mouse_frames|data word: +1 per mouse interrupt
01AB:0430|mouse_handler_mask|data word
01AB:0432|mouse_handler|data far pointer
01AB:0436|cursor_bg_save|data
01AB:07F6|cursor_shape|data
01AB:09D8|cursor_default|data 16x32 arrow
0290:045C|shared_palette|data 16 words returned by INT F3 AH=FF
0290:047C|default_palette|data 16 words 0GRB
0290:049C|brightness_tab|data 16x16 bytes
04E9:0000|gfx_params|data 8 words copied from the F3/01 caller
04E9:0022|palette|data 16 words 0GRB
04E9:0042|brightness|data word
04E9:01D4|gpc_row_buf|data
04E9:0454|gpc_file_buf|data F800h bytes
14AF:0000|anim_bank0|data 8000h bytes
14AF:8000|anim_bank1|data 8000h bytes
24AF:0000|anim_work|data
2B0F:0000|music_buf|data 3000h bytes
2B0F:3000|se_buf|data 2000h bytes
2B0F:5000|music_loaded|data byte
2B0F:5001|se_loaded|data byte
2B0F:5002|music_tracks|data 6 x 10 bytes
2B0F:503E|se_tracks|data 6 x 10 bytes
2B0F:507A|default_voice_ptrs|data 2 far pointers
2B0F:5082|joy_prev|data word
0328:004C|builtin_init_song|data 68 bytes in .USO layout
0328:012D|usd_present|data byte
0328:012E|usd_enable|data word: bit0 music, bit1 SE (default 3)
0328:0177|jumpTbl_intF4|data 32 words
0328:0560|usdtrap_chain|data far pointer
0328:0574|opn_timer_a|data word (bit15 = reprogram request)
0328:0578|opn_int_no|data byte 14h (15h if port A bit7 clear)
0328:0579|opn_imr_mask|data byte
0328:057A|opn_present|data word
0328:0956|fm_channels|data 3 x 57h bytes
0328:0A5B|ssg_channels|data 3 x 58h bytes
0328:0B63|fade_state|data
0328:1B99|opn_delay_proc|data word
"""


def data_size(kind, text):
    """Size in bytes of an IDA 'db/dw/dd' operand list (None if unsure)."""
    unit = {'db': 1, 'dw': 2, 'dd': 4}[kind]
    # strip trailing comment (not inside quotes)
    out, q, cur, items = [], False, '', []
    for ch in text:
        if ch == "'":
            q = not q
            cur += ch
        elif ch == ';' and not q:
            break
        elif ch == ',' and not q:
            items.append(cur.strip())
            cur = ''
        else:
            cur += ch
    if cur.strip():
        items.append(cur.strip())
    total = 0
    for it in items:
        m = re.match(r'^([0-9A-Fa-f]+)h?\s+dup\s*\((.*)\)$', it)
        if m:
            n = m.group(1)
            n = int(n, 16) if it[len(n):len(n) + 1] == 'h' else int(n)
            total += n * unit
        elif it.startswith("'") and it.endswith("'") and len(it) >= 2:
            if kind != 'db':
                total += unit
            else:
                total += len(it) - 2
        else:
            total += unit
    return total


def walk_asm(path, dn):
    """-> ({name: image_addr}, {name: kind}) kind = 'code' | 'data'."""
    addrs, kinds = {}, {}
    addr = None
    text = open(path, 'rb').read().decode('latin-1')
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith(';'):
            continue
        if not line[0].isspace():
            m = LABEL_LINE.match(line)
            if not m:
                continue
            name, tail = m.group(1), (m.group(2) or '')
            if 'endp' in tail or 'ends' in tail or tail.strip() == '=':
                continue
            if 'segment' in tail:
                # IDA's segments are byte-aligned: a segment starts where the
                # previous one ended, so simply keep counting.
                if name == 'seg000':
                    addr = 0
                continue
            a = AUTO.match(name)
            if a and a.group(1) != 'seg':
                addr = int(a.group(2), 16) - IDA_BASE
            is_data = bool(m.group(4))
            if addr is not None and 0 <= addr < len(dn.data) + 0x10000:
                addrs[name] = addr
                kinds[name] = 'data' if is_data else 'code'
            if is_data:
                kind = m.group(4)
                rest = line[m.end():]
                if addr is not None:
                    sz = data_size(kind, rest)
                    addr = addr + sz if sz is not None else None
            continue
        body = line.strip()
        tok = body.split()[0]
        if tok in ('db', 'dw', 'dd'):
            if addr is not None:
                addr += data_size(tok, body[len(tok):])
            continue
        if tok == 'align':
            if addr is not None:
                n = body.split()[1]
                n = int(n[:-1], 16) if n.endswith('h') else int(n)
                addr = (addr + n - 1) // n * n
            continue
        if tok in DIRECTIVES or tok.startswith(';'):
            continue
        # an instruction
        if addr is None or addr >= len(dn.data):
            addr = None
            continue
        i = dn.insn(addr)
        if i is None:
            addr = None
            continue
        addr += i.size
    return addrs, kinds


def pattern(img, lin, max_insns=24, min_bytes=6):
    """Wildcard byte pattern of the straight-line code at lin.
    Returns (regex bytes, [(pos_in_match, size, value)] wildcard operands)."""
    pat = b''
    wild = []
    pos = 0
    seg = img.seg_of(lin)
    n = 0
    while n < max_insns and lin < len(img.data):
        i = img.insn(lin, seg)
        if i is None:
            break
        b = bytes(i.bytes)
        mask = [False] * len(b)
        enc = i  # capstone exposes encoding offsets directly on the insn
        for off, size in ((enc.disp_offset, enc.disp_size),
                          (enc.imm_offset, enc.imm_size)):
            if off and size == 2:
                mask[off] = mask[off + 1] = True
                wild.append((pos + off, 2, b[off] | b[off + 1] << 8))
        # far call/jump: off16 + seg16 both wild
        if b[0] in (0x9A, 0xEA) and len(b) == 5:
            mask[1:5] = [True] * 4
        for k, x in enumerate(b):
            pat += b'.' if mask[k] else re.escape(bytes([x]))
        pos += len(b)
        lin += len(b)
        n += 1
        if i.mnemonic in ('ret', 'retf', 'iret', 'jmp', 'ljmp') and \
                pos >= min_bytes:
            break
    return pat, wild, pos


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--asm', required=True)
    ap.add_argument('--dn', required=True)
    ap.add_argument('--nova', required=True)
    ap.add_argument('--own')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--no-own', action='store_true',
                    help='only emit names carried over from the reference')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()

    dn = Image.load_mz(a.dn)
    nv = Image.load_mz(a.nova)
    addrs, kinds = walk_asm(a.asm, dn)
    dgroup_dn = max(dn.segs) * 16
    dgroup_nv = max(nv.segs) * 16
    code_end = sorted(dn.segs)[4] * 16 if len(dn.segs) > 4 else len(dn.data)

    # ---- 2. code labels ------------------------------------------------
    code_map = {}                         # dn addr -> nova addr
    votes = collections.defaultdict(collections.Counter)
    stats = collections.Counter()
    unmatched = []
    for name, da in sorted(addrs.items(), key=lambda kv: kv[1]):
        if kinds[name] != 'code' or da >= code_end:
            continue
        if da in code_map:
            continue
        pat, wild, size = pattern(dn, da)
        if size < 6:
            stats['too short'] += 1
            continue
        hits = [m.start() for m in re.finditer(pat, nv.data[:code_end + 64],
                                               re.S)]
        if not hits:
            stats['no match'] += 1
            unmatched.append((name, da))
            continue
        best = min(hits, key=lambda h: abs(h - da))
        if len(hits) > 1 and abs(best - da) > 0x100:
            stats['ambiguous'] += 1
            continue
        stats['matched'] += 1
        code_map[da] = best
        for off, _sz, dval in wild:
            nval = nv.data[best + off] | nv.data[best + off + 1] << 8
            votes[dval][nval] += 1

    # ---- 3. data labels --------------------------------------------------
    data_map = {v: c.most_common(1)[0][0] for v, c in votes.items()}
    # Initialised data (strings changed length between the builds): align the
    # two DGROUP images byte-wise.  BSS above it: operand votes.
    init_dn = dn.data[dgroup_dn:]
    init_nv = nv.data[dgroup_nv:]
    ops = difflib.SequenceMatcher(None, init_dn, init_nv,
                                  autojunk=False).get_opcodes()
    # (operands above the initialised data that did not move are mostly
    # plain constants, so a zero shift only wins if nothing else is seen)
    bss_votes = collections.Counter(
        n - d for d, n in data_map.items()
        if d >= len(init_dn) and n != d and abs(n - d) < 0x100)
    bss_shift = 0
    if bss_votes and bss_votes.most_common(1)[0][1] >= 8:
        bss_shift = bss_votes.most_common(1)[0][0]

    def map_data(off):
        if off >= len(init_dn):
            if off in data_map and data_map[off] - off == bss_shift:
                return data_map[off], ''
            return off + bss_shift, 'bss shift'
        for tag, i1, i2, j1, j2 in ops:
            if i1 <= off < i2:
                if tag == 'equal':
                    return j1 + off - i1, ''
                return j1, 'changed'
        return off, '?'

    rows = {}                              # (seg, off) -> (name, comment)
    for name, da in addrs.items():
        auto = AUTO.match(name)
        if auto and not (a.all and auto.group(1) == 'sub'):
            continue
        nm = 'dn_' + name if auto else name
        if kinds[name] == 'code' and da < code_end:
            if da not in code_map:
                continue
            na = code_map[da]
            seg = nv.seg_of(na)
            rows[(seg, na - seg * 16)] = (
                nm, 'VB; DN %s' % dn.fmt(da))
        elif da >= dgroup_dn:
            off, how = map_data(da - dgroup_dn)
            rows[(dgroup_nv // 16, off)] = (
                nm, 'data VB; DN %04X:%04X%s' % (
                    dgroup_dn // 16, da - dgroup_dn,
                    ' (' + how + ')' if how else ''))
        else:                               # data inside a code segment
            if da in code_map:
                na = code_map[da]
            else:                           # code is aligned: same address
                lo = [x for x in code_map if x <= da]
                x = max(lo) if lo else da
                na = da + (code_map.get(x, x) - x)
            seg = nv.seg_of(na)
            rows[(seg, na - seg * 16)] = (nm, 'data VB; DN %s' % dn.fmt(da))

    own = {}
    for line in NOVA_NAMES.splitlines():
        if line.strip():
            adr, nm, cm = line.split('|', 2)
            sg, of = adr.split(':')
            own[(int(sg, 16), int(of, 16))] = (nm, cm)
    if a.own:
        own.update(load_names(a.own))
    if not a.no_own:
        for key, (nm, cm) in own.items():
            old = rows.get(key)
            if old and old[0] != nm and not old[0].startswith('dn_') \
                    and '[VB:' not in cm and '(changed)' not in old[1]:
                cm = (cm + ' ' if cm else '') + '[VB: %s]' % old[0]
            rows[key] = (nm, cm)

    with open(a.out, 'w', encoding='utf-8') as f:
        f.write('# NOVA NV.OV1 (AdvBIOS 0.54) names; addresses relative to '
                'load base 0.\n# Generated by re-tools/advbios_map.py. '
                '"VB" = name taken from Valley Bell\'s Dengeki Nurse '
                'disassembly (CC-BY-SA).\n')
        for (seg, off) in sorted(rows, key=lambda k: (k[0] * 16 + k[1])):
            nm, cm = rows[(seg, off)]
            f.write('%04X:%04X\t%s\t%s\n' % (seg, off, nm, cm))
    shifts = collections.Counter(n - d for d, n in code_map.items())
    dshift = collections.Counter(n - d for d, n in data_map.items())
    print('labels in asm: %d (code %d)' % (
        len(addrs), sum(1 for k in kinds.values() if k == 'code')),
        file=sys.stderr)
    print('code labels:', dict(stats), 'shifts', dict(shifts),
          file=sys.stderr)
    for name, da in unmatched:
        print('  no match: %s (DN %s)' % (name, dn.fmt(da)), file=sys.stderr)
    for da, na in sorted(code_map.items()):
        if da != na:
            print('  moved: DN %s -> NOVA %s' % (dn.fmt(da), nv.fmt(na)),
                  file=sys.stderr)
    print('data operand shifts:', dshift.most_common(8), file=sys.stderr)
    print('rows written: %d' % len(rows), file=sys.stderr)


if __name__ == '__main__':
    main()
