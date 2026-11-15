# Adv98X — a new engine for Adv98V 1.70.54 games (first game: NOVA)

The implementation plan, approved 2026-11-14. Status: research (phase 1) complete, housekeeping
before M0 done, **M0–M4 done** (2026-11-14); M5 mostly done (left: animation cells, beeper
sound, STOP-key prompt — none used by NOVA); **M6 done** (2026-11-14): every story and ending,
both languages, played through the engine and the original interpreter with identical results
(`make TARGET=host e2e`). **M7 done** (2026-11-14): reset key, volume, `--help`/`--version`,
release archives, README; what remains is in "Open items (after M7)" below. **On lrvne**
(2026-11-15): the platform layer copied from Xenon at the start is gone, the engine is built on
the shared library lrvne ("Layering" below). Update the status line and tick milestones here as
they land; decisions taken while implementing are in "Implementation notes" at the end.

## Context

Phase 1 (research) is finished: `docs/re/` documents the original interpreter
(`NV.OVL`), AdvBIOS (`NV.OV1`), the script format, pictures, the music driver, the five plug-ins and
the game's structure, each with a verified tool (`docs/re/README.md` is the index). Phase 2 is the
engine: a portable C99 program that runs the original scripts unmodified — Japanese, and Fuzion's
English scripts, which differ only in the 117 `.MES` files — and reproduces the PC-98 release
faithfully.

Decisions already made by the user:

- Generic Adv98V engine, NOVA as its first game profile, no game-specific hacks in the engine;
  plug-in (`.TCM`) behaviour is provided by native modules that are enabled per game.
- SDL3 first; keep the design open for the Amiga family later.
- Start from a **copy** of Xenon's platform layer; a shared layer may be considered later
  (it was: lrvne, see "Layering").
