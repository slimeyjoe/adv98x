# SPDX-License-Identifier: GPL-3.0-or-later
"""refs.py: the references of the checks against the original (the interpreter and AdvBIOS
under emulation: check_vm, check_text, check_palette), kept between runs: lrvne's refcache
(lrvne/tools/lrvne/refcache.py) with what they depend on.

A reference is the same for the same inputs, none of which is the engine: the code that
computes it (the modules of the engine's and the game's trees it loaded: lrvne records them;
and the game's description and test cases, which tools/gamedir.py loads by path), the game's
imported and derived files (the unpacked originals), the fonts when the check draws text,
unicorn's version, and the call's arguments.

Entries are the game's build/refcache/<kind>/... (REFCACHE_DIR overrides). REFCACHE selects the
mode: on (default), off, refresh, verify (lrvne's refcache says what they do).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
sys.path.insert(1, os.path.join(HERE, '..', 'lrvne', 'tools'))
import gamedir  # noqa: E402
from lrvne import refcache  # noqa: E402

_cache = None


def cache():
    global _cache
    if _cache is None:
        import unicorn
        game = gamedir.require('refs')
        _cache = refcache.Cache(
            os.environ.get('REFCACHE_DIR') or gamedir.build(game, 'refcache'),
            code_roots=[gamedir.ENGINE, game],
            code_files=[os.path.join(game, 'game.py'), os.path.join(game, 'tests', 'cases.py')],
            data=[gamedir.original(game), gamedir.derived(game, 'exe')],
            salt='unicorn %s' % unicorn.__version__)
    return _cache


def plain(v):
    """the arguments as lrvne's refcache takes them: tuples as lists"""
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    if isinstance(v, bytes):
        return v.hex()
    return v


def get(kind, args, compute, fonts=None):
    """compute() for these arguments, or its stored result: (result, True if stored)"""
    if fonts is not None and not os.path.isfile(os.path.join(fonts, 'k16.xfnt')):
        # the harness would draw stand-in glyphs: never a reference
        raise refcache.RefcacheError('refs: no k16.xfnt in %s' % fonts)
    return cache().get(kind, plain(args), compute, data=[fonts] if fonts else [])
