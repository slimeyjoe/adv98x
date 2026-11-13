#!/usr/bin/env python3
"""Unpack Adv98V executables: Ides "TC0" encryption layers, then Microsoft EXEPACK.

Usage:  python3 -I re-tools/exeunpack.py IN.OVL OUT.EXE [--keep-stages DIR]

TC0 (after Valley Bell's adv98_dec): the MZ entry point is a stub
  +00 call +14h   +03 "TC0"   +06 key   +08 length   +0A start (100h = image start)
  +0C IP  +0E CS  +10 SP  +12 SS   +14 code
and every image byte is XORed with bits 6..13 of a 16-bit LCG  key = key*mult + add.
Layers are peeled until the entry point no longer carries the signature.
EXEPACK: standard backward RLE (B0/B1 fill, B2/B3 copy) and a packed relocation table.
Stdlib only; the input is only read.
"""
import struct
import sys


def u16(d, o):
    return struct.unpack_from('<H', d, o)[0]


def entry(d):
    return u16(d, 8) * 16 + u16(d, 0x16) * 16 + u16(d, 0x14)


def tc0_layer(d):
    """Return the image with one TC0 layer removed, or None if there is none."""
    e = entry(d)
    if d[e + 3:e + 6] != b'TC0':
        return None
    base = u16(d, 8) * 16
    key, length, start = struct.unpack_from('<HHH', d, e + 6)
    if start != 0x100:
        raise ValueError('TC0 start %#x' % start)
    mult, add = 0x2711, 0x3619
    for p in range(e + 0x14, e + 0x60):          # mov si,mult ... add ax,add
        if d[p] == 0xBE and d[p + 5] == 0x05:
            mult, add = u16(d, p + 1), u16(d, p + 6)
            break
    out = bytearray(d[:base + length])
    for i in range(length):
        key = (key * mult + add) & 0xFFFF
        out[base + i] ^= (key >> 6) & 0xFF
    out[0x14:0x18] = d[e + 0x0C:e + 0x10]        # IP, CS
    out[0x10:0x12] = d[e + 0x10:e + 0x12]        # SP
    out[0x0E:0x10] = d[e + 0x12:e + 0x14]        # SS
    n = len(out)
    struct.pack_into('<HH', out, 2, n & 0x1FF, (n + 0x1FF) // 0x200)
    return bytes(out), dict(key=u16(d, e + 6), length=length, mult=mult, add=add)


def exepack(d):
    """Decompress an EXEPACK MZ image into a plain MZ file."""
    base = u16(d, 8) * 16
    cs = u16(d, 0x16)
    h = base + cs * 16
    real_ip, real_cs, _mem, epsize, real_sp, real_ss, dest_len = struct.unpack_from('<7H', d, h)
    p = h + 14
    skip = 1
    if d[p:p + 2] != b'RB':
        skip = u16(d, p)
        p += 2
    if d[p:p + 2] != b'RB':
        raise ValueError('no EXEPACK signature')
    hdr_len = p + 2 - h
    image = bytearray(d[base:h])
    out = bytearray(dest_len * 16)
    out[:len(image)] = image
    src = len(image) - (skip - 1) * 16
    dst = dest_len * 16
    while out[src - 1] == 0xFF:
        src -= 1
    while True:
        cmd = out[src - 1]
        n = out[src - 3] | out[src - 2] << 8
        src -= 3
        if cmd & 0xFE == 0xB0:
            src -= 1
            v = out[src]
            dst -= n
            out[dst:dst + n] = bytes([v]) * n
        elif cmd & 0xFE == 0xB2:
            src -= n
            dst -= n
            out[dst:dst + n] = out[src:src + n]
        else:
            raise ValueError('bad EXEPACK command %#x' % cmd)
        if cmd & 1:
            break
    # relocation table: 16 groups (segment 0x0000, 0x1000, ...), each count + offsets
    stub_end = h + epsize
    err = d.find(b'Packed file is corrupt', h, stub_end)
    if err < 0:
        raise ValueError('EXEPACK error string not found')
    p = err + 22
    relocs = []
    for seg in range(16):
        n = u16(d, p)
        p += 2
        for _ in range(n):
            relocs.append((u16(d, p), seg << 12))
            p += 2
    if p != stub_end:
        raise ValueError('relocation table ends at %#x, stub at %#x' % (p, stub_end))
    hsize = (0x1C + 4 * len(relocs) + 0x1FF) & ~0x1FF
    total = hsize + len(out)
    hdr = bytearray(hsize)
    minalloc = max(0, u16(d, 0x0A) - (dest_len - (len(d) - base + 15) // 16))
    struct.pack_into('<2s13H', hdr, 0, b'MZ', total & 0x1FF, (total + 0x1FF) // 0x200,
                     len(relocs), hsize // 16, u16(d, 0x0A), u16(d, 0x0C), real_ss, real_sp, 0,
                     real_ip, real_cs, 0x1C, 0)
    del minalloc
    for i, (off, seg) in enumerate(relocs):
        struct.pack_into('<HH', hdr, 0x1C + 4 * i, off, seg)
    info = dict(image=len(out), relocs=len(relocs), cs_ip='%04X:%04X' % (real_cs, real_ip),
                ss_sp='%04X:%04X' % (real_ss, real_sp), stub_header=hdr_len)
    return bytes(hdr) + bytes(out), info


def unpack(d, log=print):
    n = 0
    while True:
        r = tc0_layer(d)
        if r is None:
            break
        d, info = r
        n += 1
        log('TC0 layer %d: %s' % (n, info))
    d, info = exepack(d)
    log('EXEPACK: %s' % info)
    return d


def main(a):
    if len(a) < 3:
        sys.exit(__doc__)
    out = unpack(open(a[1], 'rb').read())
    open(a[2], 'wb').write(out)


if __name__ == '__main__':
    main(sys.argv)