- Licence **GPL-3** (as the Xenon port's files that were copied are). Bundled third-party code keeps its own licences (ymfm BSD-3, fonts).
- Engine name **Adv98X**: binary `adv98x`, C prefix `ax_`. The repository and the game profile stay
  `nova`; the pack was `nova.pak` and is `adv98x.pak` since the move to lrvne (a pack is found by
  the program's name; the game is named by the pack's profile).
- FM music first, CD-DA optional later. Japanese and English first; Polish is a later, separate
  effort and the player-name question is left open (the engine must not preclude either answer).
- A fresh install starts locked (no `FLAG3`–`FLAG5`), like a new copy of the game.
- No game data in the repository, ever: everything is built from the user's originals by tools.

## Architecture

```
source/
  lrvne/                  the shared low-level library (git submodule), compiled into the engine:
                          include/lrvne/*.h (hal, app, sys, gfx, font, pack, profile, opn, opnq,
                          mixer, pc98, ...), src/, backends/ (null, sdl3, common, control), tools/
                          (Python: pack, fonts, disk images, inventory), fonts/, third_party/ymfm
  engine/
    main.c                the engine as a backend sees it: struct lrv_app (options, trace kind
                          names, wait_is_input) and main = lrv_app_main
    ax.h                  the one state struct (embeds lrv_sys, lrv_screen, lrv_pack, lrv_font,
                          lrv_opnq, lrv_mixer), trace and wait kinds, pack entry types, the profile
    gfx/                  gpc.c (GPC decoder); cursor.c (mouse pointer) and textlayer.c (the
                          semigraphic curtain), both overlays of the screen
    bios/                 the AdvBIOS service layer the VM and the modules call:
                          bios_sys.c (20 ms tick, BIOS key buffer and key-down bitmap, waits, RNG,
                          quit, click maps), bios_mouse.c (INT 33h, keyboard emulation),
                          bios_file.c (files, drives, saves), bios_gfx.c (picture show, palette
                          buffer, brightness), bios_text.c (window, cursor, char/string draw, fill,
                          invert, scroll), bios_snd.c (INT F4h functions)
    vm/                   mes_vm.c (the interpreter and its 64 KB segment), mes_menu.c (menu /
                          menu2)
    mod/                  native plug-in modules + registry (mod.h): chgfonth.c, palch.c, whiteh.c,
                          inputnam.c, acte1.c
    snd/                  usd.c (the USD sequencer and the two OPN timers); snd.c (its place in
                          front of lrvne's write queue and mixer; AdvBIOS's boot register writes)
    game/                 profile.c (the profile's field table), run.c (ax_run: start-up, the
                          game or the viewer, reset, shutdown; ax_render_music)
  tools/                  what only this engine knows, on lrvne's tools: gamedata.py (inventory
                          hooks, the PCK archive, derive), mkpack.py (the pack's contents, the
                          game profiles), mes.py, gpc.py
  tests/                  conformance tests (C programs + Python comparers) and e2e
  dist/ReadMe.txt, Makefile (on lrvne/mk/lrvne.mk)
```

### Layering: the engine on lrvne

```
   game profile + data     build/adv98x.pak, made from the player's copy (tools/mkpack.py)
   -------------------------------------------------------------------------------------
   engine (source/engine)  the Adv98V interpreter, AdvBIOS's services, the GPC decoder, the
                           USD music driver, the plug-in modules, the game's run logic
   -------------------------------------------------------------------------------------
   lrvne (source/lrvne)    frame loop and input queue, screen (pages, DAC, overlays, present),
                           PC-98 keyboard and video mode, OPN cores + write queue + mixer,
                           glyph tables, pack, profile parser; backends null and SDL3 with the
                           command line, paths, autoplay and the control protocol
   -------------------------------------------------------------------------------------
   host
```

- The engine keeps only what is its own. There is no engine HAL, backend, pack reader, font
  loader or OPN core any more, and no adapter layer in between: engine code calls `lrv_*`
  directly on the instances embedded in `ax` (`lrv_sys_frame_wait(&ax.sys)`,
  `lrv_screen_mark(&ax.screen, ...)`). `source/lrvne/docs/architecture.md` describes the library,
  `docs/porting-an-engine.md` there the steps this migration followed.
- What stays engine code although it sits next to the library: AdvBIOS's 20 ms tick (a
  `LRV_HOOK_TICK` hook, `bios_frame_tick`), the mouse driver's 120 Hz interrupts (a pump hook),
  the BIOS key buffer and key-down bitmap made from neutral keys with `lrvne/pc98.h`, the
  palette buffer and brightness (the DAC itself is the screen's), the timing of every fade, the
  boot register writes of the sound chip.
- Nothing about a particular game is compiled in: the storage directory is the profile's `id`,
  the window title its `title`, the start script its `start` (as the original's start file
  names it), the plug-ins enabled its `modules`; languages are the tags of the pack's `langs`
  entry. The save names `FLAGn` and `NAME.DEF` remain because the interpreter and INPUTNAM
  hard-code them. INT F2h decides by the pack: a name it has is a file of the game, any other
  is a storage record.
- lrvne is public and knows no engine and no game; a fix or a missing feature found here goes
  into lrvne as a generic change with its own test, never into the engine as a workaround.

### Key design points

1. **The VM executes script bytes exactly as `NV.OVL` does** (`docs/re/interpreter.md`,
   `mes-format.md`): byte-level run loop, the same operand reader, the same block scanners
   (`skip_token` lengths), recursion for blocks, the unwind on `mes-jump` / `exit`, the name
   placeholder substitution, flag/variable token semantics including the off-by-one on plug-in flag
   results. No AST: the three original script defects and the scanner quirks then behave as on the
   PC-98 for free. All 51 opcodes are implemented, the 21 NOVA does not use included (they are small
   and the engine is generic).
2. **The script segment is modelled as real memory** (`mes_mem.c`): one 64 KB array with the
   original layout — flags at 0x0000, variables at 0x0080, script name at 0x009A, drive bytes
   0xFD/0xFE, script at 0x9000, sub-script buffer at 0xC006, proc slots (20 × 76 bytes, with the
   original overflow-into-next-slot behaviour). Saves are then byte-compatible with the original
   `FLAGn` files, and `load-mem` addresses keep their meaning.
3. **Plug-ins are native modules keyed by file name.** `load-mem "ACTE1.tcm" 256` records "module
   acte1 at 0x100"; `exec-mem 256 …` dispatches to the module registered at that address with the
   original argument block (count + words; string arguments as script offsets). A module has
   `init/exec/unload` and its own state. The game profile lists which modules a game enables; a
   `load-mem` of an unknown file loads the bytes into segment memory (data files) and an `exec-mem`
   of an address with no module is a logged error. Semantics from `docs/re/plugins.md`, including
   exact palette arithmetic and frame counts; ACTE1 gets its full 14-command set.
4. **The AdvBIOS layer is a C API with the original service semantics** (`docs/re/advbios.md` §4–8),
   not an interrupt emulation: text window in byte columns × pixel lines, 20-pixel line pitch,
   wrap-to-top, per-character delay/beep/skip, bold as OR-with-shifted, half-width glyphs for
   20h–7Eh / A0h–DFh and for the two-byte codes of JIS rows 29h–2Bh (what the English scripts use),
   GPC show opaque / colour-0 transparent with palette flags, brightness table
   `round(v·L/15)`, click maps (80×50 cells), invert rectangle, scroll, curtain, animation cells and
   lip-sync counters (unused by NOVA, implemented for the generic engine after the NOVA path works).
5. **Two time bases.** AdvBIOS waits count 20 ms ticks; fades, scrolls, the plug-ins and the picture
   decoder wait on VSYNC (56.42 Hz). The engine keeps the frame as its unit (the HAL's `frame_wait`,
   as in Xenon) and derives the 20 ms tick from accumulated frame time (a fixed-point accumulator:
   one frame = 17.724 ms), so both run from one clock and tests stay deterministic. The RNG is
   AdvBIOS's LCG, advanced as the original advances it (also once per wait-loop iteration).
6. **Mouse with absolute position.** `struct ax_input` gains pointer x/y (in 640×400 space) and
   button levels; the SDL3 backend maps window coordinates through the scaler. Menus hit-test the
   pointer, move it onto the highlighted item like the original (`INT 33h AX=4` → the engine's
   pointer position; the backend warps the host pointer where it can), click maps read it. The
   pointer is drawn by the engine with save-under at present time (`cursor.c`, AdvBIOS's default
   shape), so screenshots and the Amiga path need no host cursor.
7. **Sound: the verified model becomes C.** `usd_seq.c` is a port of `re-tools/usdmodel.py`
   (itself clean-room from `docs/re/usd-sequencer.md` and identical to the original on 5.7 M
   register writes). `opn_timers.c` is the timer scheduler lifted from Xenon's `pmd_seq.c`
   (`timer_reg` / `fire_events` / `pmd_advance` / `pmd_set_rate`), made generic with independent
   timer A (note tick) and timer B (9.52 ms effect tick) callbacks. `snd_api.c` keeps Xenon's render
   callback, write queue, push/pull paths and gain. Chip cores are copied unchanged.
8. **Files and disks.** The pack holds each picture once under its bare name (verified in
   `docs/re/disks.md`: every reference resolves, and the one name with two contents, `NV43A`, decodes
   to the same picture). `set-drive` keeps its state (it is part of the save) but never prompts.
   Saves (`FLAG0`–`FLAG9`) and `NAME.DEF` go through HAL storage records with the original 256-byte
   contents. A fresh storage has none of them. The `NAME.DEF` and `FLAG0`–`FLAG5` on the dumped
   disk A are the previous owner's state (name …, saves, unlocks), not shipped defaults: they
   are test inputs only and never packed. Without a `NAME.DEF` the name is the interpreter's
   built-in `＊＊＊` until name entry writes one (new game always runs name entry first).
9. **Languages.** A language is a script set in the pack (`ja`: the 119 Japanese scripts; `en`: the
   117 English ones over the Japanese remainder), selected with `--lang`. No run-time text patching
   is needed for these two. The built-in messages (save failed, nothing saved, load failed) and
   engine strings come from a small per-language string table. The hook a later translation needs
   (replacing text runs by key at pack time, as Xenon does) is designed in `mkpack.py` but not built
   now.
10. **The copy protection in `NV.INI` is not run**: the engine starts at the profile's start script
    (`RUN.MES`) with the state `NV.INI` would have set (documented in `interpreter.md` §7).
11. **Test automation from the start**: the HAL trace events (script, opcode, text, menu, wait,
    picture, sound, save) and the null backend + control protocol are carried over from Xenon and
    renamed, because the e2e tests are what proves the game is completable.

### History: what was copied from Xenon

The engine started from a copy of the Xenon port's platform layer, as planned below. That layer,
together with its siblings in the other engines, became lrvne and the copy was deleted
(2026-11-15); the table is kept for the record.

| Xenon | Here | Treatment |
|---|---|---|
| `hal/xe_hal.h` | `hal/ax_hal.h` | adapt: prefix, trace kinds for this engine, absolute mouse, drop voice |
| `engine/sys.c`, `sys.h`, `xe.h`, `xe_internal.h`, `version.h` | `engine/` | adapt: per-tick hook list instead of hard-wired blink/voice, remove AGS VM coupling, add the 20 ms tick |
| `gfx/planes.h`, `p2c.*`, `scale.*` | same | as is |
| `gfx/gfx.c` | `gfx/gfx.c` | keep init, pages, dirty tracking, clears, row copy, palette; drop GDT loaders and AGS effects; add brightness |
| `text/font.c`, `enc.c`, `overlay.c` | `text/` | font as is (run-time bold added: OR with itself shifted right, incl. the original's quirk); enc adapted; overlay kept for prompts/error boxes |
| `pack/pack.*` | `pack/` | adapt the type and language enums |
| `snd/opn_core.h`, `opn_lite.c`, `opn_lite_68k.s`, `opn_ymfm.cpp`, `snd_api.c` | `snd/` | cores as is; `snd_api.c` adapted to the USD sequencer |
| `snd/pmd_seq.c` | `snd/opn_timers.c` | only the ~80-line timer scheduler, generalised |
| `util/*` | `util/` | as is |
| `backends/sdl3`, `null`, `common`, `control` | same | adapt: prefix, absolute mouse, storage dir `adv98x/nova`, options |
| `Makefile`, `config/host.mk`, `config/sdl3.mk` | same | adapt names; Amiga configs later |
| `tools/mkpack.py`, `xpak.py`, `xfont.py`, `fonts/` | same | adapt pack contents; fonts as is (full JIS kanji 16×16, half-width 8×16 incl. katakana, Latin) |
| `tests/run.sh`, unit-test pattern, `tests/e2e` rig | same | adapt |
| `third_party/ymfm` | same | as is (BSD-3) |

Details the copy must take care of (found while mapping Xenon):

- The control protocol's "blocked" detection relies on the engine emitting a wait enter/leave trace
  event around every key wait and calling `frame_wait` while waiting; the new waits (key, timed,
  menu, click map, name entry) must all do so. The protocol and `autoplay` gain an absolute
  `mouse X Y` command next to the relative one.
- `tests/run.sh` stops at the game-data gate before the data-free tests; here the data-free tests
  run first, and data-dependent ones are skipped with a note when the import is missing.
- Fonts: `jiskan16.bdf` (JIS X 0208, 16×16) and Sony `8x16rk.bdf` (ASCII + half-width katakana) are
  exactly what AdvBIOS's kanji-ROM lookups need; the two-byte half-width codes (JIS rows 29h/2Ah)
  map onto the 8×16 font, row 2Bh's blank onto a space. Bold moves from pack time to run time.
- Names to change everywhere: `xenon` → `adv98x` (binary, storage dir `adv98x/nova`, window title
  from the profile), `xe_`/`XE_` → `ax_`/`AX_`, e2e package `xe2e` → `axe2e`. Format magics
  (`XPAK`, `XFNT`) stay.

Not copied: `gdt.c`, `adt.c`, `blink.c`, `print.c`, `menu.c`, `game/*`, `vm/*`, `voice/*`,
`pmd_seq.c` beyond the scheduler, `lzss.*`, the Amiga backend (later).

Every copied or new source file gets an SPDX `GPL-3.0-or-later` header; `LICENSE` (GPL-3) at the
top; `opn_lite_68k.s` keeps its BSD-2 header, `opn_lite.c` its ymfm attribution.

## Milestones

Each milestone ends with its tests passing and a commit; the game is runnable from M2 on.

**M0 — Skeleton.** ✔ Copy the platform layer, rename to `ax_`, GPL-3 headers and `LICENSE`, top-level
`README.md`, `docs/game-data.md`. `Makefile` targets `data` (import + derive), `pack`, `test`,
`clean`, `data-clean`, `distclean`; `TARGET=host|sdl3`. `mkpack.py` builds `build/nova.pak` from
`resources/original/`: scripts per language, pictures (stored as original GPC, deduplicated by
name), songs, click maps, default name, fonts, profile. The engine opens the pack and a window and
shows a decoded picture. *Check:* `make TARGET=sdl3 && build/sdl3/adv98x --pak build/nova.pak`.

**M1 — Pictures, palette, text services.** ✔ `gpc.c` (C port of the verified decoder: interleave,
XOR carry-over across chains, opaque/masked put, position override, palette flags), brightness and
palette services, `bios_text.c` in full, bold, half-width paths. *Tests:* `test_gpc` compares all
103 distinct GPC files with `source/tools/gpc.py` output; `test_text` compares rendered text cells
against expected plane patterns (wrap, line pitch, bold, the two half-width code paths).

**M2 — The VM, silent.** ✔ `mes_mem.c`, `mes_vm.c` with every opcode, waits and delays with skip,
fades, `mes-jump`, procs, `if`/`when`/branches, `seg-call`, sub-scripts, name substitution, and the
modules NOVA calls around every line (`chgfonth`, `acte1` INIT/GET/PUT/FREE). *Tests:* `test_mes`
(unit: operand reader, scanners against `mes.py` on all 236 scripts, token semantics); null-backend
run from `RUN.MES` to the title menu and through the opening with the trace compared to a script
walk. *Check:* play the Japanese and English openings in SDL3.

**M3 — Menus, mouse, maps, saves.** ✔ `mes_menu.c` (layout, highlight, keys with the D3 steps, mouse
hover/click/cancel, `menu2` verb/noun with its cycle-counter reset), absolute mouse and `cursor.c`,
click maps (`input`), `flag-save` / `flag-load` (full and merge) / `save-check`, the built-in
messages, `name-load`, storage. *Tests:* menu unit tests (item rectangles, key navigation, hidden
items keep their index); save round-trip incl. loading an original `FLAG0` from the dump (allowed as
a test input when present, never packed); e2e: new game → first map → save → quit → continue.

**M4 — Music.** ✔ `opn_timers.c`, `usd_seq.c`, `bios_snd.c`, `snd_api.c`, the `sound` opcode with the
original semantics (load ≠ play, fixed-rate fades that do not stop the song, FM volume only at
note-on, restart rules). *Tests:* `test_usd` compares the C sequencer's register stream with the
reference recordings of `re-tools/usdemu.py` for all 28 files in the play / fade / stop / chained
scenarios (the same check `usdmodel.py --check` passes); a render smoke test per chip core.

**M5 — Remaining modules and services.** `inputnam` (full key handling incl. kana-lock input and
dakuten, the unseen default name, the exact `NAME.DEF` bytes), `palch`, `whiteh` (exact per-step
arithmetic and frame counts), ACTE1's remaining commands, scroll, curtain, animation cells and
lip-sync, beeper (`F1h 04–06`, per-character beep), quit prompt. *Tests:* palette sequences against
the emulated plug-in runs (`re-tools/tcmtool.py run`), `NAME.DEF` bytes for scripted key input.

**M6 — End to end.** ✔ e2e scenarios played headless on the null backend for both languages: 1st
story to its ending, the three 2nd-story endings (R217 route, L ≥ 5, else), the 3rd story, the
unlock chain (a fresh storage shows only "start"; after `END` writes `FLAG3`/`FLAG4`/`FLAG5` the
menu entries appear), Sound and Graphic modes; golden screen hashes at fixed points; an SDL3
offscreen presentation run. Routes come from `docs/re/script-catalog.md`.

**M7 — Polish for a first release.** ✔ (Starting point: the SDL3 build already has `--lang`,
`--scale`, `--fullscreen`, `--window`, `--storage`, `--view`, F11/F12 and Shift+Esc; no volume
options, no `make dist`; END's endless loop lets a frame pass every 1000 rounds, M6 notes.) Options (`--lang`, `--scale`, `--fullscreen`, volumes), the
engine's own end-of-game behaviour where the original loops forever (kept as original; a system-level
quit/return-to-title key is added outside the script, as in Xenon), README, `make dist`. Then, as
separate later efforts: CD-DA option (track table `resources/music/cd-tracks.tsv` exists), Amiga
family backends, Polish translation tooling, public-release cleanup.

## Open items (after M7)

Where a new session picks up; nothing here blocks playing the game.

- **The user's play-test** of the SDL3 build (text speed, fades, music balance, the feel of
  the mouse and the menus) — not done yet; findings become engine fixes with a `check_vm.py`
  scenario where the original can be compared.
- **Decisions left to the user:** the reset key (Ctrl+Shift+R was chosen because every other key
  is a PC-98 key the game may read); whether the player's archive should carry a pack-building
  kit (now it follows Xenon: no pack, the player builds it from the source tree); bundling SDL3
  into a macOS release (the executable links it dynamically).
- **M5 leftovers, unused by NOVA:** animation cells and lip-sync (C1–C5, INT F3h AH=08h–0Fh),
  the beeper's sound, the STOP-key quit prompt, ACTE1's page commands on two pages.
- **Later efforts (separate from this plan):** CD-DA option (`resources/music/cd-tracks.tsv`),
  the Amiga family backends, Polish translation tooling, the pseudonymous public release.

## Verification

- `cd source && make data SRC="<your copies>"` then `make pack` — import, inventory check,
  pack build (fails loudly on anything missing).
- `make TARGET=host test` — all unit and conformance tests above; every one compares against data
  produced from the original code or the verified Python tools, not against the engine itself.
- `make TARGET=host e2e` — headless play of every route in both languages, compared with the
  original interpreter under emulation (about 15 minutes).
- `make TARGET=sdl3 dist` — the player's archive; unpack it, put `adv98x.pak` next to `adv98x`,
  run it (`--version`, `--help`).
- `make TARGET=sdl3 && ../build/sdl3/adv98x --pak ../build/adv98x.pak [--lang en]` — manual play;
  the user's eyes and ears are the final check on feel (text speed, fades, music balance), with
  DOSBox-X / NP2 runs of the original as the comparison when a doubt needs settling.

## Housekeeping before M0 (done 2026-11-14)

- The corrections of `docs/re/usd-driver.md` §11 are merged into `docs/re/advbios.md`, the sound
  routine names into `docs/re/listing/advbios-names.tsv`.
- `gamedata.py derive` reproduces everything derived (unpacked executables, script exports, PNGs,
  plug-in listings, VGM reference recordings); the dump owner's `FLAG*` / `NAME.DEF` are marked in
  `resources/inventory.tsv` as test inputs that must never be packed.

## Implementation notes

Decisions taken while implementing, where the work refined or departed from the text above.

**M0 (2026-11-14)**

- *Input model.* `struct ax_input` is the PC-98 keyboard, not Xenon's command bits: key presses as
  (scan code, character code) pairs, as the BIOS key buffer holds them, plus the key-down bitmap
  (0000:052A) that AdvBIOS's keyboard mouse emulation and the STOP check read. Menus test scan
  codes, INPUTNAM tests character codes (docs/re/interpreter.md §4, plugins.md §5.3), so the
  engine keeps the original's view and the backends translate host keys. The mouse is absolute
  (`mouse_x/y` in 640×400 space, buttons as levels plus press edges); `mouse_warp` is optional.
  The control protocol has `press` (named keys, clicks), `key SCAN CHR`, `hold`, `mouse X Y`;
  autoplay's ranges are `ctrl:`, `shift:`, `button_r:`.
- *Time.* The 20 ms tick is derived exactly: every frame adds 5000 to an accumulator and every
  5642 in it is a tick (50 / 56.42). Frame and tick hooks replace Xenon's hard-wired blink/voice.
- *Trace kinds* are this engine's: script, op, text, menu, menu_sel, wait (key, ticks, menu,
  click, name, prompt), picture, palette, sound, save, load, module, flag, error, quit.
