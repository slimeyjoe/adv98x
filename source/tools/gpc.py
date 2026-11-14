#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""GPC picture decoder (PC-98 "PC98)GPCFILE" format, as used by NOVA / Adv98V 1.70).

A GPC file holds one 16-colour picture (4 bit planes), an optional 16-entry
12-bit palette and the screen position the picture is meant to be drawn at.
Full description: docs/re/graphics-formats.md.  Summary (little-endian):

  00  16  "PC98)GPCFILE   \\0"
  10  u32 row interleave step N (0 or 1 = rows stored in natural order)
  14  u32 offset of the palette block (0 = no palette)
  18  u32 offset of the image block
  1C  u32 0
  20  u32 file size
  24  12 x 0
  palette block:  u16 count (16), u16 bytes per entry (2),
                  count x u16 = 0x0GRB (4 bits each)
  image block:    u16 width, u16 height, u32 size of (this block + stream),
                  u16 bits per pixel (4), u16 x, u16 y, u16 0, then the stream

The stream expands (two-level zero-suppression bitmaps) to height rows of
1 + 4*ceil(width/8) bytes: a filter byte followed by the four bit planes of
that row side by side (plane 0 first).  Filter byte F != 0 means the row is a
running XOR along F interleaved chains (the accumulator is NOT reset between
chains); every row but the first is additionally XORed with the row stored
before it; finally the stored rows are dealt out to screen rows 0, N, 2N, ...,
1, N+1, ...

This decoder was written from the format description by Kirinn Bunnylin
(SuperSakura, doc/gfx/gpc-gpa.md, relayed by the lime-juice project) and
checked against the decoder in the game's own AdvBIOS (NV.OV1) and against the
Windows release's Pi pictures; see re-tools/gpc_verify.py.  No code was copied.

Library use:
    header, palette, w, h, x, y, pixels = gpc.decode(open('NV01.GPC','rb').read())
      palette  list of 16 (r, g, b), each 0..15 (None if the file has no palette)
      pixels   bytes, w*h palette indexes, row-major

Command line:
    gpc.py info FILE...
    gpc.py png  FILE... -o DIR [--screen]

