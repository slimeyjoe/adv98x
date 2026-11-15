# Adv98X

A portable engine for games made with Adv98V 1.70.54, the PC-9801 adventure engine of Cat's Pro;
its first game is **NOVA ～魅入られた肢体～** (1993). Adv98X runs the original scripts unmodified —
the Japanese ones and the English translation by Fuzion — and aims to reproduce the PC-98 release
faithfully: text, pictures, palette effects, menus, click maps, saves and the FM music.

The engine is written from the reverse-engineering notes in [`docs/re/`](docs/re/README.md); the
implementation plan and its status are in [`docs/engine-plan.md`](docs/engine-plan.md). It is
the interpreter, AdvBIOS's services, the picture decoder, the music driver and the plug-ins;
everything underneath (frame loop, screen, FM chip, fonts, the asset pack, the backends) is
**lrvne**, a library shared with sibling engines, which lives in the git submodule
`source/lrvne` and is compiled into the engine.

**Status:** the game plays through, in Japanese and English: the original scripts with pictures,
text, palette effects, menus, click maps, saves, name entry and the FM music. Verified against
the original interpreter and AdvBIOS running under emulation: every story and all five endings,
in both languages, play to the same memory, screen, saves and sound calls as the original
(`make TARGET=host e2e`). Not yet tuned by ear and eye (music balance, timing feel). Still
missing: features NOVA does not use (animation cells, beeper, the STOP-key quit prompt).

## You need the game

The repository carries none of the game. Build the pack from your own copy:
[`docs/game-data.md`](docs/game-data.md).

## Building

C99, C++14 (the ymfm sound core) and GNU Make 4; SDL3 for the playable build (`pkg-config
sdl3`); Python 3 (standard library only) for the tools.

```sh
git submodule update --init    # source/lrvne
cd source
make data SRC="..."            # import your copy of the game (docs/game-data.md)
make pack                      # -> build/adv98x.pak
make TARGET=sdl3               # -> build/sdl3/adv98x
../build/sdl3/adv98x --pak ../build/adv98x.pak [--lang en]
../build/sdl3/adv98x --pak ../build/adv98x.pak --view    # the picture viewer
make TARGET=host test          # conformance tests (headless; the emulation references need
                               # a Python with unicorn: EMU_PYTHON=..., docs/re/README.md "Tools")
make TARGET=host e2e           # every story and ending, engine vs the original (~15 min)
```

Options of the SDL3 build (`adv98x --help`): `--lang ja|en`, `--fullscreen`,
`--scale integer|aspect|fit|stretch`, `--window WxH`, `--volume 0..100`, `--no-audio`,
`--opn ymfm|lite`, `--storage DIR`, `--pak FILE`, `--view [PICTURE]`, `--version`. Keys: the host keyboard is the
PC-98's (Return, Space, Esc, cursor keys, Shift, Ctrl, …); the Kana key of a JIS keyboard or
Scroll Lock toggles kana input (the JIS kana layout, for name entry); F11 or Alt+Return toggles
fullscreen, F12 cycles the scaling, **Ctrl+Shift+R resets** (the game starts again at its title,
saves kept: the way out of an ending, which loops for ever as on the PC-98), Shift+Esc quits at
once.

Without `--pak` the program looks for the pack bundled into itself, then `adv98x.pak` (or the
only `.pak`) next to it, then in the current directory. Saves are the original's
`FLAG0`–`FLAG9` and `NAME.DEF` in `$XDG_DATA_HOME/adv98x/nova` (docs/game-data.md "Saves").

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
make TARGET=aros test              # the AROS program in hosted AROS (AROS_HOSTED=...)
make TARGET=host be68k             # the engine big-endian (m68k-linux-gnu-gcc, qemu-m68k)
```

## Release archives

```sh
make TARGET=sdl3 dist    # ../build/sdl3/adv98x-<version>-sdl3-<os>-<arch>.tar.gz: the stripped
                         # executable, the player's ReadMe, the licences; no game data
make TARGET=amiga dist   # ../build/amiga/adv98x-<version>-amiga.lha (warpos, aros alike): the
                         # drawer Adv98X with the program, its ReadMe and the licence
make dist-src            # ../build/adv98x-<version>-src.tar.gz: the committed tree with the
                         # lrvne submodule's
```

The version is `source/engine/version.h`. The player's ReadMe is `source/dist/ReadMe.txt`;
the Amiga family's is put together from the parts in `source/dist/amiga/`.

## Licence

GPL-3.0-or-later ([`LICENSE`](LICENSE)), as is lrvne. Third-party material that lrvne carries
keeps its own licence: the X.Org bitmap fonts in `source/lrvne/fonts/x11` (see its README) and
ymfm, the OPN emulator, in `source/lrvne/third_party/ymfm` (BSD 3-Clause).
