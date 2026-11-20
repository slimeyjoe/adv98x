#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""usdemu.py - run NOVA's original music driver (USDdrv / USDtrap V01.02, K.KONDO 1991,
segment 0328 of AdvBIOS 0.54 = NV.OV1) under the unicorn CPU emulator against a fake
PC-9801-26K board (YM2203), and record every OPN register write (VGM + TSV).

REQUIRES unicorn (run it with a Python that has it: docs/re/README.md "Tools").

Usage:
    usdemu.py SONG.USO [-o out.vgm] [--log out.tsv] [--loops N] [--seconds S] [--raw]
    usdemu.py --script "load NV01; play; wait 10; fadeout; wait 6; stop; wait 0.5" -o x.vgm
    usdemu.py --all [OUTDIR]          every *.USO -> OUTDIR/<name>.vgm (+ .tsv with --logs)
                                      default OUTDIR resources/derived/music/vgm
Options:
    --ov1 FILE       unpacked AdvBIOS (default resources/derived/exe/NV.OV1)
    --musdir DIR     where the .USO files are (default resources/original/pc98/A/MUS)
    --loops N        looping songs: record intro + N loop passes (default 2); the VGM loop
                     point is the start of the LAST recorded pass (the driver is in its
                     steady state there), the VGM ends where the next pass would start
    --seconds S      cap for songs that end or whose tracks loop independently (default 60)
    --raw            keep every write in the VGM (default: drop rewrites of unchanged plain
                     value registers and timer acknowledges; the TSV log is always complete)
    --phase A,B      delay (in OPN master clocks) from the play call to the next timer-A
                     and timer-B overflow; default: wherever the free-running timers are
Script commands (--script, separated by ';'):
    load NAME        = script `sound "NAME"`: INT F4h AH=02h (stop) then AH=00h (load)
    play             = `sound 1`:   INT F4h AH=01h
    volume N         = `sound 1 m`: INT F4h AH=07h, CX = N (signed volume offset, 0..-64)
    fadein           = `sound 3`:   INT F4h AH=04h
    fadeout          = `sound 2`:   INT F4h AH=03h
    stop             = `sound 0`:   INT F4h AH=02h
    fade P S F       INT F4h AH=05h BX=P CX=S DX=F (raw)
    enable M         INT F4h AH=06h AL=0 CX=M
    wait SECONDS     let the timers run
    ticks N          run until N more timer-A interrupts have been handled

How it works (see docs/re/usd-driver.md, "Emulation harness"):
  * NV.OV1 (plain MZ) is loaded at segment 1000h with its 71 relocations applied; addresses
    in this file are relative to that base, like the documentation.  Only the sound segment
    (0328) and its data segment (2B0F) are executed / used.
  * The driver's own start-up `sound_init` 0328:001C is called exactly as DoMainInit does:
    CPU-type query (INT F1h AH=11h, answered by this harness: 3 = "below 386"), chip
    detection through ports 188h/18Ah, IRQ hook, timer start, INT F4h hook, the built-in
    init sequence, a 60-VSYNC wait (port 60h bit 5, simulated at 56.42 Hz while the OPN
    timers interrupt), stop.
  * Fake hardware: YM2203 at 188h (address / status) and 18Ah (data).  Status bit 7 (busy)
    is never set; bits 0/1 are the timer A/B overflow flags.  Port A (reg 0Eh) reads FFh:
    bit 7 set = board jumpered to INT5 = IRQ 12 = vector 14h; joystick lines idle.  Slave
    PIC mask at port 0Ah.  The handler chained to (old vector 14h) is an IRET.
  * INT F2h AH=00h (AdvBIOS file read: DS:DX = name, ES:BX = buffer) is answered by this
    harness from --musdir.  INT F4h is the driver's real handler, reached through the
    vector it installed itself.
  * Timers are simulated in OPN master clocks (3 993 600 Hz): timer A overflows every
    72*(1024-NA) clocks, NA = (reg24h << 2) | (reg25h & 3); timer B every 1152*(256-NB),
    NB = reg 26h.  A new value is used from the next reload on, as in the chip.  When a
    timer overflows its flag is set (if enabled in reg 27h) and the interrupt handler is
    run; both flags may be set in one interrupt when the overflows coincide.  Register
    writes made in a handler are stamped with the overflow time (the handler takes no time).