- *Storage records* keep the original file names (`FLAG0`, `NAME.DEF`) as file names in the
  storage directory, so PC-98 saves can be dropped in.
- *Not copied now:* `p2c`/`scale` (only the Amiga backend uses them; they come with it), the
  sound files (with M4, together with the sequencer they are adapted to), `font.c`/`enc.c`/
  `overlay.c` (with M1's text services, where they are adapted). `ptest` (the synthetic
  presentation sequence) is kept for the null backend's `--present-test`.
- *Pack.* The "default name" item of M0 is dropped: INPUTNAM's default comes from the script's
  argument (plugins.md §5), nothing to pack. NV.INI is not packed. The English script set is
  completed at pack time with the Japanese scripts it does not replace (`RUN`), so a lookup never
  falls back across languages. The profile is a `profile` meta entry; `mkpack.py --game nova`
  holds NOVA's values (title, start script, modules, the `NV43A` disk choice).
- *Picture viewer.* `--view [PICTURE]` browses the pack's pictures as AdvBIOS draws them (opaque
  at the file's position, its palette at brightness 15) — the M0 check, and a tool afterwards.
  The C GPC decoder (`gfx/gpc.c`) is already the full port of `gpc.py`; M1 adds its test over
  all files and the palette-flag/position semantics of the service.
