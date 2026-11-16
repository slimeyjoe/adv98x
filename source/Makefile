# SPDX-License-Identifier: GPL-3.0-or-later
# Adv98X engine - GNU Make 4
#
#   make [TARGET=...] [V=1]        build the engine for a target (default: host = the headless
#                                  backend, for tests; sdl3 = the player; amiga, warpos, aros =
#                                  the Amiga family's programs, ../docs/amiga.md)
#   make data SRC="..."            import the original game from your copies (../docs/game-data.md)
#                                  into ../resources/original/ and derive ../resources/derived/
#   make pack                      build the game pack $(PAK) from the imported game
#   make TARGET=host test [SAN=1]  build and run the conformance tests
#   make TARGET=host be68k         the whole engine on a big-endian 68040 under qemu-m68k
#   make TARGET=aros test          the AROS build in hosted AROS against the host build
#   make TARGET=sdl3 dist          the player's archive ../build/sdl3/adv98x-<version>-<host>.tar.gz
#   make TARGET=amiga|warpos|aros dist   the Amiga family's ../build/<target>/adv98x-<version>-<target>.lha
#   make dist-src                  the source archive ../build/adv98x-<version>-src.tar.gz
#   make clean                     remove ../build/
#   make data-clean                remove everything made from the game outside ../build/
#   make distclean                 clean + data-clean: only the committed files are left
#
# The engine (engine/) is the interpreter, AdvBIOS's services, the picture decoder, the music
# driver and the plug-in modules. Everything below them - the frame loop, the screen, the FM
# chip, fonts, the pack, the backends - is lrvne (the submodule lrvne/), compiled from source
# into the engine by its make fragment, which also defines the targets and their switches
# (lrvne/mk/lrvne.mk: LRVNE_YMFM, LRVNE_CONTROL, SAN).

LRVNE     := lrvne
TARGET    ?= host
# Everything built goes to the top-level build/ (../build from here): build/<TARGET>/ for each
# target, the pack and its intermediates (fonts) in build/ itself.
BUILDROOT := ../build
BUILD     := $(BUILDROOT)/$(TARGET)
APP_NAME  := adv98x
APP_SRCS  := $(sort $(wildcard engine/*.c engine/*/*.c))
APP_INCLUDES := -Iengine
# the version is engine/version.h's (the release is tagged v<version>)
AX_VERSION  := $(shell sed -n 's/^\#define AX_VERSION *"\(.*\)"/\1/p' engine/version.h)
APP_VERSION := $(AX_VERSION)

# The Amiga family (lrvne/backends/amiga/README.md): its release archive (lrvne/mk/amiga-dist.mk)
# is the drawer Adv98X with the program, the licence and a ReadMe put together from the parts in
# dist/amiga/ (those all three share and the target's own). No icons: an icon is artwork of a
# game, and the engine has none of its own.
AMIGA_FAMILY := $(filter amiga warpos aros,$(TARGET))
ifneq ($(AMIGA_FAMILY),)
AMIGA_DIST := dist/amiga
LRVNE_DIST_DRAWER := Adv98X
LRVNE_DIST_README_PARTS := $(BUILDROOT)/$(TARGET)/ReadMe-title.txt \
    $(addprefix $(AMIGA_DIST)/,about.txt requirements-$(TARGET).txt playing.txt \
    options-$(if $(filter aros,$(TARGET)),aros,os3).txt saves.txt)
LRVNE_DIST_FILES := ../LICENSE
# the 68k program's least stack (lrvne swaps in one this large when a shell or an icon gave
# less, 4 KB by default): the interpreter recurses for the script's blocks as the original did
# on the PC-98's stack; every story played through in 20 KB on x86-64, so 64 KB leaves room
LRVNE_AMIGA_STACK := 65536
endif

.DEFAULT_GOAL := all
include $(LRVNE)/mk/lrvne.mk

.PHONY: all clean test e2e be68k
all: $(EXE)

clean:
	rm -rf $(BUILDROOT)

