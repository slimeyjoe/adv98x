#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Adv98V 1.70.54 .MES script parser (stdlib only).

The grammar follows the interpreter (NV.OVL, docs/re/mes-format.md): every operand is read the
way the opcode's handler reads it. parse(data) returns a Script whose nodes cover every byte.

Node = (kind, start, end, ...):
  ('text', s, e, str)                printed characters (Shift-JIS pairs, one-byte hiragana)
  ('nl', s, e)                       A5: new line
  ('ctl', s, e, name)                81 97 nop, 81 90 key wait + clear, 81 6F / 81 70 loop
  ('ascii', s, e, bytes)             21 ... 00: half-width string printed as is
  ('reg', s, e, number, value)       flag assignment / test (value True/False)
  ('var', s, e, index, op, value)    variable assignment / test; op '=', '+', '-'
  ('op', s, e, opcode, args, blocks) args: ints, ('str', bytes), ('letter', chr), None (absent)
                                     blocks: list of Block
  ('end', s, e, 'FFFF' | 'FFFE')
Block = dict(kind, start, end, conds=[reg/var nodes], body=[nodes])
"""
import collections

OPNAMES = {
    0xA6: 'text-frame', 0xA7: 'text-pos', 0xA8: 'text-color', 0xA9: 'text-speed', 0xAA: 'text-clear',
    0xAB: 'wait', 0xAC: 'delay', 0xAD: 'menu', 0xAE: 'menu2', 0xAF: 'seg-call', 0xB0: 'exec-file',
    0xB1: 'mes-jump', 0xB2: 'branch-random', 0xB3: 'branch-cycle', 0xB4: 'branch-var',
    0xB5: 'branch-reg', 0xB6: 'input', 0xB7: 'screen-mode', 0xB8: 'op-B8', 0xB9: 'define-proc',
    0xBA: 'proc', 0xBB: 'repeat', 0xBC: 'if', 0xBD: 'when', 0xBE: 'flag-save', 0xBF: 'flag-load',
    0xC0: 'mes-call', 0xC1: 'image-file-to', 0xC2: 'gfx-string', 0xC3: 'gfx-C3', 0xC4: 'gfx-C4',
    0xC5: 'gfx-C5', 0xC6: 'text-C6', 0xC7: 'save-check', 0xC8: 'load-mem', 0xC9: 'image-file',
    0xCA: 'sys-CA', 0xCB: 'text-CB', 0xCC: 'reg-clear', 0xCD: 'exec-mem', 0xCE: 'set-drive',
    0xCF: 'image-show', 0xD0: 'sound', 0xD1: 'fade', 0xD2: 'name-load', 0xD3: 'menu-step',
    0xD4: 'exit', 0xD5: 'decrypt', 0xD6: 'nop-D6', 0xD7: 'nop-D7', 0xD8: 'nop-D8',
}

# fixed operand counts: every operand is an optional number unless noted in _op()
NUMS = {0xA6: 4, 0xA7: 2, 0xA9: 2, 0xB8: 2, 0xBA: 1, 0xBE: 1, 0xC3: 2, 0xC4: 2, 0xC5: 2,
        0xC6: 5, 0xC7: 1, 0xCA: 1, 0xCB: 1, 0xCE: 2, 0xD3: 2, 0xAF: 0, 0xD2: 0, 0xD4: 0,
        0xD6: 0, 0xD7: 0, 0xD8: 0, 0xAA: 1}


def decode_text(raw):
    """Shift-JIS text -> str. The PC-98 character generator has half-width glyphs under
    two-byte codes (JIS rows 29h-2Bh = Shift-JIS 85xx/86xx), which cp932 lacks; the English
    translation is written with them. They are shown as the half-width characters:
    8540..859E = 21h..7Eh, 859F..85DD = A1h..DFh (katakana), 8640 = blank."""
    out = []
    i = 0
    while i < len(raw):
        b = raw[i]
        if is_lead(b) and i + 1 < len(raw):
            t = raw[i + 1]
            if b == 0x85 and 0x40 <= t <= 0x9E and t != 0x7F:
                out.append(chr(0x21 + t - 0x40 - (t > 0x7F)))
            elif b == 0x85 and 0x9F <= t <= 0xDD:
                out.append(bytes((0xA1 + t - 0x9F,)).decode('cp932'))
            elif b == 0x86 and t == 0x40:
                out.append(' ')
            else:
                out.append(raw[i:i + 2].decode('cp932', 'replace'))
            i += 2
        else:
            out.append(bytes((b,)).decode('cp932', 'replace'))
            i += 1
    return ''.join(out)


class ParseError(Exception):
    pass


def is_lead(b):
    """ed87: first byte of a two-byte character."""
    return 0x81 <= b <= 0x9F or 0xE0 <= b <= 0xFC


def token_len(d, p):
    """ed3b: the length of the token at p as the interpreter's block scanner sees it."""
    b = d[p]
    if b == 0x21:
        q = p + 1
        while d[q]:
            q += 1
        return q + 1 - p
    if 0x23 <= b <= 0x27:
        return 1
    if b == 0x28:
        return 2
    if 0x29 <= b <= 0x2C:
        return 3
    if b < 0x20 or is_lead(b):
        return 2
    return 1