Output:
  * VGM 1.51, YM2203 clock 3993600 (header 0x44), commands 55 aa dd, waits at 44100 Hz.
    Time 0 is the play call; whatever the driver wrote before it is emitted at time 0.
  * TSV: clock (master clocks since power-on), seconds since the play call, kind
    (I = init, C = API call, A / B / AB = interrupt with those timer flags), interrupt
    number, timer-A tick number since the last start (1 = first), register, value.
Python API:
    e = USDEmu();  e.load('NV01');  e.play();  e.run(seconds=10)
    e.writes -> [(clk, kind, irq_no, a_tick, reg, val)],  e.a_clk[k] = clock of tick k+1
"""
import argparse
import os
import struct
import sys

try:
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INSN, UC_HOOK_INTR, UC_HOOK_CODE
    from unicorn.x86_const import (UC_X86_INS_IN, UC_X86_INS_OUT, UC_X86_REG_AX, UC_X86_REG_BX,
                                   UC_X86_REG_CX, UC_X86_REG_DX, UC_X86_REG_SI, UC_X86_REG_DI,
                                   UC_X86_REG_SP, UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_ES,
                                   UC_X86_REG_SS, UC_X86_REG_IP, UC_X86_REG_FLAGS, UC_X86_REG_BP)
    _ALLREGS = (UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DX, UC_X86_REG_SI,
                UC_X86_REG_DI, UC_X86_REG_BP, UC_X86_REG_SP, UC_X86_REG_DS, UC_X86_REG_ES,
                UC_X86_REG_SS, UC_X86_REG_CS, UC_X86_REG_IP, UC_X86_REG_FLAGS)
except ImportError:             # the VGM writer below is still usable (usdmodel.py)
    Uc = None

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'source', 'tools'))
import gamedir  # noqa: E402
sys.path.insert(0, HERE)
import advbuild  # noqa: E402
OV1 = gamedir.derived(None, 'exe', 'NV.OV1')
MUSDIR = gamedir.part_dir('PACK.songs')
VGMDIR = gamedir.derived(None, 'music', 'vgm')

CLOCK = 3993600
BASE = 0x1000               # load segment of the image
SND = 0x0328                # sound code segment (relative to BASE)
DAT = 0x2B0F                # sound data segment (relative to BASE)
STUBSEG = 0xF000            # IRET stubs + sentinel
SENT_OFF = 0x0100
STACKSEG = 0x0800
NAMESEG = 0x0900            # scratch for file-name strings
FRAME = 70779               # one 24.83 kHz / 440-line frame in master clocks (56.42 Hz)
VSYNC_LEN = 1287            # VSYNC flag duration (8 lines)
PORT60_COST = 40            # master clocks consumed by one poll of port 60h (~10 us)
FM_WORK, FM_SIZE, SSG_WORK, SSG_SIZE = 0x0956, 0x57, 0x0A5B, 0x58


class EmuError(Exception):
    pass


class USDEmu:
    def __init__(self, ov1=None, musdir=None, cpu=3, verbose=False, init=True):
        if Uc is None:
            raise EmuError('usdemu needs the unicorn package (docs/re/README.md "Tools")')
        self.verbose = verbose
        self.musdir = musdir or MUSDIR
        self.cpu = cpu
        self.files = {}             # upper-case base name -> bytes (overrides musdir)
        self.uc = uc = Uc(UC_ARCH_X86, UC_MODE_16)
        uc.mem_map(0, 0x110000)
        uc.mem_write(STUBSEG * 16, b'\xCF' * 0x100)
        uc.mem_write(STUBSEG * 16 + SENT_OFF, b'\xF4' * 16)
        for v in range(256):
            uc.mem_write(v * 4, struct.pack('<HH', v, STUBSEG))
        self._load_mz(ov1 or OV1)
        # hardware
        self.reg = [0] * 256
        self.addr = 0
        self.status = 0
        self.pic = {0x02: 0xFF, 0x0A: 0xFF}
        self.clk = 0
        self.tA_next = None
        self.tB_next = None
        self.kind = 'I'
        self.irqno = 0
        self.atick = 0              # timer-A interrupts since the last start
        self.a_clk = []             # clock of each of them
        self.writes = []
        self.unknown_ports = {}
        self.t0 = 0                 # clock of the last start call
        self.irq_log = []           # (clk, flags) of every interrupt delivered
        self._in_irq = False
        self._fg = False
        self._irq_due = False
        uc.hook_add(UC_HOOK_INSN, self._in, None, 1, 0, UC_X86_INS_IN)
        uc.hook_add(UC_HOOK_INSN, self._out, None, 1, 0, UC_X86_INS_OUT)
        uc.hook_add(UC_HOOK_INTR, self._intr)
        sent = STUBSEG * 16 + SENT_OFF
        uc.hook_add(UC_HOOK_CODE, lambda u, a, s, d: u.emu_stop(), None, sent, sent)
        if init:
            self.sound_init()

    # ---------------- image ----------------
    def _load_mz(self, path):
        d = advbuild.check(open(path, 'rb').read(), advbuild.BIOS, path)
        if d[:2] != b'MZ':
            raise EmuError('%s: not an MZ file' % path)
        last, pages, nrel, hdr, _mn, _mx, ss, sp, _ck, ip, cs, relo = struct.unpack_from('<12H', d, 2)
        size = pages * 512 - ((512 - last) if last else 0)
        img = bytearray(d[hdr * 16:size])
        for i in range(nrel):
            o, s = struct.unpack_from('<HH', d, relo + i * 4)
            lin = s * 16 + o
            struct.pack_into('<H', img, lin, (struct.unpack_from('<H', img, lin)[0] + BASE) & 0xFFFF)
        self.uc.mem_write(BASE * 16, bytes(img))
        if bytes(img[SND * 16 + 0x11F:SND * 16 + 0x125]) != b'USDdrv':
            raise EmuError('USDdrv signature not found at 0328:011F - wrong NV.OV1?')

    def snd(self, off, n):
        return bytes(self.uc.mem_read((BASE + SND) * 16 + off, n))

    def snd_w(self, off):
        return struct.unpack('<H', self.snd(off, 2))[0]

    def dat(self, off, n):
        return bytes(self.uc.mem_read((BASE + DAT) * 16 + off, n))

    def channel(self, i):
        """raw work area of channel i (0-2 FM, 3-5 SSG)"""
        return self.snd(FM_WORK + FM_SIZE * i, FM_SIZE) if i < 3 else \
            self.snd(SSG_WORK + SSG_SIZE * (i - 3), SSG_SIZE)

    def active(self):
        return [self.channel(i)[0] for i in range(6)]

    def master(self):
        """(volume offset, fade period, fade counter, fade step, priority threshold)"""
        s16 = lambda v: v - 65536 if v & 0x8000 else v
        return (s16(self.snd_w(0x0B65)), self.snd_w(0x0B69), self.snd_w(0x0B6B),
                s16(self.snd_w(0x0B67)), self.snd(0x0B63, 1)[0])

    # ---------------- hardware ----------------
    def _periodA(self):
        return 72 * (1024 - ((self.reg[0x24] << 2) | (self.reg[0x25] & 3)))

    def _periodB(self):
        return 1152 * (256 - self.reg[0x26])

    def _next_event(self):
        c = [t for t in (self.tA_next, self.tB_next) if t is not None]
        return min(c) if c else None

    def _in(self, uc, port, size, ud):
        if port == 0x188:
            return self.status & 3
        if port == 0x18A:
            if self.addr == 0x0E:
                return 0xFF
            return self.reg[self.addr]
        if port in self.pic:
            return self.pic[port]
        if port == 0x60:
            self.clk += PORT60_COST
            if self._fg:
                ev = self._next_event()
                if ev is not None and ev <= self.clk:
                    self._irq_due = True
                    uc.emu_stop()
            return 0x20 if (self.clk % FRAME) < VSYNC_LEN else 0x00
        self.unknown_ports[('in', port)] = self.unknown_ports.get(('in', port), 0) + 1
        return 0xFF

    def _out(self, uc, port, size, value, ud):
        value &= 0xFF
        if port == 0x188:
            self.addr = value
        elif port == 0x18A:
            a = self.addr
            self.reg[a] = value
            self.writes.append((self.clk, self.kind, self.irqno, self.atick, a, value))
            if a == 0x27:
                self._reg27(value)
        elif port in self.pic:
            self.pic[port] = value
        elif port == 0x5F:
            pass
        else:
            self.unknown_ports[('out', port)] = self.unknown_ports.get(('out', port), 0) + 1

    def _reg27(self, v):
        if v & 0x10:
            self.status &= ~1
        if v & 0x20:
            self.status &= ~2
        if v & 1:
            if self.tA_next is None:
                self.tA_next = self.clk + self._periodA()
        else:
            self.tA_next = None
        if v & 2:
            if self.tB_next is None:
                self.tB_next = self.clk + self._periodB()
        else:
            self.tB_next = None

    def _intr(self, uc, intno, ud):
        ah = (uc.reg_read(UC_X86_REG_AX) >> 8) & 0xFF
        if intno == 0xF1:
            if ah == 0x11:                  # CPU type (advbios.md 4.1)
                uc.reg_write(UC_X86_REG_AX, (ah << 8) | self.cpu)
                return
            raise EmuError('INT F1h AH=%02X not provided by the harness' % ah)
        if intno == 0xF2:
            if ah != 0:
                raise EmuError('INT F2h AH=%02X not provided by the harness' % ah)
            ds, dx = uc.reg_read(UC_X86_REG_DS), uc.reg_read(UC_X86_REG_DX)
            es, bx = uc.reg_read(UC_X86_REG_ES), uc.reg_read(UC_X86_REG_BX)
            name = bytes(uc.mem_read(ds * 16 + dx, 80)).split(b'\0')[0].decode('ascii', 'replace')
            data = self._find_file(name)
            fl = uc.reg_read(UC_X86_REG_FLAGS)
            if data is None:
                uc.reg_write(UC_X86_REG_FLAGS, fl | 1)
            else:
                uc.mem_write(es * 16 + bx, data)
                uc.reg_write(UC_X86_REG_FLAGS, fl & ~1)
            return
        off, seg = struct.unpack('<HH', uc.mem_read(intno * 4, 4))
        if seg == STUBSEG:
            return
        ip, cs, fl = (uc.reg_read(UC_X86_REG_IP), uc.reg_read(UC_X86_REG_CS),
                      uc.reg_read(UC_X86_REG_FLAGS))
        sp = (uc.reg_read(UC_X86_REG_SP) - 6) & 0xFFFF
        ss = uc.reg_read(UC_X86_REG_SS)
        uc.mem_write(ss * 16 + sp, struct.pack('<HHH', ip, cs, fl))
        uc.reg_write(UC_X86_REG_SP, sp)
        uc.reg_write(UC_X86_REG_FLAGS, fl & ~0x0300)
        uc.reg_write(UC_X86_REG_CS, seg)
        uc.reg_write(UC_X86_REG_IP, off)

    def _find_file(self, name):
        base = name.replace('\\', '/').split('/')[-1].upper()
        if ':' in base:
            base = base.split(':')[-1]
        if base in self.files:
            return self.files[base]
        if not base.endswith('.USO') and base + '.USO' in self.files:
            return self.files[base + '.USO']
        for fn in os.listdir(self.musdir):
            if fn.upper() == base or fn.upper() == base + '.USO':
                with open(os.path.join(self.musdir, fn), 'rb') as f:
                    return f.read()
        return None

    # ---------------- execution ----------------
    def _emu(self, cs, ip, limit=50000000):
        uc = self.uc
        uc.reg_write(UC_X86_REG_CS, cs)
        uc.reg_write(UC_X86_REG_IP, ip)
        uc.emu_start(cs * 16 + ip, STUBSEG * 16 + SENT_OFF, count=limit)

    def _at_sentinel(self):
        uc = self.uc
        return uc.reg_read(UC_X86_REG_CS) == STUBSEG and uc.reg_read(UC_X86_REG_IP) == SENT_OFF

    def _push(self, *words):
        uc = self.uc
        sp = uc.reg_read(UC_X86_REG_SP)
        ss = uc.reg_read(UC_X86_REG_SS)
        for w in words:
            sp = (sp - 2) & 0xFFFF
            uc.mem_write(ss * 16 + sp, struct.pack('<H', w & 0xFFFF))
        uc.reg_write(UC_X86_REG_SP, sp)

    def _foreground(self, cs, ip):
        """run foreground code until it returns to the sentinel; OPN interrupts that become
        due while it polls port 60h are delivered in between"""
        uc = self.uc
        self._fg = True
        try:
            while True:
                self._irq_due = False
                self._emu(cs, ip)
                if self._at_sentinel():
                    return
                if not self._irq_due:
                    raise EmuError('foreground code stopped at %04X:%04X' % (
                        uc.reg_read(UC_X86_REG_CS), uc.reg_read(UC_X86_REG_IP)))
                cs, ip = uc.reg_read(UC_X86_REG_CS), uc.reg_read(UC_X86_REG_IP)
                saved = [uc.reg_read(r) for r in _ALLREGS]
                self._fg = False
                now = self.clk
                while True:
                    ev = self._next_event()
                    if ev is None or ev > now:
                        break
                    self.step()
                self.clk = now
                self._fg = True
                for r, v in zip(_ALLREGS, saved):
                    uc.reg_write(r, v)
        finally:
            self._fg = False

    def far_call(self, off, ax=0, bx=0, cx=0, dx=0, si=0, di=0, ds=None):
        uc = self.uc
        uc.reg_write(UC_X86_REG_SS, STACKSEG)
        uc.reg_write(UC_X86_REG_SP, 0xFFF0)
        for r, v in ((UC_X86_REG_AX, ax), (UC_X86_REG_BX, bx), (UC_X86_REG_CX, cx),
                     (UC_X86_REG_DX, dx), (UC_X86_REG_SI, si), (UC_X86_REG_DI, di)):
            uc.reg_write(r, v)
        uc.reg_write(UC_X86_REG_DS, ds if ds is not None else NAMESEG)
        uc.reg_write(UC_X86_REG_ES, NAMESEG)
        uc.reg_write(UC_X86_REG_FLAGS, 0x0202)
        self._push(STUBSEG, SENT_OFF)
        self._foreground(BASE + SND, off)

    def int_f4(self, ah, al=0, bx=0, cx=0, dx=0, ds=None):
        """software INT F4h through the vector the driver installed; returns (ax, bx, carry)"""
        uc = self.uc
        off, seg = struct.unpack('<HH', uc.mem_read(0xF4 * 4, 4))
        if seg == STUBSEG:
            raise EmuError('INT F4h is not installed')
        uc.reg_write(UC_X86_REG_SS, STACKSEG)
        uc.reg_write(UC_X86_REG_SP, 0xFFF0)
        uc.reg_write(UC_X86_REG_AX, ((ah & 0xFF) << 8) | (al & 0xFF))
        uc.reg_write(UC_X86_REG_BX, bx & 0xFFFF)
        uc.reg_write(UC_X86_REG_CX, cx & 0xFFFF)
        uc.reg_write(UC_X86_REG_DX, dx & 0xFFFF)
        uc.reg_write(UC_X86_REG_DS, ds if ds is not None else NAMESEG)
        uc.reg_write(UC_X86_REG_ES, NAMESEG)
        uc.reg_write(UC_X86_REG_FLAGS, 0x0002)
        self._push(0x0202, STUBSEG, SENT_OFF)
        self.kind = 'C'
        self._foreground(seg, off)
        # the handler's IRET popped the frame: the returned flags are live
        return (uc.reg_read(UC_X86_REG_AX), uc.reg_read(UC_X86_REG_BX),
                uc.reg_read(UC_X86_REG_FLAGS) & 1)

    @property
    def irq_vec(self):
        """vector the driver chose from the board's jumper (14h = IRQ 12, 15h = IRQ 13)"""
        return self.snd(0x0578, 1)[0]

    def irq_call(self):
        uc = self.uc
        off, seg = struct.unpack('<HH', uc.mem_read(self.irq_vec * 4, 4))
        uc.reg_write(UC_X86_REG_SS, STACKSEG)
        uc.reg_write(UC_X86_REG_SP, 0x7FF0)
        uc.reg_write(UC_X86_REG_FLAGS, 0x0002)
        self._push(0x0202, STUBSEG, SENT_OFF)
        self._emu(seg, off)
        if not self._at_sentinel():
            raise EmuError('interrupt handler did not return')

    def step(self):
        """advance to the next timer overflow and run the interrupt handler; returns the
        flags that were raised ('A', 'B', 'AB' or '')"""
        t = self._next_event()
        if t is None:
            raise EmuError('no timer running')
        kind = ''
        if self.tA_next == t:
            self.tA_next += self._periodA()
            if self.reg[0x27] & 4:
                self.status |= 1
                kind += 'A'
        if self.tB_next == t:
            self.tB_next += self._periodB()
            if self.reg[0x27] & 8:
                self.status |= 2
                kind += 'B'
        self.clk = max(self.clk, t)
        mask = 0x10 if self.irq_vec == 0x14 else 0x20
        if kind and not (self.pic[0x0A] & mask):
            self.irqno += 1
            self.kind = kind
            if 'A' in kind:
                self.atick += 1
                self.a_clk.append(t)
            self.irq_log.append((t, kind))
            self.irq_call()
        return kind

    def run(self, seconds=None, aticks=None, until=None):
        """run interrupts for `seconds`, or until `aticks` more timer-A interrupts were
        handled, or until callable until(self) is true (checked after every interrupt)"""
        end = self.clk + int(round(seconds * CLOCK)) if seconds is not None else None
        target = self.atick + aticks if aticks is not None else None
        while True:
            if target is not None and self.atick >= target:
                break
            ev = self._next_event()
            if end is not None and (ev is None or ev > end):
                self.clk = end
                break
            self.step()
            if until is not None and until(self):
                break

    # ---------------- the driver's services ----------------
    def sound_init(self):
        """AdvBIOS start-up: far call 0328:001C"""
        self.kind = 'I'
        self.far_call(0x001C)
        off, seg = struct.unpack('<HH', self.uc.mem_read(0xF4 * 4, 4))
        if seg != BASE + SND:
            raise EmuError('driver did not install INT F4h (chip not detected?)')
        self.ninit = len(self.writes)

    def _name(self, name):
        if '.' not in name:
            name += '.USO'
        if '\\' not in name:
            name = '\\MUS\\' + name
        self.uc.mem_write(NAMESEG * 16 + 0x100, name.encode('ascii') + b'\0')
        return 0x100

    def load(self, name):
        """script `sound "NAME"`: stop, then load (returns carry of the load)"""
        self.int_f4(0x02)
        return self.int_f4(0x00, bx=self._name(name))[2]

    def load_data(self, data, name='SONG.USO'):
        self.files[name.upper()] = bytes(data)
        return self.load(name)

    def load_bank(self, data, name='BANK.USO'):
        """INT F4h AH=10h: stop everything, read an effect bank to 2B0F:3000"""
        self.files[name.upper()] = bytes(data)
        return self.int_f4(0x10, bx=self._name(name))[2]

    def play_se(self, index):
        """INT F4h AH=11h: start entry BX of the effect bank"""
        return self.int_f4(0x11, bx=index)[2]

    def _started(self):
        self.t0 = self.clk
        self.atick = 0
        self.a_clk = []

    def set_phase(self, a=None, b=None):
        """re-phase the free-running timers: next overflow of A / B in `a` / `b` clocks"""
        if a is not None and self.tA_next is not None:
            self.tA_next = self.clk + a
        if b is not None and self.tB_next is not None:
            self.tB_next = self.clk + b

    def phase(self):
        return (self.tA_next - self.clk, self.tB_next - self.clk)

    def play(self):
        self._started()
        return self.int_f4(0x01)[2]

    def volume(self, n):
        self._started()
        return self.int_f4(0x07, cx=n)[2]

    def fade_in(self):
        self._started()
        return self.int_f4(0x04)[2]

    def fade_out(self):
        return self.int_f4(0x03)[2]

    def stop(self):
        return self.int_f4(0x02)[2]

    def stop_owner(self, owner):
        """internal service AH=84h: usd_stop with DX = owner (0 = everything)"""
        return self.int_f4(0x84, dx=owner)[2]

    def fade(self, period, step, flag=0):
        return self.int_f4(0x05, bx=period, cx=step, dx=flag)[2]

    def enable(self, mask):
        return self.int_f4(0x06, al=0, cx=mask)[0]


