#!/usr/bin/env python3
"""Script catalogue of an Adv98V game: transition graph, per-script summary, reachability and
asset checks (research tool; parser: source/tools/mes.py; findings: docs/re/script-catalog.md,
docs/re/disks.md).

  python3 -I re-tools/mesgraph.py [export] [--mes DIR] [--ini FILE] [--out DIR] [--inventory TSV]
                                           [--images DIR]
  python3 -I re-tools/mesgraph.py catalog resources/scripts.tsv     # refresh size / successors

Defaults: --mes resources/original/pc98/A/MES, --ini resources/original/pc98/A/NV.INI,
--out resources/derived/scripts, --inventory resources/inventory.tsv (release pc98),
--images resources/derived/images/gpc (decoded pictures + index.tsv; used only to compare the
files of a name that differs between disks).

export writes into --out (git-ignored; the tables quote menu texts):
  transitions.tsv   every mes-jump / flag-load with the conditions on the way to it
  transitions.dot   the same graph for Graphviz (flag conditions only, no game text)
  summary.tsv       one line per script: size, segments, text, pictures, music, flags, menus ...
  flagrefs.tsv      every flag / variable assignment and test with its context
  pictures.tsv      every image-file reference resolved through the set-drive state
  skeleton/*.txt    control-flow skeleton of each script (listing without text and display code)
  reach.txt         the report: reachability from the start script, missing targets, dead code,
                    unreachable segments, picture / music / file checks against the inventory

Drive model (docs/re/disks.md): `set-drive slot value` says which floppy is in a drive unit:
slot 0 = A:, slot 1 = B:; value 0..3 = disk A..D. A name without a drive letter is on unit 0.
The state is followed in lexical order inside a script and across mes-jump edges (fixpoint).
"""
import collections
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'source', 'tools'))
sys.path.insert(0, HERE)
import mes      # noqa: E402
import mesdis   # noqa: E402

MENU, MENU2, SEGCALL, JUMP, IF, WHEN = 0xAD, 0xAE, 0xAF, 0xB1, 0xBC, 0xBD
SAVE, LOAD, SAVECHK, LOADMEM, IMAGE, EXECMEM, SETDRIVE, SOUND = 0xBE, 0xBF, 0xC7, 0xC8, 0xC9, 0xCD, 0xCE, 0xD0
INPUT, DEFPROC, NAMELOAD, EXIT, EXECFILE, MESCALL = 0xB6, 0xB9, 0xD2, 0xD4, 0xB0, 0xC0
DISKS = 'ABCD'


def base(name):
    """\\MES\\D21.MES -> D21"""
    n = name.replace('/', '\\').split('\\')[-1].upper()
    return n[:-4] if n.endswith('.MES') else n


def sarg(a):
    return a[1].decode('cp932', 'replace') if isinstance(a, tuple) and a[0] == 'str' else None


def conds(cs):
    return ' '.join(mesdis.fmt_cond(c) for c in cs)


def text_of(nodes, limit=40):
    """The printed text of a body (menu item label), blanks trimmed."""
    t = ''.join(n[3] for n in nodes if n[0] == 'text')
    return t.replace('　', ' ').strip()[:limit]


