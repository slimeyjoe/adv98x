# NOVA / Adv98X

Reverse engineering of the PC-98 visual novel NOVA ～魅入られた肢体～ (Cat's Pro, 1993; engine
Adv98V 1.70.54 on AdvBIOS 0.54) and a new portable engine for it, **Adv98X** (binary `adv98x`,
C prefix `ax_`/`AX_`, game profile `nova`). The engine is built on **lrvne**, the shared low-level
library of this engine and its siblings (submodule `source/lrvne`, public, C prefix `lrv_`).

## Where things are

- `docs/re/README.md` — index of the research: interpreter, script format, AdvBIOS services,
  plug-ins, picture formats, music driver and sequencer, script catalogue, disks, other releases.
  **Read the relevant document before writing engine code; they are the specification.**
- `docs/engine-plan.md` — the approved implementation plan (architecture, the layering on lrvne,
  milestones M0–M7, verification) with the current status at its top.
- `source/engine/` — the engine, and only what is its own: the interpreter (`vm/`), AdvBIOS's
  services (`bios/`), the GPC decoder, pointer and text layer (`gfx/`), the USD music driver
  (`snd/`), the plug-in modules (`mod/`), the run logic and profile (`game/`), `main.c` (the
  `struct lrv_app`). One state struct, `ax` (`engine/ax.h`), embeds lrvne's instances.
- `source/lrvne/` — everything below that, compiled into the engine from source
  (`mk/lrvne.mk`): frame loop and input (`lrv_sys`), screen (`lrv_screen`), PC-98 keyboard and
  video mode, OPN cores, write queue and mixer, fonts, pack, profile parser, the backends
  (headless `null` for `TARGET=host`, `sdl3`) with command line, autoplay and the control
  protocol, and the generic Python tools. Its headers in `include/lrvne/` are its documentation;
  read `docs/architecture.md` and `docs/porting-an-engine.md` there. **It is a public,
  pseudonymous repository of its own**: never put a person's name, a host or home path, this
  engine's or a game's name into it, and nothing engine- or game-specific. A bug or a gap found
  from here is fixed there, generically, with a test there; the engine does not work around
  lrvne and does not wrap it (call `lrv_*` directly).
- `source/tools/` (stdlib only, on `lrvne/tools`): `gamedata.py` (import/check/derive: lrvne's
  inventory framework with this game's hooks), `mkpack.py` (the pack's contents and the game
  profile), `mes.py` (script parser), `gpc.py` (picture decoder).
- Build: `cd source && make pack && make TARGET=sdl3`; tests: `make TARGET=host test`.
- `re-tools/` — research tools (disassembly, emulation harnesses, verified reference models:
  `usdmodel.py` for the music sequencer, `gpc_verify.py`, `tcmtool.py`, `mesdis.py`, `mesgraph.py`).
  The engine's test references: `advbios_emu.py` (AdvBIOS's own INT F1h/F3h/F6h code under
  unicorn) and `nvovl_emu.py` (the original interpreter NV.OVL on it).
- Annotated listings of NV.OVL, NV.OV1 and the plug-ins: `resources/derived/listing/` (made by
  `gamedata.py derive listing`; names in `docs/re/listing/*.tsv`). The engine code cites their
  addresses: read the handler there before changing engine behaviour.

## Tests (`cd source && make TARGET=host test`, about 70 s)

- `tests/run.sh` runs everything; a test skips with a note without the imported game, the pack
  (`make pack`) or a Python with unicorn (`EMU_PYTHON=...`; without it `python3` is tried).
- The headless backend is deterministic: `adv98x --pak P --autoplay SPEC` (snapshots with frame
  hashes at `snap:` ticks), `--control` (the line protocol the Python drivers use: `press`,
  `hold`, `mouse`, `snap`, `record`, `break`), `--render-wav F --song NAME [--opn lite]`,
  `--present-test`. Keys are lrvne's neutral names (`return`/`ok`, `esc`/`cancel`, `down`,
  `a`, `kp8`, ...); a press also shows in the key-down bitmap for the poll that delivers it.
- Each check pairs a C test program (`tests/test_*.c`, linked with the engine and lrvne, HAL in
  `tests/test_hal.h`) with a Python comparer (`tests/check_*.py`) against a reference: `gpc.py`, `mes.py`, `usdmodel.py`
  and the driver's recordings, AdvBIOS under emulation (`check_text`, `check_palette`), and the
  original interpreter (`check_vm.py`: scenarios on the game's scripts plus synthetic test
  scripts assembled in the check; memory, screen, DAC, text VRAM, saves, sound and palette calls
  compared). New behaviour gets a `check_vm.py` scenario.
- `tests/e2e/explore.py` plays headless (rotating menu and map choices, `--choose` fixes story
  choices, `--record` keeps the input, `--chain` plays stories in turn with a reset after each
  ending); `tests/e2e/stories.sh` plays all three stories in one run and checks the unlock files; `tests/e2e/present.py` checks the SDL3 backend's rendering offscreen (runs
  when `make TARGET=sdl3` was built).
- `make TARGET=sdl3 dist` makes the player's archive (no pack), `make dist-src` the source one
  (with the submodule's tree); the version is `engine/version.h`.
- `make TARGET=host SAN=1 test` runs the same under the sanitizers (objects in `build/host-san`).
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
  `python3 -I source/tools/gamedata.py import <your copies...>` (any mix of directories,
  archives and images; or `LRVNE_MEDIA=<dir>` and no argument), then
  `python3 -I source/tools/gamedata.py derive --python <a Python with capstone and unicorn>`.
  The location of the media is given on the command line or in the environment, never written
  into a tracked file.
  Docs quote the game only as far as needed to identify things. The `FLAG*` / `NAME.DEF` of the
  dumped disk A are the previous owner's state: test inputs only, never packed.
- Engine: generic Adv98V engine, NOVA is a profile; no game-specific hacks, and no game's name
  or file names in `source/engine` or the Makefile's defaults: what differs between games is a
  key of the pack's profile (`engine/game/profile.c`, written by `mkpack.py`'s `PROFILES`).
  Plug-ins (`.TCM`) are native modules enabled per game. The VM executes script bytes exactly as
  `NV.OVL` does.
- Licence GPL-3.0-or-later (SPDX header in every own source file); third-party code keeps its own.
- Every test compares against data from the original code or a verified reference tool, never
  against the engine's own output.
- Research documents mark claims **verified** / **inferred** and cite code addresses; keep that
  when adding to them, and fix a document when the engine work proves it wrong.
- Python tools run as `python3 -I tool.py` (lrvne's as `python3 -I source/lrvne/tools/lrvne
  TOOL ...`); emulation tools need a Python with capstone, unicorn, pillow and numpy
  (docs/re/README.md "Tools").
- Commit after each coherent step; private repo for now (a pseudonymous public release comes
  later, so keep names, hosts and home paths out of tracked files). `source/lrvne` is a
  submodule: commit lrvne changes in it (its own identity and leak hooks), then record the new
  commit here; before that run its `make test SAN=1` and `scripts/check-leaks.sh tree`.
