#!/usr/bin/env python3
"""Adv98V .MES script lister / checker / exporter (research tool; parser: source/tools/mes.py).

  python3 -I re-tools/mesdis.py list FILE...            # structured listing on stdout
  python3 -I re-tools/mesdis.py check FILE...           # coverage + block-scanner agreement
  python3 -I re-tools/mesdis.py export OUTDIR FILE...   # listing/*.txt, strings.tsv, assets.tsv,
                                                        # graph.tsv, flags.tsv, vars.tsv, ops.tsv
The exports hold the game's text: OUTDIR belongs under resources/derived/ (not committed).
"""
import collections
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'source', 'tools'))
import mes   # noqa: E402


def fmt_arg(a):
    if a is None:
        return '-'
    if isinstance(a, tuple):
        if a[0] == 'str':
            return '"%s"' % a[1].decode('cp932', 'replace')
        if a[0] == 'letter':
            return a[1]
        return '(%s)' % ','.join(fmt_arg(x) for x in a)
    return str(a)


def fmt_cond(n, test=True):
    if n[0] == 'reg':
        return 'R%d%s%d' % (n[3], '==' if test else '=', n[4])
    op = n[4]
    if test:
        op = {'=': '==', '+': '>=', '-': '<='}[op]
    else:
        op = {'=': '=', '+': '+=', '-': '-='}[op]
    return '%s%s%d' % (mes.var_name(n[3]), op, n[5])


def listing(sc, out):
    def body(nodes, ind):
        pad = '  ' * ind
        for n in nodes:
            k = n[0]
            head = '%04X %s' % (n[1], pad)
            if k == 'text':
                out.append(head + '"%s"' % n[3])
            elif k == 'nl':
                out.append(head + 'newline')
            elif k == 'ctl':
                out.append(head + n[3])
            elif k == 'ascii':
                out.append(head + 'ascii "%s"' % n[3].decode('cp932', 'replace'))
            elif k in ('reg', 'var'):
                out.append(head + fmt_cond(n, False))
            elif k == 'end':
                out.append(head + 'end ' + n[3])
            elif k == 'stray':
                out.append(head + 'stray %02X  ; defect' % n[3])
            elif k == 'op':
                line = head + mes.OPNAMES[n[3]]
                if n[4]:
                    line += ' ' + ' '.join(fmt_arg(a) for a in n[4])
                out.append(line)
                for b in n[5]:
                    c = ' '.join(fmt_cond(x) for x in b['conds'])
                    out.append('%04X %s  %s%s:' % (b['start'], pad, b['kind'], ' [' + c + ']' if c else ''))
                    body(b['body'], ind + 2)
    for i, seg in enumerate(sc.segments):
        c = ' '.join(fmt_cond(x) for x in seg['conds'])
        out.append('%04X segment %d%s' % (seg['start'], i, ' [' + c + ']' if c else ''))
        body(seg['body'], 1)
    if sc.decrypt_from is not None:
        out.append('; decrypted from %04X on' % sc.decrypt_from)
    if sc.trailer:
        out.append('%04X trailer: %d bytes' % (sc.trailer[0], len(sc.trailer[1])))
    for off, text in sc.defects:
        out.append('; defect at %04X: %s' % (off, text))


def check(path):
    """Parse, require full coverage, and compare block ends with the interpreter's scanner."""
    sc = mes.parse(open(path, 'rb').read())
    if not all(sc.covered):
        return ['%d bytes not covered' % sc.covered.count(0)]
    problems = []
    d = sc.data
    cut = {o for o, _ in sc.defects}
    for seg in sc.segments:
        for n in mes.walk(seg['body']):
            if n[0] != 'op' or not n[5]:
                continue
            op, blocks = n[3], n[5]
            end = n[2]
            if end in cut or end - 0 in cut:
                continue
            if op in (0xAD, 0xAE):
                start = blocks[0]['end']          # after the A2 that ends the head
            else:
                start = blocks[0]['start']
            try:
                scan = mes.skip_block(d, start, 0xA2, 0xA3)
            except IndexError:
                scan = -1
            if scan != end:
                problems.append('%s at %04X: parser ends %04X, block scanner %04X' % (mes.OPNAMES[op], n[1], end, scan))
    return problems