class Info:
    """Everything the catalogue needs from one parsed script."""

    def __init__(self, name, path):
        self.name = name
        self.path = path
        self.sc = mes.parse(open(path, 'rb').read())
        self.size = len(self.sc.raw)
        self.jumps = []      # dict(off, target, kind, live, cond, text, drive)
        self.images = []     # dict(off, ref, drive, live)
        self.flagrefs = []   # (off, 'R12'|'L', kind, detail, context)
        self.menus = []      # dict(off, op, items=[(conds, text)])
        self.saves, self.loads = [], []
        self.music, self.effects = [], []
        self.sound = collections.Counter()
        self.files = []      # (off, op, name) other file operands
        self.plugins = collections.Counter()
        self.notes = []      # oddities
        self.text_runs = self.text_chars = self.waits = 0
        self.has_segcall = False
        self.segcall_menu = None
        self.exit_drive = {}
        self._prescan()

    def _prescan(self):
        segs = self.sc.segments
        last_menu = None
        menus_at_call = []
        for n in mes.walk(segs[0]['body']):
            if n[0] == 'op' and n[3] in (MENU, MENU2):
                last_menu = n
            elif n[0] == 'op' and n[3] == SEGCALL:
                menus_at_call.append(last_menu)
        for seg in segs[1:]:
            for n in mes.walk(seg['body']):
                if n[0] == 'op' and n[3] == SEGCALL:
                    menus_at_call.append(None)
        self.has_segcall = bool(menus_at_call)
        if menus_at_call and all(m is menus_at_call[0] for m in menus_at_call):
            self.segcall_menu = menus_at_call[0]
        self.nonempty = [i for i, s in enumerate(segs) if any(n[0] != 'end' for n in s['body'])]

    # ---- menu choice lookup ----
    @staticmethod
    def choice(menu, cs):
        """What a condition list says about the choice made in `menu` (S / V / N tests)."""
        if menu is None:
            return ''
        out = []
        blocks = menu[5][1:]
        for c in cs:
            if c[0] != 'var' or c[4] != '=':
                continue
            v = mes.var_name(c[3])
            if menu[3] == MENU and v == 'S' and c[5] < len(blocks):
                out.append('item %d "%s"' % (c[5], text_of(blocks[c[5]]['body'])))
            elif menu[3] == MENU2 and v == 'V':
                verbs = [b for b in blocks if b['kind'] == 'verb']
                if c[5] < len(verbs):
                    out.append('verb %d "%s"' % (c[5], text_of(verbs[c[5]]['body'])))
            elif menu[3] == MENU2 and v == 'N':
                out.append('noun %d' % c[5])
        return ', '.join(out)

    # ---- the walk ----
    def analyse(self, entry):
        """Walk the script with the drive state `entry` ({slot: frozenset(values)})."""
        self.jumps, self.images, self.flagrefs, self.menus = [], [], [], []
        self.saves, self.loads, self.music, self.effects, self.files = [], [], [], [], []
        self.sound, self.plugins = collections.Counter(), collections.Counter()
        self.notes = []
        self.text_runs = self.text_chars = self.waits = 0
        self.exit_drive = {}
        segs = self.sc.segments
        state = dict(entry)
        at_call = None
        self._last_menu = None
        for i, seg in enumerate(segs):
            if i == 0:
                live = True
                ctx, tctx = [], []
            else:
                if at_call is not None:
                    state = dict(at_call)
                live = self.has_segcall
                c = conds(seg['conds'])
                ctx = ['seg%d[%s]' % (i, c)]
                ch = self.choice(self.segcall_menu, seg['conds'])
                tctx = [ch] if ch else []
                for c in seg['conds']:
                    self._ref(seg['start'], c, 'test', 'segment %d' % i)
                if i in self.nonempty and not self.has_segcall:
                    self.notes.append('segment %d at %04X is never called (the script has no seg-call)' % (i, seg['start']))
                for j in range(1, i):
                    a = {mesdis.fmt_cond(x) for x in segs[j]['conds']}
                    b = {mesdis.fmt_cond(x) for x in seg['conds']}
                    if i in self.nonempty and j in self.nonempty and a <= b:
                        self.notes.append('segment %d [%s] is shadowed by segment %d [%s]' % (i, conds(seg['conds']), j, conds(segs[j]['conds'])))
                        live = False
                        break
            st = self._body(seg['body'], state, ctx, tctx, live)
            if i == 0:
                at_call = self._at_call if self._at_call is not None else st
                self._at_call = None
            state = st
        extra = [i for i in range(1, len(segs) - 1) if i not in self.nonempty]
        if extra:
            self.notes.append('empty segment%s %s before the end marker' % ('s' if len(extra) > 1 else '', ', '.join(map(str, extra))))
        for off, textd in self.sc.defects:
            self.notes.append('parser defect at %04X: %s' % (off, textd))

    _at_call = None

    def _ref(self, off, n, kind, where):
        if n[0] == 'reg':
            self.flagrefs.append((off, 'R%d' % n[3], kind, str(int(n[4])), where))
        else:
            self.flagrefs.append((off, mes.var_name(n[3]), kind, mesdis.fmt_cond(n, kind == 'test'), where))

    def _body(self, nodes, state, ctx, tctx, live):
        dead = False          # after an unconditional transfer in this body
        for n in nodes:
            k = n[0]
            here = live and not dead
            where = ' & '.join(ctx)
            if k == 'text':
                self.text_runs += 1
                self.text_chars += len(n[3])
            elif k == 'ascii':
                self.text_runs += 1
                self.text_chars += len(n[3])
            elif k in ('reg', 'var'):
                self._ref(n[1], n, 'set', where)
            elif k == 'ctl':
                if n[3] == 'loop-end' and not dead:
                    dead = 'loop-end at %04X' % n[1]
                continue
            if k != 'op':
                continue
            op, args, blocks = n[3], n[4], n[5]
            if op == 0xAB:
                self.waits += 1
            elif op == SETDRIVE:
                if args[0] is not None and args[1] is not None:
                    state = dict(state)
                    state[args[0] & 1] = frozenset([args[1]])
            elif op == IMAGE:
                self.images.append(dict(off=n[1], ref=sarg(args[0]), drive=dict(state), live=here))
            elif op == SOUND:
                if args and isinstance(args[0], tuple) and args[0][0] == 'letter':
                    self.effects.append((n[1], sarg(args[1]) or str(args[1])))
                elif args and sarg(args[0]) is not None:
                    self.music.append((n[1], sarg(args[0])))
                else:
                    self.sound[{0: 'stop', 1: 'play', 2: 'fade', 3: 'cmd3'}.get(args[0], 'stop')] += 1
            elif op == JUMP:
                tgt = sarg(args[0])
                self.jumps.append(dict(off=n[1], target=base(tgt), raw=tgt, kind='jump', live=here,
                                       dead=dead or ('' if live else 'segment never run'),
                                       cond=where, text=' / '.join(tctx), drive=dict(state)))
                if here:
                    for s, v in state.items():
                        self.exit_drive.setdefault(base(tgt), {}).setdefault(s, set()).update(v)
                if not dead:
                    dead = 'mes-jump at %04X' % n[1]
            elif op == SAVE:
                self.saves.append((n[1], args[0], where))
            elif op == LOAD:
                self.loads.append((n[1], args[0], args[1], where, ' / '.join(tctx)))
                if not args[1] and not dead:
                    dead = 'flag-load at %04X' % n[1]
            elif op == EXIT:
                if not dead:
                    dead = 'exit at %04X' % n[1]
            elif op == SEGCALL:
                self._at_call = dict(state)
            elif op == LOADMEM:
                self.files.append((n[1], 'load-mem', sarg(args[0])))
                self.plugins[sarg(args[0]).upper()] += 0
            elif op == EXECMEM:
                self.plugins['@%s' % args[0]] += 1
            elif op == INPUT and sarg(args[0]) is not None:
                self.files.append((n[1], 'input', sarg(args[0])))
            elif op in (EXECFILE, MESCALL):
                self.files.append((n[1], mes.OPNAMES[op], sarg(args[0])))
            if op in (MENU, MENU2):
                self._last_menu = n
                items = [(conds(b['conds']), text_of(b['body']), b['kind']) for b in blocks[1:]]
                self.menus.append(dict(off=n[1], op=op, items=items))
                state = self._body(blocks[0]['body'], state, ctx, tctx, here)
                for i, b in enumerate(blocks[1:]):
                    for c in b['conds']:
                        self._ref(b['start'], c, 'test', (where + ' & ' if where else '') + 'menu@%04X %s' % (n[1], b['kind']))
                    state = self._body(b['body'], state, ctx + ['menu@%04X %s%d' % (n[1], b['kind'], i)], tctx, here)
            elif op in (IF, WHEN):
                prev = []
                for i, b in enumerate(blocks):
                    c = conds(b['conds'])
                    for x in b['conds']:
                        self._ref(b['start'], x, 'test', where)
                    label = 'if[%s]' % c if c else 'if[else]'
                    if op == IF and prev:
                        label += ' after not[%s]' % '] not['.join(prev)
                    ch = self.choice(self._last_menu, b['conds'])
                    state = self._body(b['body'], state, ctx + [label], tctx + ([ch] if ch else []), here)
                    prev.append(c)
            elif blocks:
                for b in blocks:
                    for x in b['conds']:
                        self._ref(b['start'], x, 'test', where)
                    sub = ctx + (['proc%s' % args[0]] if op == DEFPROC else [mes.OPNAMES[op]])
                    state = self._body(b['body'], state, sub, tctx, here)
        # report code after an unconditional transfer
        seen = False
        for n in nodes:
            if seen and n[0] != 'end':
                what = mes.OPNAMES[n[3]] + (' "%s"' % sarg(n[4][0]) if n[0] == 'op' and n[4] and sarg(n[4][0]) else '') if n[0] == 'op' else n[0]
                self.notes.append('dead code at %04X (%s) after %s' % (n[1], what, seen))
                break
            if n[0] == 'op' and n[3] == JUMP:
                seen = 'the mes-jump at %04X' % n[1]
            elif n[0] == 'op' and n[3] == LOAD and not n[4][1]:
                seen = 'the flag-load at %04X' % n[1]
            elif n[0] == 'ctl' and n[3] == 'loop-end':
                seen = 'the loop-end at %04X' % n[1]
        return state