- *Tests* so far: `check_pack.py` (the C reader against `xpak.py`, every packed game file
  against the inventory md5s, nothing "never packed" in the pack) and the presentation smoke
  run.

**M1 (2026-11-14)**

- *Reference for the text and palette services: AdvBIOS itself.* `re-tools/advbios_emu.py` runs
  NV.OV1's INT F1h/F3h/F6h handlers under unicorn (loaded at 1000h with its relocations, entered
  directly, DGROUP as initialised), with the GRCG's RMW/TDW writes, the DAC ports and the kanji
  ROM modelled. `check_text.py` and `check_palette.py` run one scenario through it and through
  the engine and compare the planes, the cursor, the DAC and the palette buffer at every snap.
  This replaces the "expected plane patterns" of the plan with the original code; mutations of
  the bold quirk, line pitch, wrap rule, SJIS conversion and RMW write are all caught.
- *The kanji ROM model* (`text/font.c` `font_rom_glyph`, the same rule in the harness): JIS rows
  29h/2Ah are half-width (29xx = byte xx, 2Axx = byte xx + 80h of the 8×16 font), row 2Bh is
  half-width and blank, everything else 16×16 from `jiskan16`; a missing glyph is blank. The
  glyph layout is the X11 fonts' (column 0 used), not the ROM's; bold is applied at run time
  exactly as `MakeCharBold` does.
