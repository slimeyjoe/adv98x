#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""advbios_emu - AdvBIOS's own service code (NV.OV1) under unicorn, as a reference for tests.

Library (needs unicorn; docs/re/README.md "Tools"):

    emu = AdvBiosEmu(ov1='resources/derived/exe/NV.OV1', fonts='build/fonts')
    emu.call(0xF6, ax=0x0300 | 4)               # INT F6h AH=03h: colour 4
    emu.call(0xF6, ax=0x0900, dx=0x8250)        # draw one character
    emu.call(0xF6, ax=0x0A00, ds_si=b'text\0')  # pointer arguments: bytes placed in scratch memory
    planes = emu.planes()                        # 4 x 32000 bytes: the screen

What is real and what is modelled:
  * NV.OV1 (plain MZ, the unpacked file of `gamedata.py derive`) is loaded at segment 1000h with
    its 71 relocations applied, like usdemu.py. Nothing of its start-up is run: the services
    work from the initialised DGROUP (defaults: window 0,0-79,399, colour 15, skippable delay;
    docs/re/advbios.md §5.2). A call enters the interrupt handler itself (IntF1 0000:01A8,
    IntF3 0290:002A, IntF6 0000:0902) with an IRET frame that returns to a sentinel.
  * Graphics VRAM (A800, B000, B800, E000: planes 0..3) is MMIO with the GRCG modelled: port
    7Ch mode (bit 7 on, bit 6 RMW vs TDW, bits 0..3 plane disable), port 7Eh the four tile
    registers in turn. RMW write: plane = (plane & ~data) | (tile & data); TDW: plane = tile.
    Reads without the GRCG return the plane byte. Text VRAM (A000/A200) is plain memory.
  * Port 60h / A0h bit 5 (VSYNC) toggles on every read, so VSYNC waits end at once.
  * The palette ports A8h (index), AAh (green), ACh (red), AEh (blue) are recorded in
    `self.dac` (16 x [r, g, b]).
  * INT 18h AH=14h, the kanji ROM, answers from the pack's glyph tables (tools/xfont.py
    --no-bold: k16.xfnt keyed by JIS, ank8.xfnt by JIS X 0201 byte): rows 29h/2Ah are the
    half-width 8x16 characters (29xx = byte xx, 2Axx = byte xx + 80h), row 2Bh half-width and
    blank, all else 16x16; buffer byte 0 = 2 (height in 8-dot units), byte 1 = width in
    bytes, then 16 rows. This is the same ROM model as engine/text/font.c, so a comparison
    tests AdvBIOS's logic, not the font. AH=02h (shift state) returns `self.shift`, AH=01h
    no key. INT 33h AX=6 (right button) returns `self.right_button`.
  * The tick counter DS:00F8 is not driven: waits must not be used (character delay 0).
