# NOVA / Adv98X

Reverse engineering of the PC-98 visual novel NOVA ～魅入られた肢体～ (Cat's Pro, 1993; engine
Adv98V 1.70.54 on AdvBIOS 0.54) and a new portable engine for it, **Adv98X** (binary `adv98x`,
C prefix `ax_`/`AX_`, game profile and pack name `nova`). Successor of the Xenon port
(`xenon`), whose platform layer this engine starts from.

## Where things are

- `docs/re/README.md` — index of the research: interpreter, script format, AdvBIOS services,
  plug-ins, picture formats, music driver and sequencer, script catalogue, disks, other releases.
  **Read the relevant document before writing engine code; they are the specification.**
- `docs/engine-plan.md` — the approved implementation plan (architecture, what is copied from
  Xenon, milestones M0–M7, verification) with the current status at its top.
- `source/` — the engine (`engine/`, `hal/`, `backends/`, `Makefile`, `tests/`) and the
  build-side Python in `source/tools/` (stdlib only): `gamedata.py` (import/check/derive),
  `diskimg.py`, `mes.py` (script parser), `gpc.py` (picture decoder), `mkpack.py` / `xpak.py`
  (the pack), `xfont.py` (fonts). Build: `cd source && make pack && make TARGET=sdl3`;
  tests: `make TARGET=host test`.
- `re-tools/` — research tools (disassembly, emulation harnesses, verified reference models:
  `usdmodel.py` for the music sequencer, `gpc_verify.py`, `tcmtool.py`, `mesdis.py`, `mesgraph.py`).
  The engine's test references: `advbios_emu.py` (AdvBIOS's own INT F1h/F3h/F6h code under
  unicorn) and `nvovl_emu.py` (the original interpreter NV.OVL on it).
- Annotated listings of NV.OVL, NV.OV1 and the plug-ins: `resources/derived/listing/` (made by
  `gamedata.py derive listing`; names in `docs/re/listing/*.tsv`). The engine code cites their
  addresses: read the handler there before changing engine behaviour.

## Tests (`cd source && make TARGET=host test`, about 70 s)

- `tests/run.sh` runs everything; data-free tests first, the rest skip with a note without the
  imported game, the pack (`make pack`) or a Python with unicorn (`$EMU_PYTHON`).
- Each check pairs a C test program (`tests/test_*.c`, linked with the engine objects) with a
  Python comparer (`tests/check_*.py`) against a reference: `gpc.py`, `mes.py`, `usdmodel.py`
  and the driver's recordings, AdvBIOS under emulation (`check_text`, `check_palette`), and the
  original interpreter (`check_vm.py`: scenarios on the game's scripts plus synthetic test
  scripts assembled in the check; memory, screen, DAC, text VRAM, saves, sound and palette calls
  compared). New behaviour gets a `check_vm.py` scenario.
- `tests/e2e/explore.py` plays headless (rotating menu and map choices, `--choose` fixes story
  choices, `--record` keeps the input, `--chain` plays stories in turn with a reset after each
  ending); `tests/e2e/stories.sh` plays all three stories in one run and checks the unlock files; `tests/e2e/present.py` checks the SDL3 backend's rendering offscreen (runs
  when `make TARGET=sdl3` was built).
- `make TARGET=sdl3 dist` makes the player's archive (no pack), `make dist-src` the source one;
  the version is `engine/version.h`.
- `make TARGET=host e2e` (about 15 minutes): `check_vm.py`'s routes, every story and ending in
  both languages played through the engine and the original interpreter, compared at the
  unlock save.
- Gotchas: rebuild the test binaries after engine changes (`make TARGET=host test` does, a bare
  `make` does not relink `build/host/tests/*`); restoring a source within the same second as a
  build can leave a stale object (touch it).
- `resources/` — only our own tables are committed (`inventory.tsv`, `scripts.tsv`, `music/*.tsv`).

## Rules

- **No game data in the repository, ever**: no original files, decoded art, script text dumps,
  disassembly listings or recordings. They live in `resources/original/` and `resources/derived/`
  (git-ignored) and are rebuilt from the user's originals:
  `python3 -I source/tools/gamedata.py import <your copies>/pc-98 <EVE.PCK> "<Fuzion .hdi>"`
  then `python3 -I source/tools/gamedata.py derive --python $EMU_PYTHON`.
  Docs quote the game only as far as needed to identify things. The `FLAG*` / `NAME.DEF` of the
  dumped disk A are the previous owner's state: test inputs only, never packed.
- Engine: generic Adv98V engine, NOVA is a profile; no game-specific hacks. Plug-ins (`.TCM`) are
  native modules enabled per game. The VM executes script bytes exactly as `NV.OVL` does.
- Licence GPL-3.0-or-later (SPDX header in every own source file); third-party code keeps its own.
- Every test compares against data from the original code or a verified reference tool, never
  against the engine's own output.
- Research documents mark claims **verified** / **inferred** and cite code addresses; keep that
  when adding to them, and fix a document when the engine work proves it wrong.
- Python tools run as `python3 -I tool.py`; emulation tools need `$EMU_PYTHON`
  (capstone, unicorn, pillow, numpy).
- Commit after each coherent step; private repo for now (a pseudonymous public release comes
  later, so keep names, hosts and home paths out of tracked files).