- *Scope.* INT F6h AH=01h–0Eh, 12h, 13h and INT F3h AH=01h, 10h–16h, FFh are done; scrolling
  (AH=10h/11h) and the curtain (AH=0Fh) stay in M5 as planned. Character delays and beeps go
  through `bios_delay` (INT F1h AH=09h semantics: SHIFT or the right button skips); the beeper
  sound itself is M5.
- *Hardware details kept:* 16-bit VRAM offsets (y·80 + x) and 16-bit counts in fills and
  inversion, writes past the 32000 visible bytes dropped (the original writes off-screen VRAM
  there); the brightness service waits one frame before programming (its VSYNC wait), AH=15h
  programs one colour at once with brightness row CL.
- `check_gpc.py` compares all 103 distinct GPC files with `gpc.py` and the draw semantics
  (position override, masked mode, rows continuing past column 79, clipping) on a background.

**M2 (2026-11-14)**

- *Source.* The VM was written from NV.OVL's handlers themselves (the listing `gamedata.py derive`
  can make locally: `re-tools/dis16.py` on `resources/derived/exe/NV.OVL` with the names of
  `docs/re/listing/nvovl-names.tsv`), every function naming its original address. One file,
  `vm/mes_vm.c` (run loop, operands, scanners, all 51 opcodes), plus `vm/mes_menu.c`; the memory
  model lives in `ax.mem` with the layout of `vm/mes.h` (no separate `mes_mem.c`).
