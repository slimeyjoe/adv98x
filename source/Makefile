# SPDX-License-Identifier: GPL-3.0-or-later
# Adv98X engine - GNU Make 4
#
#   make [TARGET=host|sdl3] [V=1]   build the engine (default: host = the headless backend, for
#                                  tests; sdl3 = the player)
#   make data SRC="..."            import the original game from your copies (../docs/game-data.md)
#                                  into ../resources/original/ and derive ../resources/derived/
#   make pack                      build the game pack $(PAK) from the imported game
#   make TARGET=host test [SAN=1]  build and run the conformance tests
#   make TARGET=sdl3 dist          the player's archive ../build/sdl3/adv98x-<version>-<host>.tar.gz
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

.DEFAULT_GOAL := all
include $(LRVNE)/mk/lrvne.mk

.PHONY: all clean test e2e
all: $(EXE)

clean:
	rm -rf $(BUILDROOT)

# ---------------------------------------------------------------------------------------------
# Conformance tests (host target). Every test compares the engine with data from the original
# code or a verified reference tool (source/tools/, re-tools/), never with its own output.
# tests/run.sh runs the data-free tests first; those that need the imported game are skipped
# with a note when it is missing.
# ---------------------------------------------------------------------------------------------
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
# (LRVNE_DIST_NAME of lrvne/mk/target/<TARGET>.mk).
# `make dist-src`: the committed tree at HEAD with the lrvne submodule's at its HEAD (git archive
# leaves a submodule out; the repository holds no game data).
# ---------------------------------------------------------------------------------------------
AX_VERSION := $(shell sed -n 's/^\#define AX_VERSION *"\(.*\)"/\1/p' engine/version.h)
DIST_README ?= dist/ReadMe.txt
DIST_STRIP  ?= strip
DIST        := $(BUILD)/adv98x-$(AX_VERSION)-$(LRVNE_DIST_NAME).tar.gz
DISTDIR     := $(BUILD)/dist
SRCDIST     := $(abspath $(BUILDROOT))/adv98x-$(AX_VERSION)-src.tar.gz
SRCDIST_TMP := $(abspath $(BUILDROOT))/dist-src
# no local user or group names in the archive (GNU tar / bsdtar spell it differently)
TAR_ANON    := $(if $(shell tar --version 2>/dev/null | grep GNU),--owner=0 --group=0 --numeric-owner,--uid 0 --gid 0 --uname '' --gname '')
.PHONY: dist dist-src
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
dist-src:
	@echo "  TAR   $(SRCDIST)"
	$(Q)rm -rf $(SRCDIST_TMP) && mkdir -p $(SRCDIST_TMP)
	$(Q)git -C .. archive --prefix=adv98x-$(AX_VERSION)/ HEAD | tar -xf - -C $(SRCDIST_TMP)
	$(Q)git -C $(LRVNE) archive --prefix=adv98x-$(AX_VERSION)/source/lrvne/ HEAD | tar -xf - -C $(SRCDIST_TMP)
	$(Q)tar $(TAR_ANON) -czf $(SRCDIST) -C $(SRCDIST_TMP) adv98x-$(AX_VERSION)
	$(Q)rm -rf $(SRCDIST_TMP)
