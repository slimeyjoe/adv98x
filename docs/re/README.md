# Adv98V 1.70.54 on AdvBIOS 0.54 — reverse engineering notes

Scope: the generic engine of Cat's Pro's PC-98 adventure games, Adv98V 1.70.54 (`NV.OVL`), on
AdvBIOS 0.54 (`NV.OV1`), its music driver and its plug-ins, documented as the basis for a new
engine. The documents describe the original only; decisions about the port belong elsewhere.

They were read from one build of these programs: the one on the disks of NOVA ～魅入られた肢体～
(1993), the first game this engine plays, which is why its files and scripts are the examples
throughout. Addresses are of that build; another build of the same version moves data, so the
name tables and the harnesses take only this one (`re-tools/advbuild.py`). What is particular
to a game (its scripts, disks, pictures and songs, its other releases) is in that game's
repository: for NOVA, its `docs/re/game.md`.

The originals are not in any repository: a game's `make data` brings them in from the player's
copy and checks them against the game's `resources/inventory.tsv`.

## Documents

| Document | Contents |
|---|---|
| [interpreter.md](interpreter.md) | `NV.OVL`: packing, memory map, start-up, the run loop, menus, saves, player name, drives, plug-in calling convention, `NV.INI` and its copy protection, every service call the interpreter makes |
| [mes-format.md](mes-format.md) | `.MES` scripts: tokens, text and control codes, conditions, all 51 opcodes with operands, semantics and handler addresses, defects in the original scripts |
| [advbios.md](advbios.md) | `NV.OV1`: layout, start-up, the complete service interface (INT F1h system, F2h files, F3h graphics, F4h sound, F6h text, 33h mouse), VRAM model, character drawing, animation cells, scrolling, palette and brightness, input, timing sources, disks |
| [plugins.md](plugins.md) | the five `.TCM` plug-ins: CHGFONTH (bold), PALCH (one-colour glide), WHITEH (white fade), INPUTNAM (name entry), ACTE1 (screen blocks: 14 commands); what a native replacement must do |
| [graphics-formats.md](graphics-formats.md) | GPC pictures (header, compression, interleave, palette), what the original draw routine does, verification |
| [usd-driver.md](usd-driver.md) | the music driver "USDdrv" inside AdvBIOS: layout, chip detection, the two timers, the INT F4h functions, fades, effect banks; §11 lists corrections to advbios.md |
| [usd-sequencer.md](usd-sequencer.md) | the `.USO` song format and sequencer: file layout, per-tick algorithm, all commands, note tables, FM and SSG voices, LFOs, envelopes |
| [listing/](listing/) | name tables for `NV.OVL`, `NV.OV1` and the plug-ins, of the build `re-tools/advbuild.py` names. Disassembly listings are the original's code and are generated locally (`gamedata.py derive listing` → the game's `resources/derived/listing/`), never committed |

## Tools

Build-side tools (stdlib only) are in `source/tools/`, research tools in `re-tools/`; each has its
usage in its header. They work on a game: `source/tools/gamedir.py` finds it (`GAME_DIR`, or the
nearest directory with a `game.py`). Run them with `python3 -I`; the emulation harnesses need
`capstone` and `unicorn`: make a virtual environment for them (`python3 -m venv DIR &&
DIR/bin/pip install capstone unicorn pillow numpy`) and name its Python where one is asked for
(`EMU_PYTHON` for the tests, `DATA_PY` / `--python` for `gamedata.py derive`; `$EMU_PYTHON`
below).

| Tool | Purpose | Verification |
|---|---|---|
| `source/tools/gamedata.py` (on lrvne's `inventory`, `source`, `diskimg`) | import a game's releases (directories, archives, D88, FAT12/16, HDI, the game's own archives) by name + md5; derive | NOVA: 661 files of three releases |
| `re-tools/exeunpack.py` | TC0 decryption + EXEPACK decompression of the executables | unpacked images disassemble and match the reference build's code |
| `re-tools/advbuild.py` | the build these documents describe, by md5; the harnesses refuse another | — |
| `source/tools/mes.py`, `re-tools/mesdis.py` | script parser; lister, checker, exporter | NOVA's 236 scripts: every byte covered, block ends agree with the interpreter's scanner |
| `re-tools/mesgraph.py` | transition graph, per-script summaries, reachability, picture resolution | NOVA: 1038 picture references resolve to exactly one file |
| `source/tools/gpc.py` | picture decoder | bit-exact with the original decoder under emulation on all of NOVA's 103 distinct GPC files (the game's `re-tools/gpc_verify.py`) |
| `re-tools/dis16.py`, `advbios_map.py`, `tcmtool.py` | 16-bit disassembler with name files; label transfer from Valley Bell's listing; plug-in listings and emulation harness | — |
| `re-tools/advbios_emu.py` | AdvBIOS's own INT F1h/F3h/F6h code under emulation (GRCG, DAC ports, kanji ROM modelled), the reference for the engine's text and palette tests | the engine's `check_text.py`, `check_palette.py` |
| `re-tools/nvovl_emu.py` | the original interpreter NV.OVL on the original AdvBIOS under emulation (files, keys, clicks and the plug-ins' DOS memory modelled): scripts run as on the PC-98 | the engine's `check_vm.py` compares memory, screen, DAC, saves and sound calls with it, up to whole stories (`stop_save=`: end after a given save) |
| `re-tools/usoinfo.py`, `usdemu.py`, `usdmodel.py` | song dump, original driver under emulation (VGM recordings), clean-room sequencer model | model = original on every register write: NOVA's 28 files in play, fade, stop and chained scenarios plus synthetic songs (5.7 M writes) |

## Regenerating

In a game's directory (or with `GAME_DIR` set to it), after `make data`:

```sh
python3 -I source/tools/gamedata.py derive --python $EMU_PYTHON   # exe scripts images listing vgm (+ .tsv logs)
$EMU_PYTHON re-tools/usdmodel.py --check  # sequencer model against the original driver (about 2 min)
```

## Credits

Prior work this research builds on, read with thanks: Valley Bell's PC98VNResearch (annotated
AdvBIOS 0.54 disassembly, TC0 decryption; the names marked "VB" in `listing/advbios-names.tsv`
are taken from it under its terms, given there), lime-juice by Fuzion after tomyun's juice (MES
opcode names, GPC notes), SuperSakura by Kirinn Bunnylin (the GPC format description),
hermit1000's mes-tools (the GPC XOR carry-over observation).