- *Unwinding.* The original's SP resets are `longjmp`s: mes-jump, exit and a quit go to the top
  level (`vm_run_game`), exit inside `mes-call` to the sub-script's level. Ending the main script
  ends the game, as the original returns to DOS (the engine then quits; M7 added the reset
  button, which unwinds the same way and starts the game again).
- *Already in, though planned for M3:* menu and menu2 with mouse hover/click/cancel and the key
  steps, the click maps (`input`), saves (`flag-save`, `flag-load` full and merge, `save-check`),
  `name-load`, the built-in messages, the AdvBIOS mouse driver with its keyboard emulation, the
  INT F1h waits. M3 still owes the drawn pointer (`cursor.c`), its tests and the e2e.
- *Built-in messages.* The pack's `messages` entry per language: the Japanese fragments are taken
  from the user's NV.OVL at pack time (`mkpack.py`, via `re-tools/exeunpack.py`), the English ones
  are ours. Japanese ones sit at their original addresses; longer ones above the interpreter's
  image (0xEE80) in the model.
- *Script names* keep the original form `\MES\NAME.MES` at 0x9A (the start is `\MES\RUN.MES`,
  as NV.INI would leave it), so saves are byte-compatible.
- *Stubs until their milestone:* sound calls are traced only (M4); PALCH, WHITEH, INPUTNAM,
  ACTE1's SHOW/ACCE/COPY/MOVE/LOAD, scrolling, the curtain and the animation-cell opcodes log a
  warning (M5). The STOP-key quit prompt is M5; the host's window close quits at once.
- *Tests.* `check_mes.py`: skip_token, get_number and skip_block on every byte offset of the 236
  scripts and NV.INI against `mes.py` (1.13 M results; numbers modulo 2^16 as in AX).
  `check_run.py`: headless play from RUN.MES answering every wait with Return, 40 000 frames per
  language (reaches the 1st story's map loop S012/S013): every executed opcode starts an opcode
  node of `mes.py`'s parse, every script change is a mes-jump of the previous script, every
  picture shown is named by the current script, no error events.
- *Doc fix.* `save-check` counts a save only when its last byte is exactly FFh; `flag-load`
  accepts any non-zero byte (interpreter.md §5.1 corrected).

**M3 (2026-11-14)**

- *The reference is the original interpreter.* `re-tools/nvovl_emu.py` runs NV.OVL on AdvBIOS's
  own code (the harness of M1) with the copy-protection patch applied (`int F3h` at 0xEA84) and
  AdvBIOS's screen initialisation; files, the keyboard queue, clicks (held in the driver's button
  variable until the click-map wait returns), the plug-ins' DOS memory and the timer/mouse
  counters are modelled. `tests/check_vm.py` runs scenarios through it and through the whole
  engine (`tests/test_vm.c`) and compares the interpreter's memory, the four planes, the frame
  with the pointer, the DAC, the saves written and the sound calls. This replaces the planned
  hand-written menu unit tests: menus (keys, menu-step columns, menu2's empty noun list), click
  maps, `flag-load` of an original save (the dump's FLAG0, a test input), `flag-save` (byte-equal
  FLAG1), the Sound and Graphic modes and English are covered.
- *Key timing in the runners.* A key is offered only while the game waits for one (the harness:
  after three empty polls of the BIOS buffer; the engine runner: during a wait's trace window).
  The menu's wait-leave trace moved to the moment of the choice: restoring the mouse emulation
  afterwards waits frames, and a key offered then was dropped by the next menu's flush.
- *The pointer* (`gfx/cursor.c`): AdvBIOS's default shape, extracted from the user's NV.OV1 at
  pack time (01AB:09D8), drawn only into the presented frame with save-under; equal to what the
  driver draws into VRAM. The SDL3 backend hides the host cursor.
- *Owed to M5:* the new-game path (name entry through INPUTNAM); scenarios `story2`/`story3` are
  ready in `check_vm.py` (`AFTER_M5`) and run once INPUTNAM exists.

**M5 (2026-11-14, mostly)**

- *Done, each checked against the original code:* INPUTNAM (new-game, 2nd and 3rd story starts in
  `check_vm.py`: NAME.DEF and screen identical, with typed kana, dakuten, handakuten and
  backspace), PALCH and WHITEH (synthetic `check_vm.py` scenarios: every palette write identical
  to the real plug-ins'), ACTE1's remaining commands (synthetic scenario, page 0 only), the
  text-layer curtain (text VRAM identical after cover/uncover), scrolling (`check_text.py`
  against AdvBIOS: window and rectangle, four directions).
- *Synthetic scenarios.* `check_vm.py` assembles small test scripts (`op()`, `num()`) that run
  in place of RUN.MES on both sides; the harness now delivers the VSYNC interrupt the plug-ins
  hook (between instruction slices, as `tcmtool.py` does) and provides DOS vector get/set.
- *Text layer.* The HAL has no text plane: covered curtain cells are drawn into the presented
  frame in the palette entry nearest to the text colour — exact for NOVA's one use (white over an
  all-white palette), an approximation in general. Restart's uncover of the whole text layer
  (F6h AX=0FFFh) is done too, with its 31 frames.
- *Kana input.* The SDL3 backend has a KANA lock (the JIS keyboard's Kana key or Scroll Lock)
  giving the JIS kana layout's half-width kana, which INPUTNAM takes as hiragana.
- *Left for later (not used by NOVA):* animation cells and lip-sync (C1–C5, INT F3h AH=08h–0Fh),
  the beeper's sound (character beep, pitch), the STOP-key quit prompt (the host's window close
  quits at once), ACTE1 page commands checked on two pages (the harness has one VRAM page).

**M4 (2026-11-14)**

- *The sequencer* `snd/usd.c` is a function-by-function C port of `re-tools/usdmodel.py`,
  including the model's two YM2203 timers (so Xenon's `pmd_seq.c` timer scheduler was not
  needed: the verified model already is the timer). `check_usd.py` compares it with the model on
  151 scenarios (play, fades, chained songs, timer phases, 400 synthetic songs) and with the
  original driver's 28 recordings: 7.36 M register writes, identical. (Written by a delegated
  agent against a fixed interface; `gamedata.py derive` now also writes the recordings' `.tsv`
  logs the check reads.)