"""
import os
import struct
import sys

try:
    import unicorn
    from unicorn import x86_const as X
except ImportError:                      # the caller reports that the reference is missing
    unicorn = None

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'source', 'tools'))
import gamedir  # noqa: E402
sys.path.insert(0, HERE)
import advbuild  # noqa: E402
OV1 = gamedir.derived(None, 'exe', 'NV.OV1')

BASE = 0x1000
DGROUP = 0x3018
HANDLERS = {0xF1: (0x0000, 0x01A8), 0xF3: (0x0290, 0x002A), 0xF6: (0x0000, 0x0902)}
PLANE_LIN = (0xA8000, 0xB0000, 0xB8000, 0xE0000)
SCRATCH = 0x9000          # segment for pointer arguments
STACK = 0x9800
SENT = 0xF000             # sentinel segment: HLT at F000:0000


def read_xfnt(path):
    d = open(path, 'rb').read()
    if d[:4] != b'XFNT':
        raise ValueError('%s: not an XFNT table' % path)
    cw, ch, _flags, count = d[5], d[6], d[7], struct.unpack_from('<H', d, 8)[0]
    codes = struct.unpack_from('<%dH' % count, d, 12)
    gb = ch * cw // 8
    g = 12 + 2 * count
    return {c: d[g + i * gb:g + (i + 1) * gb] for i, c in enumerate(codes)}


class AdvBiosEmu:
    def __init__(self, ov1=OV1, fonts=None):
        if unicorn is None:
            raise RuntimeError('advbios_emu needs the unicorn package')
        self.k16 = read_xfnt(os.path.join(fonts, 'k16.xfnt')) if fonts else {}
        self.ank8 = read_xfnt(os.path.join(fonts, 'ank8.xfnt')) if fonts else {}
        self.shift = 0
        self.right_button = 0
        self.vsync = 0
        self.grcg_mode = 0
        self.tile = [0, 0, 0, 0]
        self.tile_i = 0
        self.vram = [bytearray(0x8000) for _ in range(4)]
        self.ports = []
        self.dac = [[0, 0, 0] for _ in range(16)]    # colour -> [r, g, b] as programmed
        self.dac_index = 0
        self.uc = uc = unicorn.Uc(unicorn.UC_ARCH_X86, unicorn.UC_MODE_16)
        uc.mem_map(0, 0xA8000)
        for base, size in ((0xA8000, 0x18000), (0xE0000, 0x8000)):
            uc.mmio_map(base, size,
                        lambda u, off, sz, ud, b=base: self._vram_read(b + off, sz), None,
                        lambda u, off, sz, v, ud, b=base: self._vram_write(b + off, sz, v), None)
        uc.mem_map(0xC0000, 0x20000)
        uc.mem_map(0xE8000, 0x28000)
        uc.mem_write(SENT * 16, b'\xF4' * 16)
        self._load_mz(ov1)
        for n, (seg, off) in HANDLERS.items():
            uc.mem_write(n * 4, struct.pack('<HH', off, seg + BASE))
        uc.hook_add(unicorn.UC_HOOK_INSN, self._in, None, 1, 0, X.UC_X86_INS_IN)
        uc.hook_add(unicorn.UC_HOOK_INSN, self._out, None, 1, 0, X.UC_X86_INS_OUT)
        uc.hook_add(unicorn.UC_HOOK_INTR, self._intr)

    # ---------------- image ----------------
    def _load_mz(self, path):
        d = advbuild.check(open(path, 'rb').read(), advbuild.BIOS, path)
        if d[:2] != b'MZ':
            raise ValueError('%s: not an MZ file' % path)
        last, pages, nrel, hdr = struct.unpack_from('<4H', d, 2)
        relo = struct.unpack_from('<H', d, 0x18)[0]
        size = pages * 512 - ((512 - last) if last else 0)
        img = bytearray(d[hdr * 16:size])
        for i in range(nrel):
            off, seg = struct.unpack_from('<HH', d, relo + 4 * i)
            a = seg * 16 + off
            struct.pack_into('<H', img, a, (struct.unpack_from('<H', img, a)[0] + BASE) & 0xFFFF)
        self.uc.mem_write(BASE * 16, bytes(img))

    def lin(self, seg, off):
        """linear address of an image address SEG:OFF (relative to the load base)"""
        return (seg + BASE) * 16 + off

    def ds_bytes(self, off, n):
        return bytes(self.uc.mem_read(self.lin(DGROUP, off), n))

    def ds_word(self, off):
        return struct.unpack('<H', self.ds_bytes(off, 2))[0]

    # ---------------- hardware ----------------
    def _vram_read(self, lin, size):
        v = 0
        for i in range(size):
            p, o = self._split(lin + i)
            v |= (self.vram[p][o] if p is not None else 0) << (8 * i)
        return v

    def _vram_write(self, lin, size, value):
        for i in range(size):
            p, o = self._split(lin + i)
            if p is None:
                continue
            b = (value >> (8 * i)) & 0xFF
            if self.grcg_mode & 0x80:
                for q in range(4):
                    if self.grcg_mode & (1 << q):
                        continue
                    if self.grcg_mode & 0x40:          # RMW
                        self.vram[q][o] = (self.vram[q][o] & ~b & 0xFF) | (self.tile[q] & b)
                    else:                              # TDW
                        self.vram[q][o] = self.tile[q]
            else:
                self.vram[p][o] = b

    def _split(self, lin):
        for p, b in enumerate(PLANE_LIN):
            if b <= lin < b + 0x8000:
                return p, lin - b
        return None, 0

    def _in(self, uc, port, size, ud):
        if port in (0x60, 0xA0):             # GDC status: bit 5 VSYNC, toggling
            self.vsync ^= 0x20
            return self.vsync
        self.ports.append(('in', port))
        return 0

    def _out(self, uc, port, size, value, ud):
        if port == 0x7C:
            self.grcg_mode = value & 0xFF
            self.tile_i = 0
        elif port == 0x7E:
            self.tile[self.tile_i & 3] = value & 0xFF
            self.tile_i += 1
        elif port == 0xA8:
            self.dac_index = value & 15
        elif port in (0xAA, 0xAC, 0xAE):         # green, red, blue
            self.dac[self.dac_index][{0xAC: 0, 0xAA: 1, 0xAE: 2}[port]] = value & 15
        else:
            self.ports.append(('out', port, value))

    def _intr(self, uc, intno, ud):
        ax = uc.reg_read(X.UC_X86_REG_AX)
        ah = ax >> 8
        if intno == 0x18:
            if ah == 0x14:
                self._kanji_rom(uc)
            elif ah == 0x02:
                uc.reg_write(X.UC_X86_REG_AX, (ax & 0xFF00) | (self.shift & 0xFF))
            elif ah == 0x01:
                uc.reg_write(X.UC_X86_REG_BX, uc.reg_read(X.UC_X86_REG_BX) & 0x00FF)
            return
        if intno == 0x33 and 0x33 not in HANDLERS:
            if ax == 6:
                uc.reg_write(X.UC_X86_REG_AX, self.right_button)
            return
        if intno in HANDLERS:                  # nested service call: vector it
            seg, off = HANDLERS[intno]
            ip, cs, fl = (uc.reg_read(X.UC_X86_REG_IP), uc.reg_read(X.UC_X86_REG_CS),
                          uc.reg_read(X.UC_X86_REG_FLAGS))
            sp = (uc.reg_read(X.UC_X86_REG_SP) - 6) & 0xFFFF
            ss = uc.reg_read(X.UC_X86_REG_SS)
            uc.mem_write(ss * 16 + sp, struct.pack('<HHH', ip, cs, fl))
            uc.reg_write(X.UC_X86_REG_SP, sp)
            uc.reg_write(X.UC_X86_REG_CS, seg + BASE)
            uc.reg_write(X.UC_X86_REG_IP, off)
            return
        raise RuntimeError('INT %02Xh AX=%04X at %04X:%04X not provided by the harness'
                           % (intno, ax, uc.reg_read(X.UC_X86_REG_CS), uc.reg_read(X.UC_X86_REG_IP)))

    def rom_glyph(self, jis):
        row, cell = (jis >> 8) & 0xFF, jis & 0xFF
        if row in (0x29, 0x2A, 0x2B):
            g = None if row == 0x2B else self.ank8.get(cell if row == 0x29 else (cell + 0x80) & 0xFF)
            return 1, g or bytes(16)
        return 2, self.k16.get(jis) or bytes(32)

    def _kanji_rom(self, uc):
        dx = uc.reg_read(X.UC_X86_REG_DX)
        bx, cx = uc.reg_read(X.UC_X86_REG_BX), uc.reg_read(X.UC_X86_REG_CX)
        w, rows = self.rom_glyph(dx)
        uc.mem_write(bx * 16 + cx, bytes([2, w]) + rows)

    # ---------------- calls ----------------
    def call(self, intno, ax=0, bx=0, cx=0, dx=0, si=0, di=0, ds_si=None, es_di=None,
             count=50000000):
        """Call INT intno's handler; returns a dict of the registers after the IRET.
        ds_si / es_di: bytes placed in scratch memory and pointed at."""
        uc = self.uc
        ds = es = SCRATCH
        if ds_si is not None:
            uc.mem_write(SCRATCH * 16, bytes(ds_si))
            si = 0
        if es_di is not None:
            uc.mem_write(SCRATCH * 16 + 0x4000, bytes(es_di))
            di = 0x4000
        sp = 0xFFF0 - 6
        uc.mem_write(STACK * 16 + sp, struct.pack('<HHH', 0, SENT, 0x0202))
        regs = ((X.UC_X86_REG_AX, ax), (X.UC_X86_REG_BX, bx), (X.UC_X86_REG_CX, cx),
                (X.UC_X86_REG_DX, dx), (X.UC_X86_REG_SI, si), (X.UC_X86_REG_DI, di),
                (X.UC_X86_REG_DS, ds), (X.UC_X86_REG_ES, es), (X.UC_X86_REG_SS, STACK),
                (X.UC_X86_REG_SP, sp), (X.UC_X86_REG_BP, 0), (X.UC_X86_REG_EFLAGS, 0x0002))
        for r, v in regs:
            uc.reg_write(r, v)
        seg, off = HANDLERS[intno]
        uc.reg_write(X.UC_X86_REG_CS, seg + BASE)
        uc.reg_write(X.UC_X86_REG_IP, off)
        uc.emu_start(self.lin(seg, off), SENT * 16, count=count)
        if uc.reg_read(X.UC_X86_REG_CS) != SENT:
            raise RuntimeError('INT %02Xh AX=%04X did not return' % (intno, ax))
        names = ('ax', 'bx', 'cx', 'dx', 'si', 'di', 'flags')
        ids = (X.UC_X86_REG_AX, X.UC_X86_REG_BX, X.UC_X86_REG_CX, X.UC_X86_REG_DX,
               X.UC_X86_REG_SI, X.UC_X86_REG_DI, X.UC_X86_REG_FLAGS)
        return {n: uc.reg_read(i) for n, i in zip(names, ids)}

    def planes(self):
        return [bytes(p[:32000]) for p in self.vram]

    def set_planes(self, planes):
        for p in range(4):
            self.vram[p][:32000] = planes[p][:32000]


def _selftest():
    emu = AdvBiosEmu(fonts=gamedir.build(None, 'fonts'))
    emu.call(0xF6, ax=0x0900, dx=0x8250)
    print('cursor', emu.ds_word(0x1A0), emu.ds_word(0x1A2),
          'set bytes', sum(sum(1 for b in p if b) for p in emu.planes()))


if __name__ == '__main__':
    sys.exit(_selftest())
