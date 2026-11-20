# The engine on the Amiga family

The Amiga programs (`make TARGET=amiga`, `warpos`, `aros`) are this engine on lrvne's Amiga
backend: [source/lrvne/backends/amiga/README.md](../source/lrvne/backends/amiga/README.md)
describes the backend (screens, window, scaling, Paula and AHI, the audio task's CPU budget,
WarpOS, AROS, options and tool types, packs and saves, testing). This page has what is the
engine's.

## Builds

| target | system | FM core | program file |
|---|---|---|---|
| `amiga` | AmigaOS 3.x, 68020+ (vbcc) | the light core, its render loop in 68k assembly | 233 KB |
| `warpos` | WarpOS on a PowerPC card (vbcc) | the light core in C | 313 KB |
| `aros` | AROS x86_64, ABIv11 (the AROS gcc) | the light core in C | 400 KB (382 KB stripped) |

The toolchains are found on the `PATH` and through their own variables (`VBCC`, `NDK`;
`AROS_SDK`), as lrvne's README says; nothing in the build names a directory. ymfm and the
control protocol are off on these targets (lrvne's `mk/amiga.mk`). The program carries
`$VER: adv98x <version> (<date>)` (`engine/main.c`, from `engine/version.h`), so `Version
adv98x` answers.

**Stack.** The interpreter recurses for the script's blocks, as the original did on the PC-98's
stack. Every story played through in 20 KB of stack on x86-64 (`ulimit -s`, host build);
hosted AROS reports 7.6 KB used after 30 000 frames of play. The 68k program runs on at least
64 KB: lrvne's backend has vbcc's startup swap in a stack that large when the shell's or the
icon's is smaller (both default to 4 KB), the size from the Makefile (`LRVNE_AMIGA_STACK`). The WarpOS startup has no such variable: give that program
64 KB (`Stack 65536`, or the icon's stack size). AROS swaps in 256 KB itself (lrvne).

`make TARGET=amiga|warpos|aros dist` makes `build/<target>/adv98x-<version>-<target>.lha`
(AROS: `-aros-x86_64`): the drawer `Adv98X` with the program, `LICENSE` and `ReadMe.txt`, put
together from [source/dist/amiga/](../source/dist/amiga/) (the parts the three share and each
target's requirements and options; a part the game has in its own `dist/amiga/` replaces the
engine's). No icon: an icon is artwork of a game, and the engine has
none of its own. No pack: the player builds it from their own copy (`make pack`) and puts
the game's pack into the drawer. Saves are `PROGDIR:saves/<game>/FLAG0`..`FLAG9` and `NAME.DEF`,
the original's files.

## What the port needed of the engine

vbcc (68k and PPC) and the AROS gcc took the engine as it was: no C99 feature it uses is
missing there, nothing assumes a POSIX host (files are the pack and the HAL's storage), and
64-bit arithmetic is only the music driver's clock (additions, comparisons and one
multiplication, which vbcc's library does). Changed for these targets: the `$VER:` string,
the stack size (`LRVNE_AMIGA_STACK`), and the half-width string buffer of `vm_run` made static (512 bytes less in
every level of the interpreter's recursion).

**Byte order.** Every multi-byte value the engine reads or writes is assembled from bytes in
the order the original's: the interpreter's memory and everything stored in it (saves are
256-byte images of it, `vm_rd16`/`vm_wr16`, little-endian as on the PC-98), GPC headers and
palettes (`lrv_rd16le`/`lrv_rd32le` of `lrvne/endian.h`), the music driver's song and bank
words (`usd_word`, the LFO depth), click maps (bytes), `NAME.DEF` (Shift-JIS words written high
byte first, by shifts), the plug-ins' arguments (read through `vm_rd16`). No byte buffer is cast
to a wider type anywhere in the engine; palettes and the text window are native `uint16_t`
arrays that never meet a byte buffer. The pack, the fonts and the profile are lrvne's readers.

## Testing

* **AROS** (`make TARGET=aros test`, `source/tests/aros/check_aros.py` on lrvne's rigs,
  `lrvne/rigs/README.md`): the AROS program in hosted AROS (`AROS_DIR` or `AROS_HOSTED` = the
  unpacked `AROS-202609-linux-x86_64-system`, in the environment or `tests/rig.conf`; X via
  `xwfb-run`; runs in `../build/rig-runs/`, the system tree, about 170 MB, removed after each) against the
  host build given the same input: the presentation test (25 snapshots), and the game under
  scripted input for 30 000 frames in each language (random Return/cursor/Esc presses, Shift
  held to skip text; the English run reads the pack from its file, `PRELOAD=no`). Every
  snapshot's frame hash and the picture the program read back from its screen must be the host
  frame's, and the records the game wrote the host's, byte for byte. Tried 2026-11-15: all
  OK (25 + 60 + 60 snapshots, `NAME.DEF`). A run with sound through AHI (hosted AHI into a
  private PipeWire sink, recorded by `aros.sh`) played the music. Nothing waits for a number
  of seconds: a run ends when its commands are done (a marker `aros.sh` waits for),
  `AROS_TIMEOUT` (900 s) is each run's backstop, and a run that did not finish fails saying
  how (`aros.sh`'s exit status: 3 AROS ended first, 4 no X server, 124 the backstop).
* **Big-endian** (`make TARGET=host be68k`, `source/tests/be68k/`): the whole engine and lrvne's
  library, built for m68k Linux with `m68k-linux-gnu-gcc` (freestanding: `rt.c` is its C
  library) and run under `qemu-m68k -cpu m68040`, on a HAL of its own that mirrors the headless
  backend: the pack read from the file, autoplay input (lrvne's code), sound pushed through the
  light FM core at 11 025 Hz, records in memory. The same program built natively must print
  the same, and must match `adv98x` itself (frame hashes, the WAV it recorded, the records).
  30 000 frames per language, about 20 s. Tried 2026-11-15: all OK; with `vm_rd16` changed to
  read the host's byte order the 68040 diverges at the first snapshot.
* **68k and WarpOS** (`make TARGET=amiga test`, `make TARGET=warpos test`): the presentation
  test of the 68k program in WinUAE (native, rtg, promote and uaegfx screens, in parallel, in
  warp) and of the WarpOS program in the Blizzard PPC emulation, against the host build
  (lrvne's `lrvne-present`; WinUAE, the Kickstart, a Workbench tree and WarpUP in the
  environment or `tests/rig.conf`). `make TARGET=amiga|aros lrvne-dist-check` unpacks and runs
  the release archive. 2026-11-16 the 68k program also ran 2100 frames under `rand:11` in
  WinUAE: 2748 of 65 536 bytes of stack, the snapshots at 500, 1000 and 2000 equal to the
  headless build's. lrvne's `make opn68k` checks the 68k assembly FM loop against the C loop
  under qemu-m68k.

Seen while making the big-endian test: GCC 16.2 for m68k inlined a byte-copy loop as `move.b
(a1)+,(0,a1,d0.l)`, with `d0` worked out as if `a1` were not yet incremented when the
destination is computed; the 68k increments it first. `rt.c` keeps its copy loops out of line,
and no such instruction is in the engine's code; vbcc is not affected.