- *Output* (`snd/snd.c`): the sequencer runs in sample time from the backend's audio thread (pull
  mode) or the frame (push); its writes are stamped with OPN clocks, mapped to output samples
  with exact 64-bit arithmetic and applied at least one chip sample apart. The core is ymfm (Xenon's
  wrapper, 55 467 Hz, the host resamples); `opn_lite` is in the tree for the Amiga later.
  AdvBIOS's start-up register writes go to the core at init (the model starts after them).
- *INT F4h* (`bios/bios_snd.c`) maps the services onto the model; `sound "file"` = stop + load,
  `sound 1` = play, fades at the driver's fixed rate.
- `adv98x --render-wav OUT --song NAME` (null backend) plays a song through the same path; the
  suite renders 4 s of NV01 as a smoke test. The balance and feel are for the user's ears.

**M6 (2026-11-14)**

- `tests/e2e/explore.py` plays headless with an exploring player: Return at waits, menus rotated
  item by item each time the same menu returns (→ steps wrap), click-map regions rotated
  (`load` trace events name the click map), name entry with the default. That opens the
  flag-gated hubs without a hand-written route. `tests/e2e/stories.sh` plays a fresh install
  through the 1st, 2nd and 3rd story in turn and checks that FLAG3, FLAG4 and FLAG5 are written
  — both languages, about 40 000 frames per story, 1.4 s in all.
- Found by it: END.MES ends in `｛＠｝`, a loop without any wait; the original spins the CPU
  forever. The engine keeps the loop but lets a frame pass every 1000 empty rounds so the window
  lives and the player can quit.
- *Routes against the original* (`check_vm.py` ROUTES, `make TARGET=host e2e`): the 1st story,
  the three 2nd-story endings by design (2B: `2MAL` item 0, R217; 2A: every scored choice, L = 8;
  2C: none, L = 0; `explore.py --choose SCRIPT=N`) and the 3rd story, in both languages. The
  exploring player's input on the engine is recorded (`--record`) and replayed from RUN.MES
  through the engine and through NV.OVL under emulation until the unlock file is written (END
  loops for ever after it: `TEST_VM_STOP_SAVE` / `stop_save=`); memory, screen with the ending
  card, DAC, text VRAM, every save written, every sound call and plug-in palette write are
  identical. The route must pass the script that sets the ending flag. About 5-12 CPU minutes per
  route under emulation, run in parallel (ten routes: about 15 minutes on eight cores), so not
  in the default `make test`.
- *Golden screens* became these comparisons with the original at the end of each route (and at
  every `check_vm.py` scenario) rather than stored hashes of the engine's own frames, which the
  test rule excludes.
- *Sound and Graphic modes* (`check_vm.py` `sound_all`, `graphic_all`): all 16 songs and 11
  effects chosen in turn (all 27 `.USO` loads), the 45 CG screens by key and then automatically;
  identical to the original.
- *SDL3 presentation* (`tests/e2e/present.py`, in `make test` when the SDL3 build exists): the
  offscreen SDL3 backend in control mode, five window size / scale mode runs, four frames each;
  the renderer's readback against the engine's frame (destination rectangle per scale mode,
  black border, exact palette colours ×17 with nearest filtering, flat areas with linear).

**M7 (2026-11-14)**

