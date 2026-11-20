# Adv98X

A portable engine for the games of Cat's Pro's PC-98 adventure engine Adv98V 1.70.54 on AdvBIOS
0.54: **Adv98X** (binary `adv98x`, C prefix `ax_`/`AX_`), with the reverse engineering of those
programs it is written from. The engine is built on **lrvne**, the shared low-level library of
this engine and its siblings (submodule `source/lrvne`, public, C prefix `lrv_`).

A game is a repository of its own with this one as its submodule `engine/`: its `game.py`
describes it to the engine's tools (`source/tools/gamedir.py` finds a game: `GAME_DIR`, or the
nearest directory with a `game.py`), its `tests/cases.py` holds what the tests try on it, and
its `Makefile` runs this one's with `GAME_DIR` set. The first game is NOVA ～魅入られた肢体～
(1993; `adv98x-nova`); the research was read from its copy of the original programs, so its
files are the examples throughout.

## Where things are

- `docs/re/README.md` — index of the research: interpreter, script format, AdvBIOS services,
  plug-ins, the picture format, music driver and sequencer. A game's own research (its scripts,
  disks, pictures, songs, other releases) is in its repository (`docs/re/game.md`).
  **Read the relevant document before writing engine code; they are the specification.** They
  describe one build of the original programs (`re-tools/advbuild.py`): the harnesses refuse
  another.
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
- `source/tools/` (stdlib only, on `lrvne/tools`): `gamedir.py` (the engine's and the game's
  roots), `gamedata.py` (import/check/derive: lrvne's inventory framework with the game's
  hooks, `game.py` IMPORT), `mkpack.py` (the pack from `game.py` PACK, ORIGINAL, PROFILE),
  `mes.py` (script parser), `gpc.py` (picture decoder).
- Build: in a game's directory `make pack && make TARGET=sdl3`; tests: `make test` there. Alone
  (`cd source`), the engine builds and runs the tests that need no game.
  The Amiga family (`TARGET=amiga|warpos|aros`, lrvne's Amiga backend, no ymfm): `docs/amiga.md`;
  the engine must stay C99 as vbcc takes it, free of POSIX assumptions, endian-neutral (bytes
  assembled explicitly, never a byte buffer cast to a wider type) and light on stack (the
  interpreter recurses).
- `re-tools/` — research tools (disassembly, emulation harnesses, verified reference models:
  `usdmodel.py` for the music sequencer, `tcmtool.py`, `mesdis.py`, `mesgraph.py`); they work on
  the game `gamedir.py` finds.
  The engine's test references: `advbios_emu.py` (AdvBIOS's own INT F1h/F3h/F6h code under
  unicorn) and `nvovl_emu.py` (the original interpreter NV.OVL on it).
- Annotated listings of NV.OVL, NV.OV1 and the plug-ins: the game's `resources/derived/listing/`
  (made by `gamedata.py derive listing`; names in `docs/re/listing/*.tsv`). The engine code cites their
  addresses: read the handler there before changing engine behaviour.

## Tests (`make test` in a game's directory, about 70 s)

- `tests/run.sh` runs everything; a test skips with a note without a game (`GAME_DIR`), its
  imported data, its pack (`make pack`), the dumped copy's saves (the scenarios that need them)
  or a Python with unicorn (`EMU_PYTHON=...`; without it `python3` is tried).
- The mechanisms are here; what they try on a game is in its `tests/cases.py`, written with
  `tests/casekit.py` (keys, clicks, the reset button, the script assembler). No test names a
  game's scripts, pictures, songs or saves itself.
- The headless backend is deterministic: `adv98x --pak P --autoplay SPEC` (snapshots with frame
  hashes at `snap:` ticks), `--control` (the line protocol the Python drivers use: `press`,
  `hold`, `mouse`, `snap`, `record`, `break`), `--render-wav F --song NAME [--opn lite]`,
  `--present-test`. Keys are lrvne's neutral names (`return`/`ok`, `esc`/`cancel`, `down`,
  `a`, `kp8`, ...); a press also shows in the key-down bitmap for the poll that delivers it.
- Each check pairs a C test program (`tests/test_*.c`, linked with the engine and lrvne, HAL in
  `tests/test_hal.h`) with a Python comparer (`tests/check_*.py`) against a reference: `gpc.py`, `mes.py`, `usdmodel.py`
  and the driver's recordings, AdvBIOS under emulation (`check_text`, `check_palette`), and the
  original interpreter (`check_vm.py`: the game's scenarios on its scripts plus synthetic test
  scripts; memory, screen, DAC, text VRAM, saves, sound and palette calls compared). New
  behaviour gets a `check_vm.py` scenario in the game's cases.
