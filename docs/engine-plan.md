# Adv98X — a new engine for Adv98V 1.70.54 games (first game: NOVA)

The implementation plan, approved 2026-11-14. Status: research (phase 1) complete, housekeeping
before M0 done, **M0 not started**. Update the status line and tick milestones here as they land.

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
- Start from a **copy** of Xenon's platform layer (`xenon/source`); a shared layer may be
  considered later.
- Licence **GPL-3** (as the Xenon port's files that were copied are). Bundled third-party code keeps its own licences (ymfm BSD-3, fonts).
- Engine name **Adv98X**: binary `adv98x`, C prefix `ax_`. The repository and the game profile stay
  `nova`; the pack is `nova.pak`.
- FM music first, CD-DA optional later. Japanese and English first; Polish is a later, separate
  effort and the player-name question is left open (the engine must not preclude either answer).
- A fresh install starts locked (no `FLAG3`–`FLAG5`), like a new copy of the game.
- No game data in the repository, ever: everything is built from the user's originals by tools.

## Architecture

```
source/
  hal/ax_hal.h            platform interface (from xenon hal/xe_hal.h)
  engine/
    ax.h, ax_internal.h   public entry (ax_run, ax_audio_render), the one state struct
    sys.c                 the single blocking point: ticks, waits, input queue, per-tick hooks
    gfx/                  planes.h p2c scale (as is); gfx.c (pages, dirty, palette + brightness);
                          gpc.c (GPC decoder); cursor.c (mouse pointer, save-under)
    text/                 font.c enc.c (as is / adapted); textwin.c (AdvBIOS text services)
    bios/                 the AdvBIOS service layer the VM and the modules call:
                          bios_sys.c (waits, RNG, quit, click maps), bios_file.c (files, drives,
                          saves), bios_gfx.c (picture show, palette, brightness, animation cells),
                          bios_text.c (window, cursor, char/string draw, fill, invert, scroll,
                          curtain), bios_snd.c (INT F4h functions)
    vm/                   mes_vm.c (the interpreter), mes_menu.c (menu / menu2), mes_mem.c (the
                          64 KB script segment: flags, variables, script buffers, proc slots)
    mod/                  native plug-in modules + registry (mod.h): chgfonth.c, palch.c, whiteh.c,
                          inputnam.c, acte1.c
    snd/                  opn_core.h opn_lite.c opn_lite_68k.s opn_ymfm.cpp (as is);
                          opn_timers.c (timer A/B scheduler lifted from xenon pmd_seq.c);
                          usd_seq.c (the USD sequencer); snd_api.c (render path, adapted)
    game/                 profile.c (game profile from the pack), run.c (ax_run: init, start
                          script, shutdown)
    pack/                 pack.c (XPAK reader, adapted type/lang enums)
    util/                 endian.h sjis.h utf8.h (as is)
  backends/               sdl3/, null/, common/, control/ (from xenon; amiga later)
  tools/                  gamedata.py diskimg.py mes.py gpc.py (exist); mkpack.py xpak.py xfont.py
                          (from xenon, adapted); usoinfo-based checks stay in re-tools
  tests/                  unit tests + e2e (rig from xenon)
  fonts/, third_party/ymfm, config/*.mk, Makefile
```

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

### What is copied from Xenon (`xenon/source`)

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

**M0 — Skeleton.** Copy the platform layer, rename to `ax_`, GPL-3 headers and `LICENSE`, top-level
`README.md`, `docs/game-data.md`. `Makefile` targets `data` (import + derive), `pack`, `test`,
`clean`, `data-clean`, `distclean`; `TARGET=host|sdl3`. `mkpack.py` builds `build/nova.pak` from
`resources/original/`: scripts per language, pictures (stored as original GPC, deduplicated by
name), songs, click maps, default name, fonts, profile. The engine opens the pack and a window and
shows a decoded picture. *Check:* `make TARGET=sdl3 && build/sdl3/adv98x --pak build/nova.pak`.

**M1 — Pictures, palette, text services.** `gpc.c` (C port of the verified decoder: interleave,
XOR carry-over across chains, opaque/masked put, position override, palette flags), brightness and
palette services, `bios_text.c` in full, bold, half-width paths. *Tests:* `test_gpc` compares all
103 distinct GPC files with `source/tools/gpc.py` output; `test_text` compares rendered text cells
against expected plane patterns (wrap, line pitch, bold, the two half-width code paths).

**M2 — The VM, silent.** `mes_mem.c`, `mes_vm.c` with every opcode, waits and delays with skip,
fades, `mes-jump`, procs, `if`/`when`/branches, `seg-call`, sub-scripts, name substitution, and the
modules NOVA calls around every line (`chgfonth`, `acte1` INIT/GET/PUT/FREE). *Tests:* `test_mes`
(unit: operand reader, scanners against `mes.py` on all 236 scripts, token semantics); null-backend
run from `RUN.MES` to the title menu and through the opening with the trace compared to a script
walk. *Check:* play the Japanese and English openings in SDL3.

**M3 — Menus, mouse, maps, saves.** `mes_menu.c` (layout, highlight, keys with the D3 steps, mouse
hover/click/cancel, `menu2` verb/noun with its cycle-counter reset), absolute mouse and `cursor.c`,
click maps (`input`), `flag-save` / `flag-load` (full and merge) / `save-check`, the built-in
messages, `name-load`, storage. *Tests:* menu unit tests (item rectangles, key navigation, hidden
items keep their index); save round-trip incl. loading an original `FLAG0` from the dump (allowed as
a test input when present, never packed); e2e: new game → first map → save → quit → continue.

**M4 — Music.** `opn_timers.c`, `usd_seq.c`, `bios_snd.c`, `snd_api.c`, the `sound` opcode with the
original semantics (load ≠ play, fixed-rate fades that do not stop the song, FM volume only at
note-on, restart rules). *Tests:* `test_usd` compares the C sequencer's register stream with the
reference recordings of `re-tools/usdemu.py` for all 28 files in the play / fade / stop / chained
scenarios (the same check `usdmodel.py --check` passes); a render smoke test per chip core.

**M5 — Remaining modules and services.** `inputnam` (full key handling incl. kana-lock input and
dakuten, the unseen default name, the exact `NAME.DEF` bytes), `palch`, `whiteh` (exact per-step
arithmetic and frame counts), ACTE1's remaining commands, scroll, curtain, animation cells and
lip-sync, beeper (`F1h 04–06`, per-character beep), quit prompt. *Tests:* palette sequences against
the emulated plug-in runs (`re-tools/tcmtool.py run`), `NAME.DEF` bytes for scripted key input.

**M6 — End to end.** e2e scenarios played headless on the null backend for both languages: 1st
story to its ending, the three 2nd-story endings (R217 route, L ≥ 5, else), the 3rd story, the
unlock chain (a fresh storage shows only "start"; after `END` writes `FLAG3`/`FLAG4`/`FLAG5` the
menu entries appear), Sound and Graphic modes; golden screen hashes at fixed points; an SDL3
offscreen presentation run. Routes come from `docs/re/script-catalog.md`.

**M7 — Polish for a first release.** Options (`--lang`, `--scale`, `--fullscreen`, volumes), the
engine's own end-of-game behaviour where the original loops forever (kept as original; a system-level
quit/return-to-title key is added outside the script, as in Xenon), README, `make dist`. Then, as
separate later efforts: CD-DA option (track table `resources/music/cd-tracks.tsv` exists), Amiga
family backends, Polish translation tooling, public-release cleanup.

## Verification

- `cd source && make data SRC=<your copies>` then `make pack` — import, inventory check,
  pack build (fails loudly on anything missing).
- `make TARGET=host test` — all unit and conformance tests above; every one compares against data
  produced from the original code or the verified Python tools, not against the engine itself.
- `make TARGET=host e2e` — headless play of every route in both languages with golden hashes.
- `make TARGET=sdl3 && ../build/sdl3/adv98x --pak ../build/nova.pak [--lang en]` — manual play;
  the user's eyes and ears are the final check on feel (text speed, fades, music balance), with
  DOSBox-X / NP2 runs of the original as the comparison when a doubt needs settling.

## Housekeeping before M0 (done 2026-11-14)

- The corrections of `docs/re/usd-driver.md` §11 are merged into `docs/re/advbios.md`, the sound
  routine names into `docs/re/listing/advbios-names.tsv`.
- `gamedata.py derive` reproduces everything derived (unpacked executables, script exports, PNGs,
  plug-in listings, VGM reference recordings); the dump owner's `FLAG*` / `NAME.DEF` are marked in
  `resources/inventory.tsv` as test inputs that must never be packed.
