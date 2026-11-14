#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""nvovl_emu - the original interpreter NV.OVL running scripts on the original AdvBIOS under
unicorn: the reference for the engine's interpreter tests (needs unicorn).

    emu = NvOvlEmu(files={'T.MES': script_bytes, 'NV01.GPC': ...}, fonts='build/fonts',
                   keys=[(0x1C, 0x0D)], storage={})
    result = emu.run('\\\\MES\\\\T.MES')        # until the program ends or waits with no keys left
    result: dict(end='exit'|'starved', mem=64 KB of NV.OVL's segment, planes=4 x 32000,
                 storage={name: bytes}, sound=[(ah, arg), ...], display=[...])

Built on re-tools/advbios_emu.py (AdvBIOS's own INT F1h/F3h/F6h code, GRCG, DAC, kanji ROM).
What this harness adds or models:
  * NV.OVL (the unpacked MZ of `gamedata.py derive`, one segment, no relocations) at segment
    5000h, with the two bytes NV.INI's copy protection patches in (`int F3h` at 0xEA84,
    interpreter.md §7); entered at `restart` 0xDC97 with the start script's name in the
    file-name buffer 0xD9F3, as the entry code would after its checks (§2). Before that the
    screen is set up as AdvBIOS's init_screen_state does (0000:00A2).
  * INT 33h is AdvBIOS's own mouse driver code (01AB:0178), marked installed; the pointer and
    the buttons are its variables (01AB:0404/0416/0418), set by the harness. The 120 Hz
    interrupt does not run: the driver's frame counter (01AB:042E) advances on every read.
  * The 20 ms tick counter (AdvBIOS DS:00F8) and the animation divider (DS:00FC) count down by
    one on every read, so timed waits end after as many polls as ticks.
  * INT F2h (files) is modelled after advbios.md §4.4: AH=00h load DS:DX into ES:BX, 01h write
    CX bytes, 04h select drive, 05h read at most CX bytes (AX = length), 06h, 08h nothing. Names
    lose drive and directories; FLAGn and NAME.DEF are the `storage` dict, everything else
    `files` (upper-case base names).
  * INT F4h (sound) calls are recorded in `sound`, not run.
  * INT 18h: the keyboard is a queue of (scan, char) pairs: a key becomes available after the
    program has found the buffer empty three times in a row, i.e. only while it is waiting for
    input; when the queue is empty and the program keeps polling, the run stops ("starved").
    AH=02h shift state 0. AH=40h/41h/42h (display) are recorded.
  * The VSYNC interrupt (INT 0Ah), which PALCH and WHITEH hook through DOS, is delivered
    between slices of 20 000 instructions when requested (port 64h), unmasked (port 02h bit 2)
    and interrupts are enabled, as in re-tools/tcmtool.py; old vectors they chain to are stubs.
  * INT 21h: AH=25h/35h set/get vector; AH=30h DOS 3.30; AH=48h/49h allocate (first fit) and free in 6000h-8FFFh, 4Ah
    succeeds; AH=4Ch (exit) ends the run; the rest returns at once.
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import advbios_emu as A  # noqa: E402

X = A.X
OVL = os.path.join(A.ROOT, 'resources', 'derived', 'exe', 'NV.OVL')
SEG = 0x5000
STUB = 0xF100           # interrupt stubs for the vectors plug-ins chain to
SLICE = 20000           # instructions between VSYNC interrupt opportunities (as tcmtool.py)
A.HANDLERS.setdefault(0x33, (0x01AB, 0x0178))


class Stop(Exception):
    pass