- `tests/e2e/explore.py` plays headless (rotating menu and map choices, `--choose` fixes story
  choices, `--record` keeps the input, `--chain` plays stories in turn with a reset after each
  ending); `tests/e2e/stories.sh` plays the game's stories in one run and checks the unlock files; `tests/e2e/present.py` checks the SDL3 backend's rendering offscreen (runs
  when `make TARGET=sdl3` was built).
- `make TARGET=host be68k` (about 20 s): the whole engine built for m68k Linux and run under
  qemu-m68k (big-endian) against the native build and the headless backend
  (`tests/be68k/`); `make TARGET=aros test`: the AROS build in hosted AROS (`AROS_HOSTED`)
  against the host build (`tests/aros/`). Neither is part of `make test`.
- The engine's teardown: the engine is asked to quit at `--max-ticks` and must have freed
  everything it allocated through the HAL when `run` returns, or lrvne's headless backend ends
  with exit code 1 ("memory: N bytes in M blocks not freed by the engine"); the teardown run in
  `tests/run.sh` (to `--max-ticks`, expects exit code 3) keeps it so. Memory an engine part
  allocates on first use needs a shutdown function called at the end of the run. Here:
  `vm_shutdown`, `bios_shutdown`, and a module's `shutdown` member (`mod_shutdown`; ACTE1 drops
  its blocks); the teardown run plays the game's schedule (NOVA's reaches ACTE1).
- Hosted AROS with sound: lrvne's rig runs AROS without PipeWire's data-loop threads (its ALSA
  driver otherwise lets that thread take AROS's timer signal and AROS crashes now and then;
  `lrvne/rigs/README.md`, "Hosted AROS and PipeWire"; `AROS_PW_DATA_LOOPS=1` to see it), and fails
  any run whose AROS log shows a crash.
- `make TARGET=sdl3 dist` makes the player's archive (no pack), `make TARGET=amiga|warpos|aros
  dist` the Amiga family's .lha, `make dist-src` the source one
  (with the submodule's tree); the version is `engine/version.h`.
- `make TARGET=host SAN=1 test` runs the same under the sanitizers (objects in `build/host-san`).
- `make e2e` (about 15 minutes for NOVA): the game's routes, every story and ending in every
  language played through the engine and the original interpreter, compared at the unlock
  save.
- Gotchas: rebuild the test binaries after engine changes (`make TARGET=host test` does, a bare
  `make` does not relink `build/host/tests/*`); restoring a source within the same second as a
  build can leave a stale object (touch it).

## Rules

- **No game data in any repository, ever**: no original files, decoded art, script text dumps,
  disassembly listings or recordings. They live in the game's `resources/original/` and
  `resources/derived/` (git-ignored) and are rebuilt from the user's originals with the game's
  `make data SRC=<your copies...>` (any mix of directories, archives and images; or
  `LRVNE_MEDIA=<dir>` and no argument). The location of the media is given on the command line
  or in the environment, never written into a tracked file.
  Docs quote a game only as far as needed to identify things. A dumped copy's own saves are
  the previous owner's state: test inputs only, never packed.
- Engine: generic Adv98V engine; no game-specific hacks, and no game's name or file names in
  `source/engine`, the Makefile, the tools' defaults or the tests' mechanisms: what differs
  between games is in the game's `game.py` (the pack's profile: `engine/game/profile.c`) and
  `tests/cases.py`. A game's name belongs in the research only where it says where something
  was observed. Plug-ins (`.TCM`) are native modules enabled per game. The VM executes script
  bytes exactly as `NV.OVL` does.
- Licence GPL-3.0-or-later (SPDX header in every own source file); third-party code keeps its own.
- Every test compares against data from the original code or a verified reference tool, never
  against the engine's own output.
- Research documents mark claims **verified** / **inferred** and cite code addresses; keep that
  when adding to them, and fix a document when the engine work proves it wrong.
- Python tools run as `python3 -I tool.py` (lrvne's as `python3 -I source/lrvne/tools/lrvne
  TOOL ...`); emulation tools need a Python with capstone, unicorn, pillow and numpy
  (docs/re/README.md "Tools").
- Commit after each coherent step. **A public, pseudonymous repository**: commits carry the
  repo-local identity only; no personal names, e-mail addresses, hosts, home paths or session
  links in tracked files or commit messages (`scripts/check-leaks.sh`, installed as git hooks,
  with a private pattern list in `.git/info/leak-patterns`). `source/lrvne` is a submodule: commit lrvne changes in it (its own identity and leak hooks), then record the new
  commit here; before that run its `make test SAN=1` and `scripts/check-leaks.sh tree`.