def export(outdir, files):
    os.makedirs(os.path.join(outdir, 'listing'), exist_ok=True)
    strings, assets, graph = [], [], []
    flags = collections.defaultdict(lambda: collections.Counter())
    vars_ = collections.defaultdict(lambda: collections.Counter())
    ops = collections.Counter()
    for f in files:
        name = os.path.splitext(os.path.basename(f))[0].upper()
        sc = mes.parse(open(f, 'rb').read())
        out = []
        listing(sc, out)
        with open(os.path.join(outdir, 'listing', name + '.txt'), 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(out) + '\n')

        def visit(nodes, cond_ctx):
            for n in nodes:
                if n[0] in ('text', 'ascii'):
                    t = n[3] if n[0] == 'text' else n[3].decode('cp932', 'replace')
                    strings.append((name, '%04X' % n[1], n[0], t))
                elif n[0] == 'reg':
                    flags[n[3]]['set=%d' % n[4]] += 1
                    flags[n[3]]['files:' + name] += 1
                elif n[0] == 'var':
                    vars_[mes.var_name(n[3])]['write'] += 1
                elif n[0] == 'op':
                    ops[n[3]] += 1
                    for a in n[4]:
                        if isinstance(a, tuple) and a[0] == 'str':
                            s = a[1].decode('cp932', 'replace')
                            if n[3] == 0xB1:
                                graph.append((name, '%04X' % n[1], s))
                            assets.append((name, '%04X' % n[1], mes.OPNAMES[n[3]], s))
                    for b in n[5]:
                        for c in b['conds']:
                            if c[0] == 'reg':
                                flags[c[3]]['test'] += 1
                                flags[c[3]]['files:' + name] += 1
                            else:
                                vars_[mes.var_name(c[3])]['test'] += 1
                        visit(b['body'], True)
        for seg in sc.segments:
            for c in seg['conds']:
                if c[0] == 'reg':
                    flags[c[3]]['test'] += 1
                    flags[c[3]]['files:' + name] += 1
                else:
                    vars_[mes.var_name(c[3])]['test'] += 1
            visit(seg['body'], False)

    def tsv(fn, head, rows):
        with open(os.path.join(outdir, fn), 'w', encoding='utf-8') as fh:
            fh.write('\t'.join(head) + '\n')
            for r in rows:
                fh.write('\t'.join(str(x) for x in r) + '\n')
    tsv('strings.tsv', ('script', 'offset', 'kind', 'text'), strings)
    tsv('assets.tsv', ('script', 'offset', 'op', 'string'), assets)
    tsv('graph.tsv', ('script', 'offset', 'target'), graph)
    tsv('flags.tsv', ('flag', 'set1', 'set0', 'tests', 'scripts'),
        [(k, v['set=1'], v['set=0'], v['test'], ' '.join(sorted(x[6:] for x in v if x.startswith('files:'))))
         for k, v in sorted(flags.items())])
    tsv('vars.tsv', ('var', 'writes', 'tests'), [(k, v['write'], v['test']) for k, v in sorted(vars_.items())])
    tsv('ops.tsv', ('opcode', 'name', 'count'), [('%02X' % k, mes.OPNAMES[k], v) for k, v in sorted(ops.items())])
    print('%d scripts, %d strings, %d flags, %d asset references' % (len(files), len(strings), len(flags), len(assets)))


def main(a):
    if len(a) < 3:
        sys.exit(__doc__)
    if a[1] == 'list':
        for f in a[2:]:
            out = ['; ' + f]
            listing(mes.parse(open(f, 'rb').read()), out)
            print('\n'.join(out))
    elif a[1] == 'check':
        bad = 0
        for f in a[2:]:
            try:
                p = check(f)
            except Exception as e:      # noqa: BLE001
                p = [repr(e)]
            for x in p:
                print('%s: %s' % (f, x))
            bad += bool(p)
        print('%d files checked, %d with problems' % (len(a) - 2, bad))
        sys.exit(1 if bad else 0)
    elif a[1] == 'export':
        export(a[2], a[3:])
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main(sys.argv)
