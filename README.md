# Adv98X

A portable engine for games made with Adv98V 1.70.54, the PC-9801 adventure engine of Cat's Pro.
Adv98X runs a game's original scripts unmodified and aims to reproduce its PC-98 release
faithfully: text, pictures, palette effects, menus, click maps, saves and the FM music. It is the
interpreter, AdvBIOS's services, the picture decoder, the music driver and the plug-ins as native
modules; everything underneath (frame loop, screen, FM chip, fonts, the asset pack, the backends)
is [lrvne](https://github.com/slimeyjoe/lrvne), a library shared with sibling engines, in the
submodule `source/lrvne`.

**A game is a repository of its own** that has this engine as its submodule `engine/`: the
game's description (`game.py`: what its pack takes from which original file, its profile, how
its files are imported), the inventory of its files, its own research, its test cases. The
first is **NOVA ～魅入られた肢体～** (1993): [adv98x-nova](https://github.com/slimeyjoe/adv98x-nova),
the place to start if you want to play it. Its original scripts play in Japanese and in Fuzion's
English translation.

The engine is written from the reverse-engineering notes in [`docs/re/`](docs/re/README.md),
read from NOVA's copy of the original programs; the implementation plan and its status are in
[`docs/engine-plan.md`](docs/engine-plan.md).

**Status:** NOVA plays through, in Japanese and English. Verified against the original
interpreter and AdvBIOS running under emulation: every story and all five endings, in both
languages, play to the same memory, screen, saves and sound calls as the original. Not yet tuned
by ear and eye (music balance, timing feel). Still missing: features NOVA does not use
(animation cells, beeper, the STOP-key quit prompt). The research describes one build of
Adv98V 1.70.54 and AdvBIOS 0.54, the one on NOVA's disks; a game with another build needs its
tables first (`re-tools/advbuild.py`).

## Building

C99, C++14 (the ymfm sound core) and GNU Make 4; SDL3 for the playable build (`pkg-config
sdl3`); Python 3 (standard library only) for the tools.

Alone, the engine builds and runs the tests that need no game:

```sh
git submodule update --init    # source/lrvne
cd source
make TARGET=sdl3               # -> ../build/sdl3/adv98x
make TARGET=host test          # the tests that need no game
```

Everything else is done from a game's directory, whose `Makefile` runs this one with the game
(`GAME_DIR`): `make data SRC=...`, `make pack`, `make TARGET=sdl3`, `make test` (with the game;
the emulation references need a Python with unicorn: `EMU_PYTHON=...`, `docs/re/README.md`
"Tools"), `make e2e`. The comparisons with the original need the original programs, which
come with a game: the engine's verification runs from a game's repository.

Options of the SDL3 build (`adv98x --help`): `--lang CODE`, `--fullscreen`,
`--scale integer|aspect|fit|stretch`, `--window WxH`, `--volume 0..100`, `--no-audio`,
`--opn ymfm|lite`, `--storage DIR`, `--pak FILE`, `--view [PICTURE]`, `--version`. Keys: the
host keyboard is the PC-98's (Return, Space, Esc, cursor keys, Shift, Ctrl, …); the Kana key of
a JIS keyboard or Scroll Lock toggles kana input (the JIS kana layout, for name entry); F11 or
Alt+Return toggles fullscreen, F12 cycles the scaling, **Ctrl+Shift+R resets** (the game starts
again at its title, saves kept: the way out of an ending that loops for ever as on the PC-98),
Shift+Esc quits at once.

Without `--pak` the program looks for the pack bundled into itself, then `adv98x.pak` (or the
only `.pak`) next to it, then in the current directory. Saves are the original's files
(`FLAG0`–`FLAG9`, `NAME.DEF`) in `$XDG_DATA_HOME/adv98x/<game id>`.

## Amiga, WarpOS, AROS

The same engine builds for the Amiga family on lrvne's Amiga backend: AmigaOS 3.x on a 68020 or
better (`make TARGET=amiga`, vbcc), PowerPC cards under WarpOS (`TARGET=warpos`, vbcc) and AROS
x86_64 (`TARGET=aros`, the AROS gcc), with the light FM core (on the 68k its render loop in
assembly). Toolchains, options, saves, what was changed for them, and how they are tested
(the AROS build in hosted AROS, the whole engine on a big-endian 68040 under qemu-m68k):
[`docs/amiga.md`](docs/amiga.md). The 68k and WarpOS programs build and link but have not been
run yet.

```sh
make TARGET=amiga                  # -> build/amiga/adv98x (also warpos, aros)
make TARGET=aros test              # the AROS program in hosted AROS (AROS_HOSTED=...; with a game)
make TARGET=host be68k             # the engine big-endian (m68k-linux-gnu-gcc, qemu-m68k; with a game)
```

## Release archives

```sh
make TARGET=sdl3 dist    # build/sdl3/adv98x-<version>-sdl3-<os>-<arch>.tar.gz: the stripped
                         # executable, the player's ReadMe, the licences; no game data
make TARGET=amiga dist   # build/amiga/adv98x-<version>-amiga.lha (warpos, aros alike): the
                         # drawer Adv98X with the program, its ReadMe and the licence
make dist-src            # build/<name>-<version>-src.tar.gz: the committed tree with every
                         # submodule's
```

The version is `source/engine/version.h`. The player's ReadMe is `source/dist/ReadMe.txt`, the
Amiga family's is put together from the parts in `source/dist/amiga/`; a game's own
`dist/ReadMe.txt` and `dist/amiga/` parts replace them in its archives.

## Credits and licence

GPL-3.0-or-later ([`LICENSE`](LICENSE)), as is lrvne. Third-party material keeps its own
licence: the X.Org bitmap fonts in `source/lrvne/fonts/x11` (see its README), ymfm, the OPN
emulator, in `source/lrvne/third_party/ymfm` (BSD 3-Clause), and the names marked "VB" in
`docs/re/listing/advbios-names.tsv`, taken from Valley Bell's annotated AdvBIOS disassembly
(PC98VNResearch: code GPL-2.0-or-later, documents CC-BY-SA 4.0). The research builds on
prior work, credited in [`docs/re/README.md`](docs/re/README.md). Adv98V, AdvBIOS and the games
are Cat's Pro's; this engine is not affiliated with or endorsed by them.