# ---------------- VGM ----------------
def write_vgm(path, writes, t0, end_clk, loop_clk=None, prune=True):
    """writes: [(clk, kind, irq, atick, reg, val)].  Time 0 = t0 (earlier writes at 0).
    loop_clk: clock of the loop point (first write with clk >= loop_clk starts the loop)."""
    out = bytearray()
    cur = 0
    loop_off = None
    loop_samp = None

    def samp(clk):
        return int(round(max(clk - t0, 0) * 44100 / CLOCK))

    def wait_to(target):
        nonlocal cur
        n = target - cur
        while n > 0:
            if n == 735:
                out.append(0x62); k = 735
            elif n == 882:
                out.append(0x63); k = 882
            elif n <= 16:
                out.append(0x70 + n - 1); k = n
            else:
                k = min(n, 0xFFFF)
                out.append(0x61); out.extend(struct.pack('<H', k))
            n -= k
            cur += k

    shadow = {}
    fpair = {}
    pending = None           # held A4h+ch write (latch) until its A0h+ch arrives
    for w in writes:
        clk, reg, val = w[0], w[4], w[5]
        if clk >= end_clk:
            break
        if loop_clk is not None and loop_off is None and clk >= loop_clk:
            if pending:
                wait_to(samp(pending[0])); out += bytes((0x55, pending[1], pending[2])); pending = None
            wait_to(samp(loop_clk))
            loop_off, loop_samp = len(out), cur
            shadow, fpair = {}, {}
        if prune:
            if 0x24 <= reg <= 0x26:
                continue
            if reg == 0x27:
                if 0x27 in shadow and (shadow[0x27] & 0xC0) == (val & 0xC0):
                    continue
                shadow[0x27] = val
            elif 0xA4 <= reg <= 0xA6:
                pending = (clk, reg, val)
                continue
            elif 0xA0 <= reg <= 0xA2:
                if pending and pending[1] == reg + 4:
                    pair = (pending[2], val)
                    if fpair.get(reg) == pair:
                        pending = None
                        continue
                    fpair[reg] = pair
                    wait_to(samp(pending[0])); out += bytes((0x55, pending[1], pending[2]))
                    pending = None
                else:
                    fpair.pop(reg, None)
            elif reg <= 0x0C or 0x30 <= reg <= 0x9F or 0xB0 <= reg <= 0xB6:
                if shadow.get(reg) == val:
                    continue
                shadow[reg] = val
        wait_to(samp(clk))
        out += bytes((0x55, reg, val))
    if loop_clk is not None and loop_off is None:
        wait_to(samp(loop_clk))
        loop_off, loop_samp = len(out), cur
    wait_to(samp(end_clk))
    out.append(0x66)
    hdr = bytearray(0x80)
    hdr[0:4] = b'Vgm '
    struct.pack_into('<I', hdr, 0x04, 0x80 + len(out) - 4)
    struct.pack_into('<I', hdr, 0x08, 0x151)
    struct.pack_into('<I', hdr, 0x18, cur)
    if loop_off is not None:
        struct.pack_into('<I', hdr, 0x1C, 0x80 + loop_off - 0x1C)
        struct.pack_into('<I', hdr, 0x20, cur - loop_samp)
    struct.pack_into('<I', hdr, 0x34, 0x80 - 0x34)
    struct.pack_into('<I', hdr, 0x44, CLOCK)
    with open(path, 'wb') as f:
        f.write(hdr + out)
    return 0x80 + len(out), cur, (cur - loop_samp) if loop_off is not None else 0


