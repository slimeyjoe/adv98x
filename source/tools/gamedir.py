#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""gamedir - where the engine is, and where the game is.

The engine's tools, tests and research tools work on one game at a time. A game is a directory
holding game.py (the game's description: what the pack takes from which original file, the
import's rules, the build of the interpreter it ships), resources/ (its inventory and tables;
original/ and derived/ are made from the player's copy) and tests/cases.py (what the engine's
tests try on this game). Its build/ goes there too.

Which game: the environment variable GAME_DIR names its directory; set but empty means none (the
engine's make passes it so: `make` alone builds the engine, `make test` runs the tests that need
no game). Not set at all: the nearest directory holding game.py, from the current directory up,
so that a research tool run by hand in a game's tree finds it.

usage (python3 -I tools/gamedir.py ...):
  dir           print the game's directory; exit status 1 without one
  get NAME      print a value of the description, e.g. `get PACK.name`
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.normpath(os.path.join(HERE, '..', '..'))    # the engine's top directory
MARKER = 'game.py'


def find():
    """The game's directory (absolute), or None."""
    env = os.environ.get('GAME_DIR')
    if env is not None:
        return os.path.abspath(env) if env else None
    d = os.getcwd()
    while True:
        if os.path.isfile(os.path.join(d, MARKER)):
            return d
        up = os.path.dirname(d)
        if up == d:
            return None
        d = up


def require(prog='gamedir'):
    d = find()
    if d is None:
        sys.exit('%s: no game: set GAME_DIR to a game\'s directory (one holding %s)' % (prog, MARKER))
    if not os.path.isfile(os.path.join(d, MARKER)):
        sys.exit('%s: %s has no %s' % (prog, d, MARKER))
    return d


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_games = {}


def load(game=None):
    """The game's description (game.py) as a module."""
    game = game or require()
    if game not in _games:
        _games[game] = _load(os.path.join(game, MARKER), 'game')
    return _games[game]


def cases(game=None):
    """The game's test cases (tests/cases.py) as a module."""
    game = game or require()
    return _load(os.path.join(game, 'tests', 'cases.py'), 'cases')


def resources(game=None, *parts):
    return os.path.join(game or require(), 'resources', *parts)


def original(game=None, *parts):
    """resources/original: the player's files, as `gamedata.py import` puts them."""
    return resources(game, 'original', *parts)


def derived(game=None, *parts):
    """resources/derived: what `gamedata.py derive` makes from them."""
    return resources(game, 'derived', *parts)


def inventory(game=None):
    return resources(game, 'inventory.tsv')


def build(game=None, *parts):
    """The game's build directory: the pack, its fonts, the engine's objects."""
    return os.path.join(game or require(), 'build', *parts)


def get(name, game=None):
    """A value of the description by dotted name: 'PACK.name', 'ORIGINAL.interpreter.path'."""
    obj = load(game)
    for i, part in enumerate(name.split('.')):
        obj = getattr(obj, part) if i == 0 else obj[part]
    return obj


def main(argv):
    if len(argv) == 1 and argv[0] == 'dir':
        d = find()
        if d is None:
            return 1
        print(d)
        return 0
    if len(argv) == 2 and argv[0] == 'get':
        print(get(argv[1]))
        return 0
    sys.exit('usage' + __doc__.split('usage', 1)[1].rstrip())


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