# ---------------------------------------------------------------------------------------------

def load_inventory(path, release='pc98'):
    """{disk: {NAME: (md5, size)}} for pictures, plus {PATH: size} for every file of disk A."""
    pics = collections.defaultdict(dict)
    files = {}
    if not os.path.exists(path):
        return pics, files
    with open(path, encoding='utf-8') as fh:
        head = fh.readline().rstrip('\n').split('\t')
        for line in fh:
            r = dict(zip(head, line.rstrip('\n').split('\t')))
            if r['release'] != release:
                continue
            parts = r['path'].upper().split('/')
            files['/'.join(parts)] = int(r['size'])
            if len(parts) == 3 and parts[1] == 'GPC':
                pics[parts[0]][parts[2]] = (r['md5'], int(r['size']))
    return pics, files


def read_png(path):
    """Palettised PNG (as written by the picture exporter) -> (w, h, rows of indices, palette bytes)."""
    import struct
    import zlib
    d = open(path, 'rb').read()
    p, idat, plte = 8, b'', b''
    while p < len(d):
        n, typ = struct.unpack('>I4s', d[p:p + 8])
        body = d[p + 8:p + 8 + n]
        if typ == b'IHDR':
            w, h, depth, ctype = struct.unpack('>IIBB', body[:10])
        elif typ == b'PLTE':
            plte = body
        elif typ == b'IDAT':
            idat += body
        p += 12 + n
    if ctype != 3:
        raise ValueError('not a palettised PNG')
    raw = zlib.decompress(idat)
    stride = (w * depth + 7) // 8
    rows, prev = [], bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]
        cur = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = cur[i - 1] if i else 0
            b, c = prev[i], (prev[i - 1] if i else 0)
            if f == 1:
                cur[i] = (cur[i] + a) & 255
            elif f == 2:
                cur[i] = (cur[i] + b) & 255
            elif f == 3:
                cur[i] = (cur[i] + (a + b) // 2) & 255
            elif f == 4:
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                cur[i] = (cur[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        if depth == 8:
            rows.append(bytes(cur))
        else:
            mask = (1 << depth) - 1
            rows.append(bytes((cur[(x * depth) // 8] >> (8 - depth - (x * depth) % 8)) & mask for x in range(w)))
        prev = cur
    return w, h, rows, plte


def on_screen(imgdir, index, disk, name):
    """The picture as it lands on the 640x400 screen: (list of 400 rows of indices, palette)."""
    key = '%s_%s.png' % (disk, name[:-4])
    x, y = index[key]
    w, h, rows, plte = read_png(os.path.join(imgdir, key))
    scr = [bytearray(640) for _ in range(400)]
    for r in range(h):
        scr[y + r][x:x + w] = rows[r]
    return scr, plte


def compare_variants(imgdir, pics, name):
    """Do the differing files of one name show the same picture? -> text for the report."""
    idx = {}
    try:
        with open(os.path.join(imgdir, 'index.tsv'), encoding='utf-8') as fh:
            fh.readline()
            for line in fh:
                r = line.split('\t')
                idx[r[0]] = (int(r[2]), int(r[3]))
        disks = [d for d in DISKS if name in pics.get(d, {})]
        ref, refpal = on_screen(imgdir, idx, disks[0], name)
        out = []
        for d in disks[1:]:
            scr, pal = on_screen(imgdir, idx, d, name)
            n = sum(1 for y in range(400) for x in range(640) if scr[y][x] != ref[y][x])
            out.append('%s vs %s: %d of 256000 screen pixels differ (palette indices), palette %s'
                       % (disks[0], d, n, 'identical' if pal[:48] == refpal[:48] else 'DIFFERENT'))
        return '; '.join(out)
    except (OSError, KeyError, ValueError) as e:
        return 'not compared (%s)' % e


def resolve(ref, drive):
    """image-file operand + drive state -> (unit, [disk letters]) under the drive model."""
    r = ref.upper()
    unit = 0
    if len(r) > 1 and r[1] == ':':
        unit = ord(r[0]) - 65
        r = r[2:]
    vals = drive.get(unit)
    disks = sorted(DISKS[v] if v < 4 else '?' for v in vals) if vals else []
    return unit, disks, r.replace('\\', '/').lstrip('/')


def build(mesdir, ini):
    infos = {}
    for f in sorted(os.listdir(mesdir)):
        if f.upper().endswith('.MES'):
            infos[base(f)] = Info(base(f), os.path.join(mesdir, f))
    start = None
    if ini and os.path.exists(ini):
        start = os.path.basename(ini).upper()
        infos[start] = Info(start, ini)
    # drive-state fixpoint over the jump graph
    entry = {n: {} for n in infos}
    for _ in range(20):
        changed = False
        for n, inf in infos.items():
            inf.analyse({s: frozenset(v) for s, v in entry[n].items()})
        for n, inf in infos.items():
            for tgt, st in inf.exit_drive.items():
                if tgt not in infos:
                    continue
                for s, v in st.items():
                    cur = entry[tgt].setdefault(s, set())
                    if not v <= cur:
                        cur |= v
                        changed = True
        if not changed:
            break
    return infos, start, entry


def compact(nums):
    """[1,2,3,7] -> '1-3 7'"""
    out, nums = [], sorted(set(nums))
    i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if i == j else '%d-%d' % (nums[i], nums[j]))
        i = j + 1
    return ' '.join(out)


def picname(ref):
    r = ref.upper()
    pre = r[:2] if len(r) > 1 and r[1] == ':' else ''
    n = r.split('\\')[-1]
    return pre + (n[:-4] if n.endswith('.GPC') else n)


def edges(infos):
    """Live transitions: {src: [target...]} including the save/load edges."""
    savers = sorted({n for n, inf in infos.items() for s in inf.saves if s[1] in (0, 1, 2)})
    e = collections.defaultdict(list)
    for n, inf in infos.items():
        for j in inf.jumps:
            if j['live'] and j['target'] not in e[n]:
                e[n].append(j['target'])
    return e, savers


def export(infos, start, entry, out, pics, files, imgdir=None):
    os.makedirs(os.path.join(out, 'skeleton'), exist_ok=True)

    def tsv(fn, head, rows):
        with open(os.path.join(out, fn), 'w', encoding='utf-8') as fh:
            fh.write('\t'.join(head) + '\n')
            for r in rows:
                fh.write('\t'.join(str(x) for x in r) + '\n')

    e, savers = edges(infos)
    # --- transitions ---
    rows = []
    for n, inf in infos.items():
        for j in inf.jumps:
            rows.append((n, '%04X' % j['off'], j['target'], 'jump',
                         'live' if j['live'] else 'dead', 'yes' if j['target'] in infos else 'MISSING',
                         j['cond'], j['text'], j['dead'] if not j['live'] else ''))
        for off, slot, mode, where, textc in inf.loads:
            for s in (savers if not mode else []):
                rows.append((n, '%04X' % off, s, 'load FLAG%s' % slot, 'live', 'yes', where, textc, ''))
    tsv('transitions.tsv', ('script', 'offset', 'target', 'kind', 'live', 'exists', 'condition', 'choice', 'why_dead'), rows)
    with open(os.path.join(out, 'transitions.dot'), 'w', encoding='utf-8') as fh:
        fh.write('digraph scripts {\n  rankdir=LR; node [shape=box, fontsize=10]; edge [fontsize=8];\n')
        seen = set()
        for r in rows:
            key = (r[0], r[2], r[6], r[4], r[3])
            if key in seen:
                continue
            seen.add(key)
            attr = ['label="%s"' % r[6].replace('"', "'")]
            if r[4] == 'dead':
                attr.append('style=dotted')
            if r[3] != 'jump':
                attr.append('style=dashed')
            if r[5] == 'MISSING':
                attr.append('color=red')
            fh.write('  "%s" -> "%s" [%s];\n' % (r[0], r[2], ', '.join(attr)))
        fh.write('}\n')

    # --- pictures ---
    prow, used, unresolved, ambiguous = [], collections.Counter(), [], []
    for n, inf in infos.items():
        for im in inf.images:
            unit, disks, rel = resolve(im['ref'], im['drive'])
            name = rel.split('/')[-1]
            found = [d for d in disks if name in pics.get(d, {})]
            everywhere = ''.join(d for d in DISKS if name in pics.get(d, {}))
            md5s = {pics[d][name][0] for d in DISKS if name in pics.get(d, {})}
            status = 'ok' if len(disks) == 1 and found else ('AMBIGUOUS' if len(disks) > 1 else 'NOT FOUND')
            if len(disks) > 1 and len(found) == len(disks) and len({pics[d][name][0] for d in found}) == 1:
                status = 'ok (same file on %s)' % ''.join(found)
            if not disks:
                status = 'DRIVE UNKNOWN'
            if status.startswith('ok'):
                for d in found:
                    used[(d, name)] += 1
            elif im['live']:
                (ambiguous if status == 'AMBIGUOUS' else unresolved).append((n, im, status))
            prow.append((n, '%04X' % im['off'], im['ref'], ' '.join('%d=%s' % (s, ','.join(map(str, sorted(v)))) for s, v in sorted(im['drive'].items())),
                         ''.join(disks), ','.join(pics[d][name][0][:8] for d in found), everywhere,
                         len(md5s), status, 'live' if im['live'] else 'dead'))
    tsv('pictures.tsv', ('script', 'offset', 'reference', 'drive_state', 'disk', 'md5', 'name_on_disks', 'variants', 'status', 'live'), prow)

    # --- flag references ---
    tsv('flagrefs.tsv', ('name', 'script', 'offset', 'kind', 'value', 'context'),
        [(r[1], n, '%04X' % r[0], r[2], r[3], r[4]) for n, inf in infos.items() for r in inf.flagrefs])

    # --- summary ---
    srow = []
    for n, inf in infos.items():
        fs = [int(r[1][1:]) for r in inf.flagrefs if r[1][0] == 'R' and r[1][1:].isdigit() and r[2] == 'set']
        ft = [int(r[1][1:]) for r in inf.flagrefs if r[1][0] == 'R' and r[1][1:].isdigit() and r[2] == 'test']
        vs = sorted({r[1] for r in inf.flagrefs if not r[1][1:].isdigit() and r[2] == 'set'})
        vt = sorted({r[1] for r in inf.flagrefs if not r[1][1:].isdigit() and r[2] == 'test'})
        pl = sorted(k for k in inf.plugins if not k.startswith('@'))
        ex = sum(v for k, v in inf.plugins.items() if k.startswith('@'))
        srow.append((n, inf.size, '%d/%d' % (len(inf.nonempty), len(inf.sc.segments)), inf.text_runs, inf.text_chars, inf.waits,
                     ' '.join(dict.fromkeys(picname(i['ref']) for i in inf.images)),
                     ' '.join(dict.fromkeys(m[1].split('\\')[-1].split('.')[0] for m in inf.music)),
                     ' '.join('%s=%d' % kv for kv in sorted(inf.sound.items())) + (' se=%d' % len(inf.effects) if inf.effects else ''),
                     compact(fs), compact(ft), ''.join(vs), ''.join(vt),
                     ' '.join('%s(%d)' % ('menu2' if m['op'] == MENU2 else 'menu', len(m['items'])) for m in inf.menus),
                     ' '.join('FLAG%s' % s[1] for s in inf.saves), ' '.join('FLAG%s' % s[1] for s in inf.loads),
                     ' '.join(pl), ex, ' '.join(e.get(n, []))))
    tsv('summary.tsv', ('script', 'size', 'segments', 'text_runs', 'text_chars', 'waits', 'pictures', 'music', 'sound_cmds',
                        'flags_set', 'flags_tested', 'vars_set', 'vars_tested', 'menus', 'saves', 'loads', 'plugins',
                        'exec_mem', 'successors'), srow)

    # --- skeletons ---
    for n, inf in infos.items():
        with open(os.path.join(out, 'skeleton', n.replace('.', '_') + '.txt'), 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(skeleton(inf.sc)) + '\n')

    # --- report ---
    rep = []
    root = start or 'RUN'
    if root not in infos:          # the English script set has no RUN.MES
        root = 'MODE'
    reach, todo = set(), [root]
    while todo:
        x = todo.pop()
        if x in reach or x not in infos:
            continue
        reach.add(x)
        todo += e.get(x, [])
        if any(not l[2] for l in infos[x].loads):
            todo += savers
    rep.append('Scripts: %d (start: %s); reachable: %d' % (len(infos), root, len(reach)))
    rep.append('Never reached: ' + (' '.join(sorted(set(infos) - reach)) or 'none'))
    missing = sorted({(n, j['target'], '%04X' % j['off'], 'live' if j['live'] else 'dead')
                      for n, inf in infos.items() for j in inf.jumps if j['target'] not in infos})
    rep.append('Jump targets that do not exist: ' + ('; '.join('%s@%s -> %s (%s)' % (a, c, b, d) for a, b, c, d in missing) or 'none'))
    rep.append('Scripts that save (FLAG0-2) = load targets: ' + ' '.join(savers))
    rep.append('')
    rep.append('Entry drive state not set by the script itself (inherited from predecessors):')
    for n, inf in infos.items():
        first = [x for x in inf.sc.segments[0]['body'][:4] if x[0] == 'op' and x[3] == SETDRIVE]
        if len({x[4][0] for x in first}) < 2:
            rep.append('  %s: sets %s at its start; inherits %s' % (
                n, ', '.join('slot %d' % x[4][0] for x in first) or 'nothing',
                ' '.join('%d={%s}' % (s, ','.join(map(str, sorted(v)))) for s, v in sorted(entry[n].items())) or 'nothing'))
    rep.append('')
    rep.append('Oddities per script:')
    for n, inf in infos.items():
        for t in inf.notes:
            rep.append('  %s: %s' % (n, t))
    rep.append('')
    if pics:
        total = sum(len(i.images) for i in infos.values())
        ok = sum(1 for r in prow if r[8].startswith('ok'))
        rep.append('Pictures: %d image-file references (%d distinct names); resolved to exactly one file: %d; not resolved: %d'
                   % (total, len({r[2].upper().split('\\')[-1] for r in prow}), ok, total - ok))
        for n, im, status in unresolved + ambiguous:
            rep.append('  %s@%04X %s: %s' % (n, im['off'], im['ref'], status))
        multi = sorted({(r[2].upper().split('\\')[-1], r[6]) for r in prow if r[7] > 1})
        rep.append('Names with different contents on different disks: ' + ('; '.join('%s on %s' % m for m in multi) or 'none'))
        for name, _ in multi:
            if imgdir:
                rep.append('  %s on screen (decoded pictures in %s): %s' % (name, os.path.relpath(imgdir, ROOT), compare_variants(imgdir, pics, name)))
            by = collections.defaultdict(set)
            for r in prow:
                if r[2].upper().endswith('\\' + name):
                    by[r[4]].add(r[0])
            for d, ss in sorted(by.items()):
                rep.append('  %s from disk %s (md5 %s): %s' % (name, d, pics[d][name][0][:8] if name in pics.get(d, {}) else '-', ' '.join(sorted(ss))))
            # independent evidence: the other pictures the same scripts take from the same unit
            for r0 in sorted({r[0] for r in prow if r[2].upper().endswith('\\' + name)}):
                others = sorted({r[2].upper().split('\\')[-1] for r in prow
                                 if r[0] == r0 and r[2][1:2] == ':' and not r[2].upper().endswith('\\' + name)})
                hold = [d for d in DISKS if d != 'A' and all(o in pics.get(d, {}) for o in others)]
                rep.append('    %s: its other B: pictures (%d) are all on disk(s) %s' % (r0, len(others), ''.join(hold) if others else '- (none)'))
        # would a search over all disks give the same file?
        diff = [r for r in prow if r[8].startswith('ok') and r[7] > 1]
        rep.append('References whose name exists with other contents on another disk: %d' % len(diff))
        letter = collections.Counter()
        for r in prow:
            u = r[2][:2].upper() if r[2][1:2] == ':' else 'none'
            letter[(u, r[4])] += 1
        rep.append('References by drive letter and resolved disk: ' + ', '.join('%s->%s: %d' % (k[0], k[1], v) for k, v in sorted(letter.items())))
        unref = sorted((d, nm) for d in pics for nm in pics[d] if (d, nm) not in used)
        never = sorted({nm for d, nm in unref if not any((x, nm) in used for x in DISKS)})
        rep.append('Picture files never loaded from their disk (%d): %s' % (len(unref), ' '.join('%s:%s' % x for x in unref)))
        rep.append('Picture names never referenced at all: ' + (' '.join(never) or 'none'))
        rep.append('')
        refm = collections.Counter(m[1].upper().replace('\\', '/').lstrip('/') for i in infos.values() for m in i.music)
        have = {p[2:] for p in files if p.startswith('A/MUS/')}
        rep.append('Music: %d sound "file" references, %d distinct; missing: %s; on disk A but never referenced: %s' % (
            sum(refm.values()), len(refm), ' '.join(sorted(set(refm) - have)) or 'none', ' '.join(sorted(have - set(refm))) or 'none'))
        only_sound = sorted(m for m in refm if all(n == 'SOUND' for n, i in infos.items() for x in i.music if x[1].upper().replace('\\', '/').lstrip('/') == m))
        rep.append('Music referenced only by SOUND.MES: ' + (' '.join(only_sound) or 'none'))
        other = collections.Counter((f[1], f[2].upper().replace('\\', '/').lstrip('/')) for i in infos.values() for f in i.files)
        for (op, nm), c in sorted(other.items()):
            rep.append('  %s "%s" x%d: %s' % (op, nm, c, 'on disk A' if 'A/' + nm in files else 'MISSING'))
        scripts_on_disk = {p.split('/')[-1][:-4] for p in files if p.startswith('A/MES/')}
        rep.append('Scripts on disk A never reached: ' + (' '.join(sorted(scripts_on_disk - reach)) or 'none'))
    with open(os.path.join(out, 'reach.txt'), 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(rep) + '\n')
    print('\n'.join(rep))


KEEP = {MENU, MENU2, SEGCALL, JUMP, INPUT, IF, WHEN, SAVE, LOAD, SAVECHK, LOADMEM, IMAGE, SETDRIVE, SOUND,
        NAMELOAD, EXIT, EXECFILE, MESCALL, 0xC6, EXECMEM, DEFPROC, 0xD5}


def skeleton(sc):
    """The listing reduced to control flow, state and file operations."""
    out = []

    def body(nodes, ind, inmenu=False):
        pad = '  ' * ind
        ntext = 0
        for n in nodes:
            k = n[0]
            head = '%04X %s' % (n[1], pad)
            if k in ('text', 'ascii'):
                ntext += 1
                if inmenu:
                    out.append(head + '"%s"' % (n[3] if k == 'text' else mes.decode_text(n[3])).strip('　 '))
            elif k == 'ctl' and n[3].startswith('loop'):
                out.append(head + n[3])
            elif k in ('reg', 'var'):
                out.append(head + mesdis.fmt_cond(n, False))
            elif k == 'op' and n[3] in KEEP:
                if n[3] == EXECMEM and any(isinstance(a, tuple) and a[1][:3] in (b'GET', b'PUT') for a in n[4]):
                    continue
                line = head + mes.OPNAMES[n[3]]
                if n[4]:
                    line += ' ' + ' '.join(mesdis.fmt_arg(a) for a in n[4])
                mark = len(out)
                out.append(line)
                for b in n[5]:
                    c = ' '.join(mesdis.fmt_cond(x) for x in b['conds'])
                    out.append('%04X %s  %s%s:' % (b['start'], pad, b['kind'], ' [' + c + ']' if c else ''))
                    body(b['body'], ind + 2, n[3] in (MENU, MENU2))
                if n[3] == DEFPROC and len(out) == mark + 2:
                    del out[mark:]
        if ntext and not inmenu:
            out.append('     %s; %d text runs' % (pad, ntext))

    for i, seg in enumerate(sc.segments):
        c = ' '.join(mesdis.fmt_cond(x) for x in seg['conds'])
        out.append('%04X segment %d%s' % (seg['start'], i, ' [' + c + ']' if c else ''))
        body(seg['body'], 1)
    return out


def catalog(path, infos):
    """Refresh the size and successors columns of resources/scripts.tsv; keep story and role."""
    e, savers = edges(infos)
    old = {}
    if os.path.exists(path):
        with open(path, encoding='utf-8') as fh:
            head = fh.readline()
            for line in fh:
                r = line.rstrip('\n').split('\t')
                old[r[0]] = r
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('script\tstory\trole\tsize\tsuccessors\n')
        for n, inf in infos.items():
            o = old.get(n, [n, '?', '?'])
            succ = list(e.get(n, []))
            if any(not l[2] for l in inf.loads):
                succ += ['load:' + s for s in savers]
            fh.write('\t'.join((n, o[1], o[2], str(inf.size), ' '.join(succ))) + '\n')
    print('%s: %d scripts' % (path, len(infos)))


def main(argv):
    opt = dict(mes=os.path.join(ROOT, 'resources', 'original', 'pc98', 'A', 'MES'),
               ini=os.path.join(ROOT, 'resources', 'original', 'pc98', 'A', 'NV.INI'),
               out=os.path.join(ROOT, 'resources', 'derived', 'scripts'),
               inventory=os.path.join(ROOT, 'resources', 'inventory.tsv'),
               images=os.path.join(ROOT, 'resources', 'derived', 'images', 'gpc'))
    pos = []
    a = argv[1:]
    while a:
        x = a.pop(0)
        if x.startswith('--') and x[2:] in opt and a:
            opt[x[2:]] = a.pop(0)
        elif x in ('-h', '--help'):
            sys.exit(__doc__)
        else:
            pos.append(x)
    cmd = pos[0] if pos else 'export'
    infos, start, entry = build(opt['mes'], opt['ini'])
    if cmd == 'export':
        pics, files = load_inventory(opt['inventory'])
        export(infos, start, entry, opt['out'], pics, files, opt['images'] if os.path.isdir(opt['images']) else None)
    elif cmd == 'catalog' and len(pos) == 2:
        catalog(pos[1], infos)
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main(sys.argv)