class NvOvlEmu(A.AdvBiosEmu):
    def __init__(self, files, fonts=None, keys=(), storage=None, ovl=OVL, ov1=A.OV1):
        super().__init__(ov1=ov1, fonts=fonts)
        self.files = {k.upper(): v for k, v in files.items()}
        self.storage = dict(storage or {})
        self.keys = list(keys)
        self.key_ready = None
        self.empty_senses = 0
        self.sound = []
        self.display = []
        self.palette_log = []                   # INT F3h AH=13h / 15h calls
        self.end = None
        self.blocks = {}                        # DOS memory for the plug-ins: 6000h-8FFFh
        self.imr = 0xFF                         # master PIC mask (port 02h): IRQ2 = VSYNC
        self.vsync_armed = False                # port 64h written: one VSYNC interrupt requested
        # old vectors a plug-in chains to: INT 18h -> `int 18h; iret`, INT 0Ah -> `iret`
        self.uc.mem_write(STUB * 16, b'\xcd\x18\xcf\x00\xcf')
        self.uc.mem_write(0x18 * 4, struct.pack('<HH', 0, STUB))
        self.uc.mem_write(0x0A * 4, struct.pack('<HH', 4, STUB))
        d = open(ovl, 'rb').read()
        hdr = struct.unpack_from('<H', d, 8)[0] * 16
        self.uc.mem_write(SEG * 16, d[hdr:hdr + 0x10000])
        self.uc.mem_write(SEG * 16 + len(d) - hdr, bytes(0x10000 - (len(d) - hdr)))
        mouse = (0x01AB + A.BASE) * 16
        self.uc.mem_write(mouse + 0x176, b'\0\0')           # driver installed
        self.uc.mem_write(mouse + 0x403, b'\xdf')           # IRQ mask bit
        self._counter(mouse + 0x42E, +1)
        ds = (A.DGROUP + A.BASE) * 16
        # the click-map wait (INT F1h AH=0Dh, 0000:0526) polls only the mouse: a run that
        # loops there is waiting for input
        self.click_polls = 0
        loop = (0x0000 + A.BASE) * 16 + 0x0526

        mouse = (0x01AB + A.BASE) * 16

        def click(uc, addr, size, ud):
            self.click_polls += 1
            if self.keys and self.keys[0][0] == 'ret*':
                self.keys.pop(0)
            if self.keys and self.keys[0][0] == 'click' and self.click_polls > 3:
                _, x, y = self.keys.pop(0)
                uc.mem_write(mouse + 0x416, struct.pack('<HH', x, y))
                uc.mem_write(mouse + 0x404, b'\x01\x00')      # left down until the wait returns
            elif self.click_polls > 500:
                self.end = 'starved'
                uc.emu_stop()

        def click_done(uc, addr, size, ud):
            uc.mem_write(mouse + 0x404, b'\x00\x00')
            self.click_polls = 0
        self.uc.hook_add(A.unicorn.UC_HOOK_CODE, click, None, loop, loop)
        done = (0x0000 + A.BASE) * 16 + 0x0574
        self.uc.hook_add(A.unicorn.UC_HOOK_CODE, click_done, None, done, done)
        self._counter(ds + 0xF8, -1)
        self._counter(ds + 0xFC, -1)

    def _counter(self, lin, step):
        def hook(uc, access, addr, size, value, ud):
            v = struct.unpack('<H', uc.mem_read(lin, 2))[0]
            if step > 0:
                v = (v + 1) & 0xFFFF
            elif v:
                v -= 1
            uc.mem_write(lin, struct.pack('<H', v))
        self.uc.hook_add(A.unicorn.UC_HOOK_MEM_READ, hook, None, lin, lin + 1)

    # ---------------- interrupts ----------------
    def _intr(self, uc, intno, ud):
        ax = uc.reg_read(X.UC_X86_REG_AX)
        ah, al = ax >> 8, ax & 0xFF
        if intno == 0x18:
            if ah == 0x01:
                bx = uc.reg_read(X.UC_X86_REG_BX) & 0x00FF
                if self.key_ready is None and self.keys and self.keys[0][0] == 'click':
                    self.empty_senses += 1      # a click waits for a click-map wait
                    if self.empty_senses > 2000:
                        self.end = 'starved'
                        uc.emu_stop()
                        return
                elif self.key_ready is None and self.keys and self.keys[0][0] == 'ret*':
                    self.empty_senses += 1
                    if self.empty_senses >= 3:
                        self.key_ready = (0x1C, 0x0D)
                        self.empty_senses = 0
                elif self.key_ready is None:
                    self.empty_senses += 1
                    if self.keys and self.empty_senses >= 3:
                        self.key_ready = self.keys.pop(0)
                        self.empty_senses = 0
                    elif not self.keys and self.empty_senses > 2000:
                        self.end = 'starved'
                        uc.emu_stop()
                        return
                if self.key_ready is not None:
                    uc.reg_write(X.UC_X86_REG_AX, (self.key_ready[0] << 8) | self.key_ready[1])
                    bx |= 0x0100
                uc.reg_write(X.UC_X86_REG_BX, bx)
                return
            if ah == 0x00:
                if self.key_ready is None:
                    if not self.keys:
                        self.end = 'starved'
                        uc.emu_stop()
                        return
                    self.key_ready = self.keys.pop(0)
                k = self.key_ready
                self.key_ready = None
                self.empty_senses = 0
                uc.reg_write(X.UC_X86_REG_AX, (k[0] << 8) | k[1])
                return
            if ah in (0x40, 0x41, 0x42):
                self.display.append((ah, uc.reg_read(X.UC_X86_REG_CX) >> 8))
                return
            return super()._intr(uc, intno, ud)
        if intno == 0xF2:
            return self._files(uc, ah, al)
        if intno == 0xF4:
            bx = uc.reg_read(X.UC_X86_REG_BX)
            arg = None
            if ah in (0x00, 0x10):
                arg = self._name(uc.reg_read(X.UC_X86_REG_DS), bx)
            elif ah == 0x11:
                arg = bx
            elif ah in (0x03, 0x04):
                arg = uc.reg_read(X.UC_X86_REG_DX) & 0xFF
            elif ah == 0x07:
                arg = uc.reg_read(X.UC_X86_REG_CX)
            self.sound.append((ah, arg))
            return
        if intno == 0x21:
            if ah == 0x35:                      # get vector AL -> ES:BX
                off, seg = struct.unpack('<HH', uc.mem_read(al * 4, 4))
                uc.reg_write(X.UC_X86_REG_ES, seg)
                uc.reg_write(X.UC_X86_REG_BX, off)
            elif ah == 0x25:                    # set vector AL <- DS:DX
                uc.mem_write(al * 4, struct.pack('<HH', uc.reg_read(X.UC_X86_REG_DX),
                                                 uc.reg_read(X.UC_X86_REG_DS)))
            elif ah == 0x30:
                uc.reg_write(X.UC_X86_REG_AX, 0x1E03)
            elif ah == 0x48:                    # allocate BX paragraphs (plug-ins: ACTE1)
                n = uc.reg_read(X.UC_X86_REG_BX)
                seg = self._alloc(n)
                if seg is None:
                    uc.reg_write(X.UC_X86_REG_AX, 8)
                    self._cf(uc, True)
                else:
                    uc.reg_write(X.UC_X86_REG_AX, seg)
                    self._cf(uc, False)
            elif ah == 0x49:
                self.blocks.pop(uc.reg_read(X.UC_X86_REG_ES), None)
                self._cf(uc, False)
            elif ah == 0x4A:
                self._cf(uc, False)
            elif ah == 0x4C:
                self.end = 'exit'
                uc.emu_stop()
            return
        if intno == 0xF3 and ah == 0x13:
            ds, si = uc.reg_read(X.UC_X86_REG_DS), uc.reg_read(X.UC_X86_REG_SI)
            words = struct.unpack('<16H', uc.mem_read(ds * 16 + si, 32))
            self.palette_log.append('13 %d ' % al + ' '.join('%03X' % w for w in words))
        elif intno == 0xF3 and ah == 0x15:
            self.palette_log.append('15 %d %d %03X' % (al, uc.reg_read(X.UC_X86_REG_CX) & 0xFF,
                                                    uc.reg_read(X.UC_X86_REG_BX)))
        if intno in (0xF1, 0xF3, 0xF6, 0x33):
            return super()._intr(uc, intno, ud)
        return super()._intr(uc, intno, ud)

    def _alloc(self, n):
        """first fit in 6000h-8FFFh"""
        seg = 0x6000
        for s, size in sorted(self.blocks.items()):
            if seg + n <= s:
                break
            seg = max(seg, s + size)
        if seg + n > 0x9000:
            return None
        self.blocks[seg] = n
        return seg

    def _in(self, uc, port, size, ud):
        if port == 0x02:
            return self.imr
        return super()._in(uc, port, size, ud)

    def _out(self, uc, port, size, value, ud):
        if port == 0x02:
            self.imr = value & 0xFF
        elif port == 0x64:
            self.vsync_armed = True
        else:
            super()._out(uc, port, size, value, ud)

    def _deliver_vsync(self):
        """INT 0Ah when requested (port 64h), unmasked (IRQ2) and interrupts are enabled"""
        uc = self.uc
        fl = uc.reg_read(X.UC_X86_REG_EFLAGS)
        if not self.vsync_armed or self.imr & 4 or not fl & 0x200:
            return
        off, seg = struct.unpack('<HH', uc.mem_read(0x0A * 4, 4))
        self.vsync_armed = False
        sp = (uc.reg_read(X.UC_X86_REG_SP) - 6) & 0xFFFF
        ss = uc.reg_read(X.UC_X86_REG_SS)
        uc.mem_write(ss * 16 + sp, struct.pack('<HHH', uc.reg_read(X.UC_X86_REG_IP),
                                               uc.reg_read(X.UC_X86_REG_CS), fl & 0xFFFF))
        uc.reg_write(X.UC_X86_REG_SP, sp)
        uc.reg_write(X.UC_X86_REG_EFLAGS, fl & ~0x200)
        uc.reg_write(X.UC_X86_REG_CS, seg)
        uc.reg_write(X.UC_X86_REG_IP, off)

    def _name(self, seg, off):
        b = bytes(self.uc.mem_read(seg * 16 + off, 128)).split(b'\0')[0]
        return b.decode('ascii', 'replace')

    @staticmethod
    def base(name):
        b = name.replace('\\', '/').split('/')[-1].split(':')[-1].upper()
        return b

    def _cf(self, uc, on):
        fl = uc.reg_read(X.UC_X86_REG_EFLAGS)
        uc.reg_write(X.UC_X86_REG_EFLAGS, (fl | 1) if on else (fl & ~1))

    def _files(self, uc, ah, al):
        ds, dx = uc.reg_read(X.UC_X86_REG_DS), uc.reg_read(X.UC_X86_REG_DX)
        es, bx = uc.reg_read(X.UC_X86_REG_ES), uc.reg_read(X.UC_X86_REG_BX)
        cx = uc.reg_read(X.UC_X86_REG_CX)
        if ah in (0x00, 0x01, 0x05, 0x06):
            name = self.base(self._name(ds, dx))
            record = name == 'NAME.DEF' or (name.startswith('FLAG') and len(name) == 5)
            src = self.storage if record else self.files
        if ah in (0x00, 0x05):
            data = src.get(name)
            if data is None:
                self._cf(uc, True)
                return
            if ah == 0x05:
                data = data[:cx]
            uc.mem_write(es * 16 + bx, bytes(data))
            uc.reg_write(X.UC_X86_REG_AX, len(data))
            self._cf(uc, False)
            return
        if ah == 0x01:
            if not record:
                self._cf(uc, True)
                return
            self.storage[name] = bytes(uc.mem_read(es * 16 + bx, cx))
            uc.reg_write(X.UC_X86_REG_AX, cx)
            self._cf(uc, False)
            return
        self._cf(uc, False)

    # ---------------- running ----------------
    def run(self, start, count=400000000):
        uc = self.uc
        # what NV.INI's copy protection does on success: `int F3h` into image-show (0xEA84;
        # without it no picture is ever shown, interpreter.md §7)
        uc.mem_write(SEG * 16 + 0xEA84, b'\xcd\xf3')
        # AdvBIOS's init_screen_state 0000:00A2: default palette, brightness 0, page cleared,
        # brightness 15, mouse reset
        self.call(0xF3, ax=0x1000)
        self.call(0xF3, ax=0x1100)
        self.call(0xF6, ax=0x0C00)
        self.call(0xF3, ax=0x110F)
        self.call(0x33, ax=0x0000)
        name = start.encode('ascii') + b'\0'
        uc.mem_write(SEG * 16 + 0xD9F3, name)
        for r, v in ((X.UC_X86_REG_CS, SEG), (X.UC_X86_REG_DS, SEG), (X.UC_X86_REG_ES, SEG),
                     (X.UC_X86_REG_SS, SEG), (X.UC_X86_REG_SP, 0xFFF0),
                     (X.UC_X86_REG_IP, 0xDC97), (X.UC_X86_REG_EFLAGS, 0x0202)):
            uc.reg_write(r, v)
        done = 0
        while self.end is None and done < count:
            cs, ip = uc.reg_read(X.UC_X86_REG_CS), uc.reg_read(X.UC_X86_REG_IP)
            uc.emu_start(cs * 16 + ip, 0xFFFFF, count=SLICE)
            done += SLICE
            if self.end is None:
                self._deliver_vsync()
        if self.end is None:
            raise RuntimeError('NV.OVL stopped at %04X:%04X' % (uc.reg_read(X.UC_X86_REG_CS),
                                                               uc.reg_read(X.UC_X86_REG_IP)))
        # the screen with the pointer, then without it (hiding restores what is under it): the
        # engine draws the pointer only into the presented frame
        with_pointer = None
        if struct.unpack('<H', uc.mem_read((0x01AB + A.BASE) * 16 + 0x42A, 2))[0]:
            with_pointer = self.planes()
            self.call(0x33, ax=2)
        return dict(end=self.end, mem=bytes(uc.mem_read(SEG * 16, 0x10000)),
                    planes=self.planes(), pointer_planes=with_pointer,
                    palette_log=list(self.palette_log), storage=dict(self.storage), sound=list(self.sound),
                    display=list(self.display))