# ---------------------------------------------------------------------------------------------
# Conformance tests (host target). Every test compares the engine with data from the original
# code or a verified reference tool (source/tools/, re-tools/), never with its own output.
# tests/run.sh runs the data-free tests first; those that need the imported game are skipped
# with a note when it is missing.
# ---------------------------------------------------------------------------------------------
ifeq ($(AMIGA_FAMILY),)
TEST_SRCS := $(sort $(wildcard tests/*.c))
TEST_EXES := $(patsubst tests/%.c,$(BUILD)/tests/%$(EXESUF),$(TEST_SRCS))
# each test program is linked with the engine (without its main) and the library, no backend
TEST_OBJS := $(filter-out $(BUILD)/engine/main.o,$(APP_OBJS)) $(LRVNE_LIB_OBJS)
-include $(patsubst tests/%.c,$(BUILD)/tests/%.d,$(TEST_SRCS))

$(BUILD)/tests/%$(EXESUF): $(BUILD)/tests/%.o $(TEST_OBJS)
	@mkdir -p $(dir $@)
	@echo "  LINK  $@"
	$(Q)$(LRVNE_LD) $(OPT) -o $@ $< $(TEST_OBJS) $(LDLIBS)

test: $(TEST_EXES) $(EXE)
	$(Q)tests/run.sh $(BUILD)

# the whole stories against the original interpreter (tests/check_vm.py ROUTES): every ending,
# both languages; long (5-12 CPU minutes per route under emulation, run in parallel)
e2e: $(TEST_EXES) $(EXE)
	$(Q)tests/run.sh $(BUILD) e2e

# big-endian: the engine and lrvne's library on a HAL of their own, built for m68k Linux and run
# under qemu-m68k against the same program built natively, which must match the headless
# backend (tests/be68k/be68k.sh; skipped without the cross compiler or qemu-m68k)
be68k: $(EXE)
	$(Q)tests/be68k/be68k.sh $(EXE) $(PAK) $(BUILD)/be68k; rc=$$?; [ $$rc -eq 77 ] || exit $$rc

else ifeq ($(TARGET),aros)
# The AROS program in hosted AROS (tests/aros/check_aros.py on lrvne's rigs; AROS_DIR or
# AROS_HOSTED in the environment or tests/rig.conf):
# the presentation test and scripted runs of the game, every snapshot's frame hash and the
# picture read back against the host build given the same input, which this builds first.
test: $(EXE)
	$(Q)$(MAKE) --no-print-directory TARGET=host
	$(Q)python3 -I tests/aros/check_aros.py --aros-bin $(EXE) --host-bin $(BUILDROOT)/host/$(APP_NAME)$(EXESUF) \
	    --pak $(PAK) $(CHECK_AROS)
else ifneq ($(filter amiga warpos,$(TARGET)),)
# The 68k or WarpOS program in WinUAE (lrvne's rigs: the presentation test against the host
# build; the emulator's settings in the environment or tests/rig.conf, lrvne/rigs/README.md)
test: lrvne-present
e2e:
	@echo "$@: the $(TARGET) program has no end-to-end rig (make TARGET=$(TARGET) test runs the presentation test)"; exit 1
else
test e2e:
	@echo "$@: the $(TARGET) program has no test rig here (make TARGET=aros test runs the AROS one)"; exit 1
endif

# ---------------------------------------------------------------------------------------------
# The game's data (../docs/game-data.md), which the repository does not carry.
#   make data SRC="DIR-or-image ..."  [DATA_PY=python with capstone/unicorn/pillow/numpy]
# (without SRC: the directories named in the environment variable LRVNE_MEDIA)
# imports the releases into ../resources/original/ (checked against ../resources/inventory.tsv)
# and derives ../resources/derived/ (tools/gamedata.py derive; the parts that need a module
# DATA_PY lacks are skipped with a note).
# ---------------------------------------------------------------------------------------------
DATA_PY  ?=
LRVNE_PY   := python3 -I
LRVNE_TOOL := $(LRVNE_PY) $(LRVNE)/tools/lrvne
.PHONY: data data-derive data-check
data:
	$(Q)test -n "$(SRC)$$LRVNE_MEDIA" || { echo "data: set SRC=<your copies of the game> (../docs/game-data.md)"; exit 1; }
	$(Q)$(LRVNE_PY) tools/gamedata.py import $(SRC)
	$(Q)$(LRVNE_PY) tools/gamedata.py derive $(if $(DATA_PY),--python $(DATA_PY)) $(DATA_PARTS)
data-derive:
	$(Q)$(LRVNE_PY) tools/gamedata.py derive $(if $(DATA_PY),--python $(DATA_PY)) $(DATA_PARTS)
data-check:
	$(Q)$(LRVNE_PY) tools/gamedata.py check

# Everything made from the original game outside ../build/ (the ignored paths of ../.gitignore)
DATA_GENERATED := ../resources/original ../resources/derived
.PHONY: data-clean distclean
data-clean:
	rm -rf $(DATA_GENERATED)
distclean: clean data-clean

# ---------------------------------------------------------------------------------------------
# The pack: fonts (lrvne's xfont from the X11 bitmap fonts it carries) and everything the engine
# needs from the original game (tools/mkpack.py, on lrvne's pack writer). The same for every
# target. The pack is named after the program, which is where a backend looks for it; which game
# it is, is in its profile (GAME=<id> chooses when mkpack.py knows several).
# ---------------------------------------------------------------------------------------------
X11FONTS ?= $(LRVNE)/fonts/x11
ORIGINAL ?= ../resources/original
PAK      ?= $(BUILDROOT)/$(APP_NAME).pak
GAME     ?=
.PHONY: pack
pack:
	$(Q)mkdir -p $(BUILDROOT)/fonts
	$(Q)$(LRVNE_TOOL) xfont --no-bold -o $(BUILDROOT)/fonts/ank8.xfnt $(X11FONTS)/8x16rk.bdf >/dev/null
	$(Q)$(LRVNE_TOOL) xfont --no-bold -o $(BUILDROOT)/fonts/k16.xfnt $(X11FONTS)/jiskan16.bdf >/dev/null
	$(Q)$(LRVNE_PY) tools/mkpack.py --original $(ORIGINAL) --fonts $(BUILDROOT)/fonts \
	    $(if $(GAME),--game $(GAME)) -o $(PAK)

# ---------------------------------------------------------------------------------------------
# Release archives. The version is engine/version.h's (the release is tagged v<version>).
# `make TARGET=sdl3 dist`: $(BUILD)/adv98x-<version>-<DIST_NAME>.tar.gz, which unpacks to
# Adv98X/{adv98x, ReadMe.txt, LICENSE, LICENSE.ymfm}: the stripped executable, the player's
# ReadMe (dist/ReadMe.txt, @VERSION@ replaced) and the licences of what is in the executable.
# The pack is not in it: it is the game's data, which the player builds from their own copy
# (the ReadMe says how). A target that can be released has a name for its archives
# (LRVNE_DIST_NAME of lrvne/mk/target/<TARGET>.mk). `make TARGET=amiga|warpos|aros dist`:
# $(BUILD)/adv98x-<version>-<target>.lha (AROS: -aros-x86_64), which unpacks to the drawer
# Adv98X/{adv98x, ReadMe.txt, LICENSE}, no pack either.
# `make dist-src`: the committed tree at HEAD with the lrvne submodule's at its HEAD (git archive
# leaves a submodule out; the repository holds no game data).
# ---------------------------------------------------------------------------------------------
DIST_README ?= dist/ReadMe.txt
DIST_STRIP  ?= strip
DIST        := $(BUILD)/adv98x-$(AX_VERSION)-$(LRVNE_DIST_NAME).tar.gz
DISTDIR     := $(BUILD)/dist
SRCDIST     := $(abspath $(BUILDROOT))/adv98x-$(AX_VERSION)-src.tar.gz
SRCDIST_TMP := $(abspath $(BUILDROOT))/dist-src
# no local user or group names in the archive (GNU tar / bsdtar spell it differently)
TAR_ANON    := $(if $(shell tar --version 2>/dev/null | grep GNU),--owner=0 --group=0 --numeric-owner,--uid 0 --gid 0 --uname '' --gname '')
.PHONY: dist dist-src
ifneq ($(AMIGA_FAMILY),)
# the Amiga family's .lha (lrvne's lrvne-dist; AMIGA_DIST above); the ReadMe's title with the version
dist: lrvne-dist
$(BUILDROOT)/$(TARGET)/ReadMe-title.txt: $(AMIGA_DIST)/title.txt engine/version.h
	@mkdir -p $(dir $@)
	$(Q)sed 's/@VERSION@/$(AX_VERSION)/g' $< >$@
else
dist: $(EXE)
	$(Q)test -n "$(LRVNE_DIST_NAME)" || { echo "dist: no release archive for TARGET=$(TARGET)"; exit 1; }
	$(Q)rm -rf $(DISTDIR) $(DIST)
	$(Q)mkdir -p $(DISTDIR)/Adv98X
	$(Q)cp $(EXE) $(DISTDIR)/Adv98X/
	$(if $(DIST_STRIP),$(Q)$(DIST_STRIP) $(DISTDIR)/Adv98X/adv98x$(EXESUF))
	$(Q)sed 's/@VERSION@/$(AX_VERSION)/g' $(DIST_README) >$(DISTDIR)/Adv98X/ReadMe.txt
	$(Q)cp ../LICENSE $(DISTDIR)/Adv98X/LICENSE
	$(Q)cp $(LRVNE)/third_party/ymfm/LICENSE $(DISTDIR)/Adv98X/LICENSE.ymfm
	@echo "  TAR   $(DIST)"
	$(Q)cd $(DISTDIR) && tar $(TAR_ANON) -czf $(abspath $(DIST)) Adv98X
	$(Q)tar -tzvf $(DIST)
endif
dist-src:
	@echo "  TAR   $(SRCDIST)"
	$(Q)rm -rf $(SRCDIST_TMP) && mkdir -p $(SRCDIST_TMP)
	$(Q)git -C .. archive --prefix=adv98x-$(AX_VERSION)/ HEAD | tar -xf - -C $(SRCDIST_TMP)
	$(Q)git -C $(LRVNE) archive --prefix=adv98x-$(AX_VERSION)/source/lrvne/ HEAD | tar -xf - -C $(SRCDIST_TMP)
	$(Q)tar $(TAR_ANON) -czf $(SRCDIST) -C $(SRCDIST_TMP) adv98x-$(AX_VERSION)
	$(Q)rm -rf $(SRCDIST_TMP)
