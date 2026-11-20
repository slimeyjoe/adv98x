# SPDX-License-Identifier: GPL-3.0-or-later
"""casekit - what a game's tests/cases.py builds its cases from.

The engine's tests take what they try on a game from that game's tests/cases.py
(tools/gamedir.py cases(), which puts this directory on the path first). This module is the
vocabulary those cases are written in:

  * the PC-98 keys of a scenario's input, as (scan code, character); ('click', x, y) a click;
    RET_TO_CLICK Return at every key wait up to the next click-map wait; RESET the reset button
    (the engine only: the original is started anew with the keys after it, and the engine must
    end in the same state);
  * the script assembler of the synthetic scenarios: op(code, *args) is a statement of the
    script format (docs/re/mes-format.md), its arguments numbers or quoted strings; END waits
    for a key (the run stops there) and ends the script.
"""

RET, DOWN, RIGHT = (0x1C, 0x0D), (0x3D, 0x00), (0x3C, 0x00)
RET_TO_CLICK = ('ret*',)
RESET = ('reset',)


def key(scan, char):
    return (scan, char)


def click(x, y):
    return ('click', x, y)


def num(n):
    if n < 5:
        return bytes([0x23 + n])
    if n < 256:
        return bytes([0x28, n])
    return bytes([0x29 + (n >> 14), (n >> 7) & 0x7F, n & 0x7F])


def qs(text):
    return b'"' + text.encode('ascii') + b'"'


def op(code, *args):
    out = bytes([code])
    for a in args:
        out += qs(a) if isinstance(a, str) else num(a)
    return out


END = b'\xab\xff\xff\xff\xfe'