def skip_block(d, p, opener, closer):
    """ec22: from p (inside a block, depth 1) to just after the matching closer."""
    depth = 1
    while True:
        b = d[p]
        if b == opener:
            depth += 1
            p += 1
        elif b == closer:
            depth -= 1
            p += 1
            if depth == 0:
                return p
        else:
            p += token_len(d, p)


class Script:
    def __init__(self, data):
        self.raw = bytes(data)
        self.data = bytearray(data)       # decrypted in place by D5
        self.segments = []                # [dict(start, end, conds, body)]
        self.trailer = None               # (start, bytes) after FF FE
        self.decrypt_from = None
        self.defects = []                 # (offset, text): what the original scripts get wrong
        self.covered = bytearray(len(data))

    # ---- low level ----
    def _mark(self, s, e):
        for i in range(s, e):
            if self.covered[i]:
                raise ParseError('byte %#x parsed twice' % i)
            self.covered[i] = 1

    def _num(self, p):
        """ec54: (value or None, next p)."""
        d = self.data
        b = d[p]
        if 0x23 <= b <= 0x27:
            self._mark(p, p + 1)
            return b - 0x23, p + 1
        if b == 0x28:
            self._mark(p, p + 2)
            return d[p + 1], p + 2
        if 0x29 <= b <= 0x2C:
            self._mark(p, p + 3)
            return (b - 0x29) * 16384 + ((d[p + 1] >> 1) << 8) + ((d[p + 2] & 0x7F) | (d[p + 1] & 1) << 7), p + 3
        return None, p

    def _str(self, p):
        d = self.data
        if d[p] != 0x22:
            raise ParseError('string expected at %#x' % p)
        q = d.index(0x22, p + 1)
        self._mark(p, q + 1)
        return ('str', bytes(d[p + 1:q])), q + 1

    def _regvar(self, p):
        d = self.data
        w = d[p] << 8 | d[p + 1]
        self._mark(p, p + 2)
        if d[p] < 0x10:
            return ('reg', p, p + 2, (w & 0x3FF) - 1, bool(w & 0x400))
        return ('var', p, p + 2, ((w & 0x3F0) >> 4) - 1, {0x0: '=', 0x8: '=', 0xC: '+', 0x4: '-'}[d[p] & 0xC], w & 0xF)

    def _conds(self, p):
        out = []
        while self.data[p] < 0x20:
            out.append(self._regvar(p))
            p += 2
        return out, p

    # ---- statements ----
    def _run(self, p, out):
        """de2f: statements until FF FF / FF FE or a byte A0..A4; returns (p after it, terminator)."""
        d = self.data
        text_start, text = None, []

        def flush(at):
            nonlocal text_start, text
            if text:
                out.append(('text', text_start, at, decode_text(b''.join(text))))
            text_start, text = None, []
        while True:
            b = d[p]
            if b == 0xFF and d[p + 1] in (0xFF, 0xFE):
                flush(p)
                self._mark(p, p + 2)
                out.append(('end', p, p + 2, 'FF%02X' % d[p + 1]))
                return p + 2, d[p + 1] | 0xFF00
            if 0xA0 <= b <= 0xA4:
                flush(p)
                self._mark(p, p + 1)
                return p + 1, b
            if is_lead(b):
                w = b << 8 | d[p + 1]
                ctl = {0x8197: 'nop', 0x8190: 'key-clear', 0x816F: 'loop-begin', 0x8170: 'loop-end'}.get(w)
                self._mark(p, p + 2)
                if ctl:
                    flush(p)
                    out.append(('ctl', p, p + 2, ctl))
                else:
                    if text_start is None:
                        text_start = p
                    text.append(bytes(d[p:p + 2]))
                p += 2
            elif b == 0x21:
                flush(p)
                q = d.index(0, p)
                self._mark(p, q + 1)
                out.append(('ascii', p, q + 1, bytes(d[p + 1:q])))
                p = q + 1
            elif b < 0x20:
                flush(p)
                out.append(self._regvar(p))
                p += 2
            elif b == 0xA5:
                flush(p)
                self._mark(p, p + 1)
                out.append(('nl', p, p + 1))
                p += 1
            elif 0x2D <= b <= 0x7F:
                self._mark(p, p + 1)
                if text_start is None:
                    text_start = p
                text.append(bytes((0x82, b + 0x72)))
                p += 1
            elif 0xA6 <= b <= 0xD8:
                flush(p)
                p = self._op(p, out)
            else:
                raise ParseError('byte %02X at %#x is not a statement' % (b, p))

    def _cut(self, body, p, what):
        """A block that runs into the end of its segment: give the end marker back."""
        self.defects.append((p - 2, '%s block not closed before the segment end' % what))
        body.pop()
        self.covered[p - 2] = self.covered[p - 1] = 0
        return p - 2

    def _alts(self, p, kind):
        """Alternatives separated by A4 up to A3 (ecdf / e335); p is after the opening A2."""
        blocks = []
        while True:
            conds, q = self._conds(p)
            body = []
            q2, term = self._run(q, body)
            blocks.append(dict(kind=kind, start=p, end=q2, conds=conds, body=body))
            p = q2
            if term == 0xA3:
                return blocks, p
            if term >= 0xFF00:
                blocks[-1]['end'] = p = self._cut(body, p, kind)
                return blocks, p
            if term != 0xA4:
                raise ParseError('%s: terminator %#x at %#x' % (kind, term, p))

    def _open(self, p, what):
        """The handlers skip the block opener with a bare `inc si`."""
        if self.data[p] != 0xA2:
            raise ParseError('%s: A2 expected at %#x, found %02X' % (what, p, self.data[p]))
        self._mark(p, p + 1)
        return p + 1

    def _op(self, p, out):
        d = self.data
        s, op = p, d[p]
        self._mark(p, p + 1)
        p += 1
        args, blocks = [], []

        def nums(n, stop_on_absent=False):
            nonlocal p
            for _ in range(n):
                v, p = self._num(p)
                args.append(v)
                if v is None and stop_on_absent:
                    break

        def string():
            nonlocal p
            a, p = self._str(p)
            args.append(a)

        if op in NUMS:
            nums(NUMS[op])
        elif op == 0xA8:                      # colour [, d010 [, clear attribute]]
            nums(1)
            nums(2, True)
        elif op in (0xAB, 0xAC):              # wait / delay: second operand only after a first
            nums(2, True)
        elif op == 0xAD:                      # menu: (x y)* prefix-statements A2 items A3
            while True:
                v, p = self._num(p)
                if v is None:
                    break
                w, p = self._num(p)
                args.append((v, w))
            pre = []
            p, term = self._run(p, pre)
            if term != 0xA2:
                raise ParseError('menu: A2 expected, got %#x at %#x' % (term, p))
            blocks.append(dict(kind='menu-head', start=s, end=p, conds=[], body=pre))
            b2, p = self._alts(p, 'item')
            blocks += b2
        elif op == 0xAE:                      # menu2: head A2 (verb A0 nouns A1)* A3
            while True:
                v, p = self._num(p)
                if v is None:
                    break
                w, p = self._num(p)
                args.append((v, w))
            pre = []
            p, term = self._run(p, pre)
            if term != 0xA2:
                raise ParseError('menu2: A2 expected, got %#x at %#x' % (term, p))
            blocks.append(dict(kind='menu-head', start=s, end=p, conds=[], body=pre))
            while True:
                v0 = p
                conds, p = self._conds(p)
                body = []
                p, term = self._run(p, body)
                if term != 0xA0:
                    raise ParseError('menu2: A0 expected, got %#x at %#x' % (term, p))
                blocks.append(dict(kind='verb', start=v0, end=p, conds=conds, body=body))
                while True:
                    n0 = p
                    conds, p = self._conds(p)
                    body = []
                    p, term = self._run(p, body)
                    blocks.append(dict(kind='noun', start=n0, end=p, conds=conds, body=body))
                    if term == 0xA1:
                        break
                    if term != 0xA4:
                        raise ParseError('menu2 nouns: terminator %#x at %#x' % (term, p))
                if d[p] == 0xA3:
                    self._mark(p, p + 1)
                    p += 1
                    break
        elif op == 0xB0:                      # exec-file "name" [offset [entry]]
            string()
            nums(2, True)
        elif op in (0xB1, 0xC0, 0xC9):
            string()
        elif op in (0xB2, 0xB3):
            p = self._open(p, OPNAMES[op])
            blocks, p = self._alts(p, 'alt')
        elif op == 0xB4:                      # branch-var LETTER A2 ...
            args.append(('letter', chr(d[p])))
            self._mark(p, p + 1)
            p = self._open(p + 1, 'branch-var')
            blocks, p = self._alts(p, 'alt')
        elif op == 0xB5:
            nums(1)
            p = self._open(p, 'branch-reg')
            blocks, p = self._alts(p, 'alt')
        elif op == 0xB6:                      # input: "file" | LETTER n
            if d[p] == 0x22:
                string()
            else:
                args.append(('letter', chr((d[p] & 0x1F) + 0x40)))
                self._mark(p, p + 1)
                p += 1
                nums(1)
        elif op == 0xB7:                      # screen-mode p1 [p2 p3]
            nums(1)
            v, p = self._num(p)
            args.append(v)
            if v is not None:
                nums(1)
        elif op in (0xB9, 0xBB):              # define-proc n A2 body A3 / repeat n A2 body A3
            nums(1)
            p = self._open(p, OPNAMES[op])
            body = []
            b0 = p
            p, term = self._run(p, body)
            if term >= 0xFF00:
                p = self._cut(body, p, OPNAMES[op])
            elif term != 0xA3:
                raise ParseError('%s: A3 expected, got %#x at %#x' % (OPNAMES[op], term, p))
            blocks.append(dict(kind='body', start=b0, end=p, conds=[], body=body))
        elif op in (0xBC, 0xBD):
            p = self._open(p, OPNAMES[op])
            blocks, p = self._alts(p, 'alt')
        elif op == 0xBF:                      # flag-load n [mode]
            nums(2)
        elif op in (0xC1, 0xC2):              # n "string"
            nums(1)
            string()
        elif op == 0xC8:                      # load-mem "file" [offset]
            string()
            nums(1)
        elif op == 0xCC:                      # reg-clear [first [last]]
            nums(2, True)
        elif op == 0xCD:                      # exec-mem offset (string | number)*
            nums(1)
            while True:
                if d[p] == 0x22:
                    string()
                    continue
                v, p = self._num(p)
                if v is None:
                    break
                args.append(v)
        elif op == 0xCF:                      # image-show p1 [mode [x y]]
            nums(1)
            v, p = self._num(p)
            args.append(v)
            if v is not None:
                v, p = self._num(p)
                args.append(v)
                if v is not None:
                    nums(1)
        elif op == 0xD0:                      # sound: se (name|n) | "file" | n [m]
            if (d[p] | 0x20) == 0x73 and (d[p + 1] | 0x20) == 0x65:
                self._mark(p, p + 2)
                p += 2
                args.append(('letter', 'se'))
                while d[p] == 0x20:
                    self._mark(p, p + 1)
                    p += 1
                if d[p] == 0x22:
                    string()
                else:
                    nums(1)
            elif d[p] == 0x22:
                string()
            else:
                nums(1)
                if args[0] in (1, 2, 3):
                    nums(1)
        elif op == 0xD1:                      # fade p1 [p2 [p3]]
            nums(1)
            if args[0] is not None:
                nums(1)
                if args[0] == 2 and args[1] is not None:
                    nums(1)
        elif op == 0xD5:                      # decrypt key: the rest of the buffer, in place
            nums(1)
            if args[0]:
                self.decrypt_from = p
                for i in range(p, len(d)):
                    d[i] = ((d[i] >> 4 | d[i] << 4) & 0xFF) ^ (args[0] & 0xFF)
        else:
            raise ParseError('opcode %02X at %#x' % (op, s))
        out.append(('op', s, p, op, args, blocks))
        return p

    def parse(self):
        p = 0
        first = True
        while True:
            s = p
            if first:
                conds = []
            else:
                conds, p = self._conds(p)
            body = []
            while True:
                p, term = self._run(p, body)
                if term in (0xFFFF, 0xFFFE):
                    break
                # a block byte outside any block ends the run in the interpreter
                self.defects.append((p - 1, 'stray %02X outside a block' % term))
                body.append(('stray', p - 1, p, term))
            self.segments.append(dict(start=s, end=p, conds=conds, body=body))
            first = False
            if term == 0xFFFE:
                break
        if p < len(self.data):
            self.trailer = (p, bytes(self.data[p:]))
            self._mark(p, len(self.data))
        return self


def parse(data):
    return Script(data).parse()


def walk(nodes):
    """Every node of a body, depth first, blocks included."""
    for n in nodes:
        yield n
        if n[0] == 'op':
            for b in n[5]:
                yield from b['conds']
                yield from walk(b['body'])


def var_name(i):
    return chr(0x41 + i) if i < 26 else 'v%d' % i


def stats(scripts):
    c = collections.Counter()
    for sc in scripts:
        for seg in sc.segments:
            for n in walk(seg['body']):
                if n[0] == 'op':
                    c[n[3]] += 1
    return c
