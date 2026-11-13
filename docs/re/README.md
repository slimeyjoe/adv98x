# NOVA ～魅入られた肢体～ (Cat's Pro, PC-9801, 1993) — reverse engineering notes

Scope: the original PC-98 release — the generic engine Adv98V 1.70.54 (`NV.OVL`) on AdvBIOS 0.54
(`NV.OV1`), its plug-ins, and all game data — documented as the basis for a new engine. The
documents describe the original only; decisions about the port belong elsewhere.

Source material (not in the repository; `source/tools/gamedata.py import` brings the files in and
checks them against `resources/inventory.tsv`): the four 2HD floppies of 1993-05-28 (D88), the
Windows release of 1996 (`EVE.PCK`), the FM Towns CD of 1993, and the English translation by Fuzion
(a hard-disk image; only its 117 scripts differ from the Japanese release).

## Documents

| Document | Contents |
|---|---|
| [interpreter.md](interpreter.md) | `NV.OVL`: packing, memory map, start-up, the run loop, menus, saves, player name, drives, plug-in calling convention, `NV.INI` and its copy protection, every service call the interpreter makes |
| [mes-format.md](mes-format.md) | `.MES` scripts: tokens, text and control codes, conditions, all 51 opcodes with operands, semantics and handler addresses, defects in the original scripts |
| [advbios.md](advbios.md) | `NV.OV1`: layout, start-up, the complete service interface (INT F1h system, F2h files, F3h graphics, F4h sound, F6h text, 33h mouse), VRAM model, character drawing, animation cells, scrolling, palette and brightness, input, timing sources, disks |
| [plugins.md](plugins.md) | the five `.TCM` plug-ins: CHGFONTH (bold), PALCH (one-colour glide), WHITEH (white fade), INPUTNAM (name entry), ACTE1 (screen blocks: 14 commands); what a native replacement must do |
| [graphics-formats.md](graphics-formats.md) | GPC pictures (header, compression, interleave, palette), the Windows release's Pi files, verification, table of all pictures |
| [script-catalog.md](script-catalog.md) | every script, the route graphs of the three stories, maps, saves and unlocks, CG and music modes, the complete flag and variable tables, script bugs |
| [disks.md](disks.md) | which file is on which floppy, how scripts select disks, the rule that resolves every picture reference |
| [other-versions.md](other-versions.md) | the Windows release (EVE engine, script format, differences) and the FM Towns release (AdvTowns, archives, script dialect), the song ↔ CD track table |
| [usd-driver.md](usd-driver.md) | the music driver "USDdrv" inside AdvBIOS: layout, chip detection, the two timers, the INT F4h functions, fades, effect banks; §11 lists corrections to advbios.md |
| [usd-sequencer.md](usd-sequencer.md) | the `.USO` song format and sequencer: file layout, per-tick algorithm, all commands, note tables, FM and SSG voices, LFOs, envelopes; per-song table |
| [listing/](listing/) | name tables for `NV.OVL`, `NV.OV1` and the plug-ins. Disassembly listings are the game's code and are generated locally (`resources/derived/listing/`), never committed |

## Tools

Build-side tools (stdlib only) are in `source/tools/`, research tools in `re-tools/`; each has its
usage in its header. Run them with `python3 -I`; the emulation harnesses need `capstone` and
`unicorn` (`python3 -m venv DIR && DIR/bin/pip install capstone unicorn pillow numpy`).

| Tool | Purpose | Verification |
|---|---|---|
| `source/tools/gamedata.py`, `diskimg.py` | import the releases (D88, FAT12/16, HDI, PCK) by name + md5 | 662 files of three releases |
| `re-tools/exeunpack.py` | TC0 decryption + EXEPACK decompression of the executables | unpacked images disassemble and match the reference build's code |
| `source/tools/mes.py`, `re-tools/mesdis.py` | script parser; lister, checker, exporter | all 236 scripts: every byte covered, block ends agree with the interpreter's scanner |
| `re-tools/mesgraph.py` | transition graph, per-script summaries, reachability, picture resolution | 1038 picture references resolve to exactly one file |
| `source/tools/gpc.py`, `re-tools/pi.py`, `re-tools/gpc_verify.py` | picture decoders | bit-exact with the original decoder under emulation on all 103 distinct GPC files |
| `re-tools/dis16.py`, `advbios_map.py`, `tcmtool.py` | 16-bit disassembler with name files; label transfer from Valley Bell's listing; plug-in listings and emulation harness | — |
| `re-tools/evedis.py`, `evecmp.py`, `cdimg.py` | Windows scripts, release comparison, Towns CD image and archives | 118 Windows scripts fully covered |
| `re-tools/usoinfo.py`, `usdemu.py`, `usdmodel.py` | song dump, original driver under emulation (VGM recordings), clean-room sequencer model | model = original on every register write: 28 files in play, fade, stop and chained scenarios plus synthetic songs (5.7 M writes) |

## Regenerating

```sh
python3 -I source/tools/gamedata.py import PATH/TO/pc-98 PATH/TO/EVE.PCK "PATH/TO/Nova [TL-En by Fuzion].hdi"
mkdir -p resources/derived/exe
for f in NV.OVL NV.OV1 INSTH.EXE; do python3 -I re-tools/exeunpack.py resources/original/pc98/A/$f resources/derived/exe/$f; done
python3 -I re-tools/mesdis.py check  resources/original/pc98/A/MES/*.MES resources/original/pc98/A/NV.INI resources/original/en/MES/*.MES
python3 -I re-tools/mesdis.py export resources/derived/scripts resources/original/pc98/A/MES/*.MES resources/original/pc98/A/NV.INI
python3 -I source/tools/gpc.py png resources/original/pc98/*/GPC/*.GPC -o resources/derived/images/gpc
```

## Credits

Prior work this research builds on, read with thanks: Valley Bell's PC98VNResearch (annotated
AdvBIOS 0.54 disassembly, TC0 decryption), lime-juice by Fuzion after tomyun's juice (MES opcode
names, GPC notes), SuperSakura by Kirinn Bunnylin (GPC and Pi format descriptions), hermit1000's
mes-tools (the GPC XOR carry-over observation).