Only the Python standard library is used.
"""
import os
import struct
import sys
import zlib

MAGIC = b'PC98)GPCFILE   \x00'

# _SPREAD[p][b]: the 8 pixels of plane byte b as a 64-bit big-endian integer,
# one byte per pixel, with bit p set where the plane bit is set.
_SPREAD = [[sum(((b >> (7 - i)) & 1) << (8 * (7 - i) + p) for i in range(8))
            for b in range(256)] for p in range(4)]


class GpcError(ValueError):
    pass


def parse_header(data):
    """Return a dict of every header field (no pixel decoding)."""
    if data[:16] != MAGIC:
        raise GpcError('not a GPC file (bad signature)')
    interleave, pal_ofs, img_ofs = struct.unpack_from('<III', data, 0x10)
    hdr = {
        'interleave': interleave,
        'palette_offset': pal_ofs,
        'image_offset': img_ofs,
        'reserved_1c': struct.unpack_from('<I', data, 0x1C)[0],
        'file_size_field': struct.unpack_from('<I', data, 0x20)[0],
        'reserved_24': bytes(data[0x24:0x30]),
        'file_size': len(data),
    }
    if pal_ofs:
        count, esize = struct.unpack_from('<HH', data, pal_ofs)
        hdr['palette_count'] = count
        hdr['palette_entry_size'] = esize
        raw = struct.unpack_from('<%dH' % count, data, pal_ofs + 4)
        hdr['palette_raw'] = list(raw)
        hdr['palette_trailer'] = bytes(data[pal_ofs + 4 + count * esize:img_ofs]) \
            if img_ofs > pal_ofs else b''
    else:
        hdr['palette_count'] = 0
        hdr['palette_entry_size'] = 0
        hdr['palette_raw'] = None
        hdr['palette_trailer'] = b''
    (w, h, size, bpp, x, y, unk) = struct.unpack_from('<HHIHHHH', data, img_ofs)
    hdr.update(width=w, height=h, stream_size_field=size, bpp=bpp, x=x, y=y,
               image_unknown_0e=unk, stream_offset=img_ofs + 16,
               stream_bytes_in_file=len(data) - (img_ofs + 16))
    return hdr


def palette_rgb4(raw):
    """Palette words 0x0GRB -> [(r, g, b)] with 4-bit components."""
    return [((v >> 4) & 15, (v >> 8) & 15, v & 15) for v in raw]


def unpack_stream(data, pos, out_len):
    """Zero-suppression decoder.  Returns (bytearray(out_len), end position).

    control byte A, MSB first: bit clear -> 8 zero bytes;
    bit set -> mask byte B, MSB first: bit clear -> one zero byte,
                                       bit set   -> one literal byte.
    Stops when out_len bytes are produced or the input runs out (rest = 0).
    """
    out = bytearray(out_len)
    o = 0
    n = len(data)
    try:
        while o < out_len:
            a = data[pos]
            pos += 1
            if a == 0:
                o += 64
                continue
            for abit in (0x80, 0x40, 0x20, 0x10, 8, 4, 2, 1):
                if o >= out_len:
                    break
                if not a & abit:
                    o += 8
                    continue
                b = data[pos]
                pos += 1
                if b == 0xFF:
                    chunk = data[pos:pos + 8]
                    pos += 8
                    out[o:o + 8] = chunk          # may extend; trimmed below
                    o += 8
                    continue
                for bbit in (0x80, 0x40, 0x20, 0x10, 8, 4, 2, 1):
                    if b & bbit:
                        if o < out_len:
                            out[o] = data[pos]
                        pos += 1
                    o += 1
    except IndexError:
        pass
    del out[out_len:]
    if len(out) < out_len:
        out.extend(bytes(out_len - len(out)))
    return out, min(pos, n)


def unfilter_rows(buf, row_len, height, carry=True):
    """Undo the horizontal and vertical XOR in place.

    buf holds `height` stored rows of 1 + row_len bytes.  Returns a list of
    `height` bytes objects (row_len each), still in stored order.
    carry=False resets the accumulator at the start of every chain; that is
    NOT what the original decoder does and is only here for experiments.
    """
    rows = []
    prev = 0
    stride = row_len + 1
    for r in range(height):
        base = r * stride
        step = buf[base]
        row = buf[base + 1:base + stride]
        if step:
            acc = 0
            for start in range(min(step, row_len)):
                if not carry:
                    acc = 0
                for i in range(start, row_len, step):
                    acc ^= row[i]
                    row[i] = acc
        cur = int.from_bytes(row, 'big') ^ prev
        prev = cur
        rows.append(cur.to_bytes(row_len, 'big'))
    return rows


def deinterleave(rows, step):
    """Stored row order -> screen row order (rows 0, step, 2*step, ..., 1, ...)."""
    height = len(rows)
    if step <= 1:
        return rows
    out = [None] * height
    src = 0
    for start in range(min(step, height)):
        for dst in range(start, height, step):
            out[dst] = rows[src]
            src += 1
    return out


def planes_to_pixels(rows, width):
    """Rows of 4 side-by-side bit planes -> bytes of width*len(rows) indexes."""
    bw = (width + 7) >> 3
    s0, s1, s2, s3 = _SPREAD
    out = bytearray()
    for row in rows:
        line = bytearray()
        for i in range(bw):
            v = s0[row[i]] | s1[row[bw + i]] | s2[row[2 * bw + i]] | s3[row[3 * bw + i]]
            line += v.to_bytes(8, 'big')
        out += line[:width]
    return bytes(out)


def decode(data, carry=True):
    """Decode a GPC file.

    Returns (header, palette, width, height, x, y, pixels):
      header   dict from parse_header() plus 'stream_end' (file offset one past
               the last stream byte consumed)
      palette  [(r, g, b)] * 16 with 4-bit components, or None
      pixels   bytes(width * height) of palette indexes
    """
    hdr = parse_header(data)
    if hdr['bpp'] != 4:
        raise GpcError('unsupported bits per pixel: %d' % hdr['bpp'])
    w, h = hdr['width'], hdr['height']
    row_len = 4 * ((w + 7) >> 3)
    buf, end = unpack_stream(data, hdr['stream_offset'], (row_len + 1) * h)
    hdr['stream_end'] = end
    rows = unfilter_rows(buf, row_len, h, carry)
    rows = deinterleave(rows, hdr['interleave'])
    pixels = planes_to_pixels(rows, w)
    pal = palette_rgb4(hdr['palette_raw']) if hdr['palette_raw'] else None
    return hdr, pal, w, h, hdr['x'], hdr['y'], pixels


# --------------------------------------------------------------------------
# Minimal PNG writer (indexed colour), stdlib only.

def _chunk(tag, body):
    return struct.pack('>I', len(body)) + tag + body + \
        struct.pack('>I', zlib.crc32(tag + body) & 0xFFFFFFFF)


def write_png(path, width, height, pixels, palette4, text=None):
    """Write an 8-bit indexed PNG.  palette4: [(r,g,b)] with 4-bit components
    (expanded to 8 bits by nibble replication, 0xF -> 0xFF)."""
    if palette4 is None:
        palette4 = [(i, i, i) for i in range(16)]
    plte = bytes(c * 17 for rgb in palette4 for c in rgb)
    raw = bytearray()
    for r in range(height):
        raw.append(0)
        raw += pixels[r * width:(r + 1) * width]
    png = b'\x89PNG\r\n\x1a\n'
    png += _chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 3, 0, 0, 0))
    png += _chunk(b'PLTE', plte)
    for key, value in (text or {}).items():
        png += _chunk(b'tEXt', key.encode('latin-1') + b'\0' + str(value).encode('latin-1'))
    png += _chunk(b'IDAT', zlib.compress(bytes(raw), 9))
    png += _chunk(b'IEND', b'')
    with open(path, 'wb') as f:
        f.write(png)


def on_screen(width, height, x, y, pixels, sw=640, sh=400, fill=0):
    """Place the picture on an sw x sh canvas of colour `fill` (clipped)."""
    canvas = bytearray([fill]) * (sw * sh)
    for r in range(height):
        yy = y + r
        if not 0 <= yy < sh or x >= sw:
            continue
        n = min(width, sw - x)
        canvas[yy * sw + x:yy * sw + x + n] = pixels[r * width:r * width + n]
    return bytes(canvas)


# --------------------------------------------------------------------------
# CLI

def _label(path):
    """Name used for output files: BASENAME, or DISK_BASENAME when the path
    looks like .../<DISK>/GPC/<NAME>.GPC and --disk-prefix is given."""
    return os.path.splitext(os.path.basename(path))[0]


def cmd_info(paths):
    print('file\tsize\tsize_field_ok\tinterleave\tpal_ofs\timg_ofs\tw\th\tx\ty\tbpp\tsize_field'
          '\tstream_in_file\tstream_used\tunk0e\tpal_trailer\tpalette(0GRB)')
    for p in paths:
        data = open(p, 'rb').read()
        hdr = decode(data)[0]
        pal = ' '.join('%03X' % v for v in hdr['palette_raw']) if hdr['palette_raw'] else '-'
        print('\t'.join(str(v) for v in (
            p, hdr['file_size'], int(hdr['file_size_field'] == hdr['file_size']), hdr['interleave'], '0x%X' % hdr['palette_offset'],
            '0x%X' % hdr['image_offset'], hdr['width'], hdr['height'], hdr['x'], hdr['y'],
            hdr['bpp'], hdr['stream_size_field'], hdr['stream_bytes_in_file'],
            hdr['stream_end'] - hdr['stream_offset'], hdr['image_unknown_0e'],
            hdr['palette_trailer'].hex() or '-', pal)))


def cmd_png(paths, outdir, screen=False, disk_prefix=False):
    os.makedirs(outdir, exist_ok=True)
    rows = []
    for p in paths:
        data = open(p, 'rb').read()
        hdr, pal, w, h, x, y, pix = decode(data)
        name = _label(p)
        if disk_prefix:
            parts = os.path.normpath(os.path.abspath(p)).split(os.sep)
            if len(parts) >= 3:
                name = parts[-3] + '_' + name
        out = os.path.join(outdir, name + '.png')
        text = {'gpc-x': x, 'gpc-y': y, 'gpc-interleave': hdr['interleave'],
                'gpc-palette': 'file' if pal else 'none'}
        if screen:
            write_png(out, 640, 400, on_screen(w, h, x, y, pix), pal, text)
        else:
            write_png(out, w, h, pix, pal, text)
        rows.append((name + '.png', p, x, y, w, h, hdr['interleave'], 1 if pal else 0,
                     ' '.join('%03X' % v for v in hdr['palette_raw']) if pal else '-'))
    with open(os.path.join(outdir, 'index.tsv'), 'w') as f:
        f.write('png\tsource\tx\ty\tw\th\tinterleave\thas_palette\tpalette_0GRB\n')
        for r in rows:
            f.write('\t'.join(str(v) for v in r) + '\n')
    print('wrote %d PNG(s) and index.tsv to %s' % (len(rows), outdir))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description='GPC picture decoder (NOVA, PC-98)')
    sub = ap.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('info', help='print header fields as TSV')
    a.add_argument('files', nargs='+')
    a = sub.add_parser('png', help='convert to indexed PNG + index.tsv')
    a.add_argument('files', nargs='+')
    a.add_argument('-o', '--outdir', required=True)
    a.add_argument('--screen', action='store_true',
                   help='place the picture at its x,y on a 640x400 canvas of colour 0 '
                        '(default: PNG is exactly the picture rectangle)')
    a.add_argument('--disk-prefix', action='store_true',
                   help='prefix output names with the grandparent directory '
                        '(A_NV00.png) so same-named files on several disks do not collide')
    args = ap.parse_args(argv)
    if args.cmd == 'info':
        cmd_info(args.files)
    else:
        cmd_png(args.files, args.outdir, args.screen, args.disk_prefix)
    return 0


if __name__ == '__main__':
    sys.exit(main())