- *The end of the game stays as the original*: END.MES loops for ever after writing the unlock
  file. The way out is a **reset button** (`AX_EV_RESET`; SDL3: Ctrl+Shift+R, the control
  protocol and autoplay: `reset`), the engine's stand-in for switching the PC-98 off and
  starting the game again. The game unwinds as for a quit (every wait already polls for it),
  then `run.c` puts the machine back into its start-up state — sound (`snd_reset`: the chip
  reset with AdvBIOS's start-up writes, a fresh sequencer, the output kept open), both pages
  and the palette (`gfx_reset`), the text layer, the pointer's save-under, AdvBIOS's DGROUP
  (`bios_init`), the interpreter's memory, the plug-ins (`mod_init` now resets every module) —
  and runs the start script again; the storage is kept. A reset is available everywhere, not
  only at the end; in the viewer it goes back to the first picture. Trace event `reset`.
- *Checked against the original:* `check_vm.py` `reset_sound` (a song playing in Sound mode),
  `reset_game` (at a map's click wait), `reset_name` (in name entry, before NAME.DEF is
  written): the engine runs the keys before RESET, is reset, runs the keys after it; the
  original runs only the keys after it from a fresh start; memory, screen, DAC, text VRAM,
  saves, sound and palette calls (logged from the reset on) are identical. Mutations show
  `bios_init` is needed; dropping `gfx_reset` or `tl_init` is invisible for NOVA (RUN.MES
  redraws everything, the start uncovers the whole text layer) — they stay, so that a reset is
  the start-up state for any game.
- `stories.sh` now plays the three stories **in one run** (`explore.py --chain
  FLAG3:0,FLAG4:1,FLAG5:2`): after each ending's unlock file it presses reset, and the next
  story must be on the title menu.
- *Volume:* `--volume 0..100` (SDL3 and null backends) scales the FM output (music and effects
  are one chip) by v·256/100 / 256 in `snd.c`; the render check in `run.sh` verifies every
  sample of a 4 s render at 30 against the full-volume one.
- *Options:* `--help` (all options and keys), `--version` (`engine/version.h`, 0.1.0).
- *Release archives:* `make TARGET=sdl3 dist` → `adv98x-<version>-sdl3-<os>-<arch>.tar.gz`
  with the stripped executable, the player's ReadMe (`backends/sdl3/ReadMe.txt`), `LICENSE`
  and ymfm's licence; no pack (Xenon's model: the player builds it from their copy); no user
  names in the tar headers. `make dist-src` is `git archive` of HEAD. The executable links SDL3
  dynamically (the player installs it); bundling SDL3 for macOS is left for the public
  release.
- *Verified at the end of M7:* `make TARGET=host test` and `make TARGET=host e2e` (all ten
  routes, both languages, identical to the original) pass.

**lrvne (2026-11-15)**

The engine was moved onto lrvne following its `docs/porting-an-engine.md`; "Layering" above is
the result. What was decided on the way:

- *Recorded before, compared after:* the present test, frame hashes of autoplay runs (both
  languages: title, text, menus, name entry, Sound and Graphic mode, a load), control sessions
  event for event with the hash of every changed frame (the same plus a save, a load after a
  reset, held Shift), and songs rendered with both OPN cores. All identical with one exception,
  which is the input model and not the engine: lrvne shows a key press as down in the key-down
  bitmap for the poll that delivers it (on the machine a press lasts many polls), where the old
  test backends delivered a press without a level. So Return pressed while a click map waits
  is, with the keyboard mouse emulation on, a left click, as on the PC-98. The old build fed
  press and level together produces the same frames and events as the new one.
- *Keyboard.* The backends deliver neutral keys; `bios_sys.c` turns the presses into the BIOS
  key buffer (scan code and character, `lrv_pc98_keypress`) and answers the key-down bitmap
  from `lrv_pc98_keymap`. The control protocol's `key SCAN CHR` is gone with the old backends:
  a test presses the host key that gives the character (`hold kana 1` for the kana layout);
  `test_vm` does that translation for the (scan, character) pairs of `check_vm.py`.
- *Pack.* lrvne's format 2. A file of the game is an entry under its own name (`RUN.MES`,
  `NV01.GPC`) with one of the engine's types (`AX_PT_*`, from `LRV_PT_ENGINE`); INT F2h asks
  the pack by name and takes every other name for a storage record, so the engine has no list
  of save names and no table of extensions. The `lang` and `meta` entries nothing read are
  gone. Languages are tags; `--lang` with a tag the pack lacks is an error.
- *Profile.* `id`, `title`, `lang`, `modules` (lrvne's base keys) and `start`. `start` is the
  full name the start file gives (`\MES\RUN.MES`): it ends up in the interpreter's memory and
  in saves, so it is the game's, not a name the engine builds. `modules` lists the plug-ins by
  their files' base names (`ACTE1`), matched exactly. A pack without a profile, an id or a
  start script is refused.
- *Game-specific items found and where they went:* storage directory name → profile `id`;
  window title → `title` (was already); start script path → `start`; pack file name
  `nova.pak` → `adv98x.pak`, found by the program's name; default song of `--render-wav`
  (`CATS`) → none, `--song` is required; `FLAGn` / `NAME.DEF` in INT F2h → the pack decides;
  compiled language ids ja/en/pl → the pack's `langs`; the two-disk picture rule, the place of
  the built-in messages and the English messages were and stay in `mkpack.py`'s `PROFILES`.
  Kept in the engine because the original code has them: `FLAG%d` (flag-save / flag-load),
  `NAME.DEF` (name-load, INPUTNAM), the plug-ins' names.
- *Presentation test.* `--present-test` runs in the video mode the engine opens, after the
  pack (the window title is the game's): it moved from the data-free tests to the ones that
  need the pack.
- *Tools.* `gamedata.py` is lrvne's inventory framework with hooks; it now reads 7z/rar/lzh
  archives and nested containers, and takes the Windows release's `EVE.PCK` out of the rar:
  the PCK reader is registered as a container format of the game's own
  (`Hooks(containers={'.pck': read_pck})`, a hook added to lrvne for this). The blank
  end-of-directory entry of the PCK is no longer an inventory row.
- *Added to lrvne on the way:* readers for archive formats of a game's own in its `source`
  and `inventory` tools (above).
- *Fixed in lrvne on the way:* the SDL3 backend drew the fit-mode picture into a rectangle
  with fractional edges, which lit a border column under the software renderer
  (`tests/e2e/present.py` failed at 1000x700 before the migration too); the rectangle is now
  on whole pixels.
- *`make dist-src`* adds the submodule's tree to the archive (`git archive` leaves it out).