def write_log(path, writes, t0):
    with open(path, 'w') as f:
        f.write('clock\tseconds\tkind\tirq\ta_tick\treg\tval\n')
        for clk, kind, irq, atick, reg, val in writes:
            f.write('%d\t%.6f\t%s\t%d\t%d\t%02X\t%02X\n' % (clk, (clk - t0) / CLOCK, kind, irq, atick, reg, val))


# ---------------- rendering ----------------
MAX_LOOP_TICKS = 40000      # songs whose tracks loop independently (lcm of loops beyond this)


def render_song(path, out=None, log=None, loops=2, seconds=60.0, prune=True, phase=None,
                ov1=None, musdir=None, emu=None):
    """record one song as the scripts play it: sound "file" + sound 1.  Returns a dict."""
    sys.path.insert(0, HERE)
    import usoinfo
    name = os.path.basename(path)
    data = open(path, 'rb').read()
    song = usoinfo.parse(data, name)
    tm = usoinfo.song_timing(song)
    e = emu or USDEmu(ov1, musdir or os.path.dirname(os.path.abspath(path)))
    e.files[name.upper()] = data
    if e.load(name):
        raise EmuError('driver refused to load %s' % name)
    if phase:
        e.set_phase(*phase)
    if e.play():
        raise EmuError('driver refused to play %s' % name)
    info = {'name': name, 'emu': e, 'timing': tm}
    loop_clk = None
    if tm['loops'] and tm['loop'] <= MAX_LOOP_TICKS:
        n = max(loops, 1)
        want = tm['intro'] + n * tm['loop'] + 1
        e.run(aticks=want)
        end_clk = e.a_clk[want - 1]
        loop_clk = e.a_clk[tm['intro'] + (n - 1) * tm['loop']]
        info['kind'] = 'loop'
    elif tm['loops']:
        e.run(seconds=seconds)
        end_clk = e.clk
        info['kind'] = 'free'
    else:
        cap = e.clk + int(seconds * CLOCK * 10)
        e.run(until=lambda x: not any(x.active()) or x.clk > cap)
        info['end_tick'] = e.atick
        e.run(seconds=0.25)
        end_clk = e.clk
        info['kind'] = 'end'
    info['end_clk'], info['loop_clk'] = end_clk, loop_clk
    info['seconds'] = (end_clk - e.t0) / CLOCK
    info['loop_seconds'] = (end_clk - loop_clk) / CLOCK if loop_clk is not None else 0.0
    if out:
        info['vgm'] = write_vgm(out, e.writes, e.t0, end_clk, loop_clk, prune)
    if log:
        write_log(log, e.writes, e.t0)
    return info


