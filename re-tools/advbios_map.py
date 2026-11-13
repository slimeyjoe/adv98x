#!/usr/bin/env python3
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
  4. writes  SEG:OFF<TAB>name<TAB>comment  for NOVA.  Hand-made names from
     the NOVA analysis (--own, same TSV format) take precedence and are
     merged; VB-derived rows are marked "VB" in the comment.

Usage:
  advbios_map.py --asm ADVBIOS.DEC2.asm --dn ADVBIOS.DEC2.OVL --nova NV.OV1
                 [--own own.tsv] [--all] --out advbios-names.tsv

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
    bss_shift = len(init_nv) - len(init_dn)

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

    if a.own:
        for key, (nm, cm) in load_names(a.own).items():
            old = rows.get(key)
            if old and old[0] != nm and not old[0].startswith('dn_'):
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
    print('data operand shifts:', dshift.most_common(8), file=sys.stderr)
    print('rows written: %d' % len(rows), file=sys.stderr)


if __name__ == '__main__':
    main()
