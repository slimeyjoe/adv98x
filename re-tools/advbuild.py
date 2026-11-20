#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""advbuild - the build of Adv98V 1.70.54 this research describes, and the check for it.

The documents in docs/re/, the name tables in docs/re/listing/ and the harnesses (advbios_emu,
nvovl_emu, usdemu, gpc_verify) give addresses in one build of the interpreter (NV.OVL) and of
AdvBIOS 0.54 (NV.OV1): the one on NOVA's disks (1993), which is where they were read. Another
build of the same version is not the same: the AdvBIOS of Dengeki Nurse has the same code with
a data segment 48 bytes longer (re-tools/advbios_map.py). So the harnesses take only this build,
and a game whose originals are another one needs its own tables first.

The md5s are of the images as exeunpack.py leaves them (`gamedata.py derive exe`).

usage: python3 -I re-tools/advbuild.py FILE...    say which part of the build each file is
"""
import hashlib
import sys

INTERPRETER = {'name': 'the interpreter (NV.OVL)', 'md5': '1750191fda9b882760eabbed67c79c27'}
BIOS = {'name': 'AdvBIOS 0.54 (NV.OV1)', 'md5': '51ea8ab9876014b5c37001c0bc5820be'}


class WrongBuild(RuntimeError):
    pass


def check(data, part, path='the file'):
    """data if it is that part of the build (INTERPRETER or BIOS), else WrongBuild."""
    md5 = hashlib.md5(data).hexdigest()
    if md5 != part['md5']:
        raise WrongBuild('%s is not %s of the build this research describes (md5 %s, expected '
                         '%s; re-tools/advbuild.py)' % (path, part['name'], md5, part['md5']))
    return data


def main(paths):
    rc = 0
    for path in paths:
        md5 = hashlib.md5(open(path, 'rb').read()).hexdigest()
        part = next((p for p in (INTERPRETER, BIOS) if p['md5'] == md5), None)
        print('%s: %s' % (path, part['name'] if part else 'not of this build (md5 %s)' % md5))
        rc |= part is None
    return rc


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]) if len(sys.argv) > 1 else __doc__)
