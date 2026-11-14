# Adv98X

A portable engine for games made with Adv98V 1.70.54, the PC-9801 adventure engine of Cat's Pro;
its first game is **NOVA ～魅入られた肢体～** (1993). Adv98X runs the original scripts unmodified —
the Japanese ones and the English translation by Fuzion — and aims to reproduce the PC-98 release
faithfully: text, pictures, palette effects, menus, click maps, saves and the FM music.

The engine is written from the reverse-engineering notes in [`docs/re/`](docs/re/README.md); the
implementation plan and its status are in [`docs/engine-plan.md`](docs/engine-plan.md).

**Status:** early. The interpreter runs the original scripts (Japanese and English) with
pictures, text, palette effects, menus, click maps and saves; there is no sound yet, and name
entry and a few palette effects are still missing (milestones M4, M5 of the plan).

## You need the game

The repository carries none of the game. Build the pack from your own copy:
[`docs/game-data.md`](docs/game-data.md).

## Building

C99 and GNU Make; SDL3 for the playable build (`pkg-config sdl3`); Python 3 (standard library
only) for the tools.

```sh
cd source
make data SRC="..."            # import your copy of the game (docs/game-data.md)
make pack                      # -> build/nova.pak
make TARGET=sdl3               # -> build/sdl3/adv98x
../build/sdl3/adv98x --pak ../build/nova.pak [--lang en]
../build/sdl3/adv98x --pak ../build/nova.pak --view    # the picture viewer
make TARGET=host test          # conformance tests (headless)
```

Options of the SDL3 build: `--lang ja|en`, `--fullscreen`, `--scale integer|aspect|fit|stretch`,
`--window WxH`, `--storage DIR`, `--view [PICTURE]`. Keys: the host keyboard is the PC-98's
(Return, Space, Esc, cursor keys, Shift, Ctrl, …); the Kana key of a JIS keyboard or Scroll Lock
toggles kana input (the JIS kana layout, for name entry); F11 or Alt+Return toggles fullscreen,
F12 cycles the scaling, Shift+Esc quits at once.

## Licence

GPL-3.0-or-later ([`LICENSE`](LICENSE)). Bundled third-party material keeps its own licence: the
X.Org bitmap fonts in `source/fonts/x11` (see its README).