def run_script(text, e=None, ov1=None, musdir=None, verbose=False):
    e = e or USDEmu(ov1, musdir)
    for cmd in text.split(';'):
        p = cmd.split()
        if not p:
            continue
        c = p[0].lower()
        if c == 'load':
            cf = e.load(p[1])
        elif c == 'play':
            cf = e.play()
        elif c == 'volume':
            cf = e.volume(int(p[1], 0))
        elif c == 'fadein':
            cf = e.fade_in()
        elif c == 'fadeout':
            cf = e.fade_out()
        elif c == 'stop':
            cf = e.stop()
        elif c == 'fade':
            cf = e.fade(int(p[1], 0), int(p[2], 0), int(p[3], 0) if len(p) > 3 else 0)
        elif c == 'enable':
            cf = e.enable(int(p[1], 0))
        elif c == 'wait':
            e.run(seconds=float(p[1])); cf = 0
        elif c == 'ticks':
            e.run(aticks=int(p[1])); cf = 0
        elif c == 'phase':
            e.set_phase(int(p[1], 0), int(p[2], 0)); cf = 0
        else:
            raise EmuError('unknown script command %r' % cmd)
        if verbose:
            print('%10.4f s  %-16s cf=%d  master=%s active=%s' % (
                e.clk / CLOCK, cmd.strip(), cf, e.master(), e.active()))
    return e


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('song', nargs='?')
    ap.add_argument('-o', '--out')
    ap.add_argument('--log')
    ap.add_argument('--loops', type=int, default=2)
    ap.add_argument('--seconds', type=float, default=60.0)
    ap.add_argument('--raw', action='store_true')
    ap.add_argument('--phase')
    ap.add_argument('--script')
    ap.add_argument('--all', nargs='?', const=VGMDIR)
    ap.add_argument('--logs', action='store_true', help='with --all: also write <name>.tsv')
    ap.add_argument('--ov1')
    ap.add_argument('--musdir')
    ap.add_argument('-v', '--verbose', action='store_true')
    a = ap.parse_args()
    phase = tuple(int(x, 0) for x in a.phase.split(',')) if a.phase else None
    if a.all:
        os.makedirs(a.all, exist_ok=True)
        md = a.musdir or MUSDIR
        for fn in sorted(os.listdir(md)):
            if not fn.upper().endswith('.USO'):
                continue
            stem = os.path.splitext(fn)[0]
            info = render_song(os.path.join(md, fn), os.path.join(a.all, stem + '.vgm'),
                               os.path.join(a.all, stem + '.tsv') if a.logs else None,
                               a.loops, a.seconds, not a.raw, phase, a.ov1, md)
            size, smp, lsmp = info['vgm']
            print('%-12s %-4s %7d bytes  %8.2f s  loop %7.2f s  writes %d' % (
                fn, info['kind'], size, smp / 44100.0, lsmp / 44100.0, len(info['emu'].writes)))
        return 0
    if a.script:
        e = run_script(a.script, ov1=a.ov1, musdir=a.musdir, verbose=a.verbose)
        if a.out:
            size, smp, _ = write_vgm(a.out, e.writes, e.writes[e.ninit][0] if len(e.writes) > e.ninit else 0,
                                     e.clk, None, not a.raw)
            print('%s: %d bytes, %.2f s' % (a.out, size, smp / 44100.0))
        if a.log:
            write_log(a.log, e.writes, e.t0)
        if e.unknown_ports:
            print('unknown ports:', e.unknown_ports)
        return 0
    if not a.song:
        ap.error('need SONG.USO, --script or --all')
    path = a.song if os.path.exists(a.song) else os.path.join(a.musdir or MUSDIR, a.song)
    if not os.path.exists(path) and os.path.exists(path + '.USO'):
        path += '.USO'
    out = a.out or (os.path.splitext(os.path.basename(path))[0] + '.vgm' if not a.log else None)
    info = render_song(path, out, a.log, a.loops, a.seconds, not a.raw, phase, a.ov1,
                       a.musdir or os.path.dirname(os.path.abspath(path)))
    e = info['emu']
    print('%s: %s, %.2f s recorded (loop %.2f s), %d writes, %d interrupts, %d timer-A ticks' % (
        info['name'], info['kind'], info['seconds'], info['loop_seconds'], len(e.writes), e.irqno, e.atick))
    if out:
        print('%s: %d bytes' % (out, info['vgm'][0]))
    if e.unknown_ports:
        print('unknown ports:', e.unknown_ports)
    return 0


if __name__ == '__main__':
    sys.exit(main())
