#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""The original game data: import it from your copies of the releases, check it, derive from it.

The repository carries none of the game (Cat's Pro, 1993), only an inventory of its files:
resources/inventory.tsv (release, path, size, mtime, md5, kind). This is lrvne's import
framework (source/lrvne/tools: lrvne.inventory, which finds the files in whatever you have:
directories, zip/7z/rar archives, floppy and hard-disk images, nested in any order) with what
only this game's tools know: where a release goes, how to read the Windows release's archive
(EVE.PCK), and the derived data.

usage (python3 -I tools/gamedata.py ...):
  import [SRC...] [--out DIR]    copy the files of the inventory from your media into
                                 resources/original/<release>/<path> (not committed)
  check [-q] [--out DIR]         verify that tree; exit status 1 while the PC-98 release is
                                 incomplete
  scan [SRC...]                  print inventory rows for what SRC holds (maintenance): the
                                 PC-98 floppies are recognised by their volume label, the
                                 members of EVE.PCK are the Windows release's, other files
                                 are rows of the release named in the environment variable
                                 SCAN_RELEASE (default: en)
  derive [PART...] [--python PY] everything the documents and tests refer to, see below
SRC defaults to the directories named in the LRVNE_MEDIA environment variable.

Releases in the inventory (column 1; destination resources/original/<release>/...):
  pc98      the four 2HD floppies of 1993-05-28, kept per disk (pc98/A/..., pc98/B/GPC/...):
            the same name can hold different data on different disks
  win       members of the Windows 1996 EVE.PCK (research only; optional)
  en        the scripts of the English translation by Fuzion (the files that differ; optional)
A file is recognised by name + md5 wherever it is found, so a hard-disk install of the
Japanese release supplies the pc98 rows too.
The disk-A files FLAG0..FLAG5 and NAME.DEF are the state the dumped copy was left in (saves,
unlocks, the owner's name): they are imported as test inputs and must never go into a pack.

derive: made from resources/original/ into resources/derived/ (not committed) by the tools in
re-tools/ and source/tools/:
    exe      the unpacked executables (exeunpack.py)            -> derived/exe/
    scripts  listings, strings, graph of the Japanese and English scripts (mesdis.py,
             mesgraph.py)                                        -> derived/scripts[-en]/
    images   every GPC as PNG (gpc.py)                           -> derived/images/gpc/
    listing  annotated listings of the plug-ins (tcmtool.py), of AdvBIOS and of the interpreter
             (dis16.py with docs/re/listing/*-names.tsv)        -> derived/listing/
    vgm      reference recordings (VGM and register-write logs) of all songs from the original
             driver under emulation (usdemu.py; needs unicorn: --python names a Python that
             has it)                                             -> derived/music/vgm/
  Default: all parts; a part whose Python module is missing is skipped with a note.
"""
import glob
import os
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
ORIG = os.path.join(ROOT, 'resources', 'original')
INVENTORY = os.path.join(ROOT, 'resources', 'inventory.tsv')
sys.path.insert(0, os.path.join(HERE, '..', 'lrvne', 'tools'))
from lrvne import inventory   # noqa: E402

FLOPPY_LABEL = 'NOVA____98'     # volume labels NOVA____98A .. D


def load_inventory():
    """The rows of resources/inventory.tsv (lrvne.inventory.Row: name = the path inside the
    release, get('release'), get('kind'))."""
    return inventory.Inventory.load(INVENTORY).rows


# ---- the Windows release's archive ("PCK Version 1.00") ----------------------------------------

def _rol_words(b):
    o = bytearray(len(b))
    for i in range(0, len(b) & ~1, 2):
        w = b[i] | b[i + 1] << 8
        w = (w << 1 | w >> 15) & 0xFFFF
        o[i], o[i + 1] = w & 255, w >> 8
    return bytes(o)


def is_pck(d):
    return len(d) >= 0x4000 and _rol_words(d[:16]) == b'PCK Version 1.00'


def pck_members(d):
    """(name, data) of every member. The first 0x4000 bytes (header + 511 entries of 32 bytes)
    are stored with every 16-bit word rotated right by one bit; member data is plain."""
    head = _rol_words(d[:0x4000])
    for p in range(0x20, 0x4000, 32):
        name = head[p:p + 16].split(b'\0')[0].strip()
        if not name:            # a free slot, or the entry after the last member
            continue
        off, size = struct.unpack_from('<II', head, p + 16)
        yield name.decode('ascii'), d[off:off + size]


def read_pck(data):
    """The archive as lrvne's sources read one of a game's own format: its members, or None
    when the file is not a PCK archive."""
    return list(pck_members(data)) if is_pck(data) else None


# ---- scan (maintenance) --------------------------------------------------------------------

def kind_of(path):
    ext = os.path.splitext(path)[1].upper()
    return {'.MES': 'script', '.GPC': 'image', '.USO': 'music', '.TCM': 'plug-in code',
            '.CLM': 'map hit table', '.PI': 'image (Pi)', '.EVE': 'script (EVE)',
            '.WAV': 'sound effect', '.CDF': 'map hit table', '.OVL': 'engine', '.OV1': 'engine',
            '.COM': 'engine loader', '.INI': 'engine start script', '.EXE': 'installer',
            '.SYS': 'boot', '.DEF': 'default name'}.get(ext, 'save' if 'FLAG' in path.upper() else 'other')


def scan_row(entry, _data):
    label = entry.volume_label
    if label.startswith(FLOPPY_LABEL):
        release, path = 'pc98', label[-1] + '/' + entry.inner_path
    elif entry.kind == 'container':
        release, path = 'win', entry.inner_path
    else:
        release, path = os.environ.get('SCAN_RELEASE', 'en'), entry.inner_path
    return {'path': path, 'release': release, 'mtime': entry.mtime, 'kind': kind_of(path)}


HOOKS = inventory.Hooks(
    dest_path=lambda row: row.get('release') + '/' + row.name,
    required=lambda row: row.get('release') == 'pc98',
    group=lambda row: row.get('release'),
    scan_row=scan_row,
    containers={'.pck': read_pck})


# ---- derive --------------------------------------------------------------------------------

DERIVE_PARTS = ('exe', 'scripts', 'images', 'listing', 'vgm')


def cmd_derive(a):
    retools = os.path.join(ROOT, 're-tools')
    der = os.path.join(ROOT, 'resources', 'derived')
    disk_a = os.path.join(a.out, 'pc98', 'A')
    if not os.path.isdir(disk_a):
        sys.exit('gamedata: %s is missing: import the game first' % disk_a)
    py = a.python or sys.executable

    def run(interp, *args):
        cmd = [interp] + (['-I'] if interp == sys.executable else []) + list(args)
        r = subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        tail = r.stdout.strip().splitlines()[-1:] or ['']
        print('  %s %s' % ('ok  ' if r.returncode == 0 else 'FAIL', tail[0][:110]))
        return r.returncode == 0

    def has(interp, mod):
        return subprocess.run([interp, '-c', 'import ' + mod], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0
    ok = True
    for part in a.parts or DERIVE_PARTS:
        print('derive %s:' % part)
        if part == 'exe':
            os.makedirs(os.path.join(der, 'exe'), exist_ok=True)
            for f in ('NV.OVL', 'NV.OV1', 'INSTH.EXE'):
                ok &= run(sys.executable, os.path.join(retools, 'exeunpack.py'),
                          os.path.join(disk_a, f), os.path.join(der, 'exe', f))
        elif part == 'scripts':
            ja = sorted(glob.glob(os.path.join(disk_a, 'MES', '*.MES'))) + [os.path.join(disk_a, 'NV.INI')]
            en = sorted(glob.glob(os.path.join(a.out, 'en', 'MES', '*.MES')))
            ok &= run(sys.executable, os.path.join(retools, 'mesdis.py'), 'check', *(ja + en))
            ok &= run(sys.executable, os.path.join(retools, 'mesdis.py'), 'export', os.path.join(der, 'scripts'), *ja)
            if en:
                ok &= run(sys.executable, os.path.join(retools, 'mesdis.py'), 'export', os.path.join(der, 'scripts-en'), *en)
        elif part == 'images':
            files = sorted(glob.glob(os.path.join(a.out, 'pc98', '*', 'GPC', '*.GPC')))
            ok &= run(sys.executable, os.path.join(HERE, 'gpc.py'), 'png', *files, '-o',
                      os.path.join(der, 'images', 'gpc'), '--disk-prefix')
        elif part == 'listing':
            if not has(py, 'capstone'):
                print('  skipped: %s has no capstone (--python)' % py)
                continue
            ok &= run(py, os.path.join(retools, 'tcmtool.py'), 'list')
            # NV.OV1 (AdvBIOS) and NV.OVL (the interpreter), named from docs/re/listing/
            names = os.path.join(ROOT, 'docs', 're', 'listing')
            lst = os.path.join(der, 'listing')
            os.makedirs(lst, exist_ok=True)
            ok &= run(py, os.path.join(retools, 'dis16.py'), os.path.join(der, 'exe', 'NV.OV1'),
                      '--names', os.path.join(names, 'advbios-names.tsv'),
                      '--out', os.path.join(lst, 'advbios.lst'))
            ovl_names = os.path.join(lst, 'nvovl-names.seg.tsv')     # bare offsets -> 0000:OFF
            with open(os.path.join(names, 'nvovl-names.tsv'), encoding='utf-8') as fi, \
                    open(ovl_names, 'w', encoding='utf-8') as fo:
                for line in fi:
                    if line.strip() and not line.startswith('#') and '\t' in line:
                        fo.write('0000:' + line)
            ok &= run(py, os.path.join(retools, 'dis16.py'), os.path.join(der, 'exe', 'NV.OVL'),
                      '--names', ovl_names, '--out', os.path.join(lst, 'nvovl.lst'))
        elif part == 'vgm':
            if not has(py, 'unicorn'):
                print('  skipped: %s has no unicorn (--python)' % py)
                continue
            if not os.path.exists(os.path.join(der, 'exe', 'NV.OV1')):
                print('  skipped: derive exe first')
                continue
            ok &= run(py, os.path.join(retools, 'usdemu.py'), '--all', '--logs')
        else:
            sys.exit('gamedata: unknown part %s (parts: %s)' % (part, ' '.join(DERIVE_PARTS)))
    return 0 if ok else 1




def add_derive_arguments(p):
    p.add_argument('parts', nargs='*')
    p.add_argument('--python')
    p.add_argument('--out', default=ORIG)


def main():
    return inventory.run_cli(None, INVENTORY, ORIG, hooks=HOOKS, prog='gamedata',
                             description=__doc__.split('\n')[0],
                             commands={'derive': (add_derive_arguments, cmd_derive)})


if __name__ == '__main__':
    sys.exit(main())
