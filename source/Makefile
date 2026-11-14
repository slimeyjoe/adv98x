# SPDX-License-Identifier: GPL-3.0-or-later
# Adv98X engine - GNU Make 4
#
#   make [TARGET=host|sdl3] [V=1]   build the engine (default: host = the null backend, for tests)
#   make data SRC="..."            import the original game from your copies (../docs/game-data.md)
#                                  into ../resources/original/ and derive ../resources/derived/
#   make pack                      build the game pack ../build/nova.pak from the imported game
#   make TARGET=host test          build and run the conformance tests
#   make clean                     remove ../build/
#   make data-clean                remove everything made from the game outside ../build/
#   make distclean                 clean + data-clean: only the committed files are left
#
# Each target is described by config/<TARGET>.mk (compiler, flags, backend directory).

TARGET ?= host
# Everything built goes to the top-level build/ (../build from here): build/<TARGET>/ for each
# target, the pack and its intermediates (fonts) in build/ itself.
BUILDROOT := ../build
BUILD     := $(BUILDROOT)/$(TARGET)
include config/$(TARGET).mk

EXE      ?= $(BUILD)/adv98x$(EXESUF)

ENGINE_SRCS  := $(sort $(wildcard engine/*.c engine/*/*.c))
BACKEND_DIRS ?= backends/$(BACKEND)
BACKEND_SRCS := $(sort $(foreach d,$(BACKEND_DIRS) backends/common,$(wildcard $(d)/*.c)))
EXTRA_SRCS   ?=
# Control mode (test automation protocol) is built into the host and SDL3 backends.
CONTROL      ?= 0
ifeq ($(CONTROL),1)
CONTROL_SRCS := $(wildcard backends/control/*.c)
else
CONTROL_SRCS :=
endif
ALL_SRCS     := $(ENGINE_SRCS) $(BACKEND_SRCS) $(CONTROL_SRCS) $(EXTRA_SRCS)

obj_of  = $(patsubst %.c,$(BUILD)/%.o,$(patsubst %.cpp,$(BUILD)/%.o,$(patsubst %.s,$(BUILD)/%.o,$(1))))
OBJS    := $(call obj_of,$(ALL_SRCS))
DEPS    := $(OBJS:.o=.d)

INCLUDES := -I. -Iengine -Ihal -Ibackends/common -Ibackends/control $(addprefix -I,$(BACKEND_DIRS))

ifeq ($(V),1)
Q :=
else
Q := @
endif

.DEFAULT_GOAL := all
.PHONY: all clean test
.SECONDARY:

all: $(EXE)

$(EXE): $(OBJS)
	@echo "  LINK  $@"
	$(Q)$(LINK)

$(BUILD)/%.o: %.c
	@mkdir -p $(dir $@)
	@echo "  CC    $<"
	$(Q)$(COMPILE_C)

$(BUILD)/%.o: %.cpp
	@mkdir -p $(dir $@)
	@echo "  CXX   $<"
	$(Q)$(COMPILE_CXX)

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
DEPS      += $(patsubst tests/%.c,$(BUILD)/tests/%.d,$(TEST_SRCS))
ENGINE_OBJS := $(call obj_of,$(ENGINE_SRCS) $(EXTRA_SRCS))

$(BUILD)/tests/%$(EXESUF): $(BUILD)/tests/%.o $(ENGINE_OBJS)
	@mkdir -p $(dir $@)
	@echo "  LINK  $@"
	$(Q)$(LINK_TEST)

test: $(TEST_EXES) $(EXE)
	$(Q)tests/run.sh $(BUILD)

# ---------------------------------------------------------------------------------------------
# The game's data (../docs/game-data.md), which the repository does not carry.
#   make data SRC="DIR-or-image ..."  [DATA_PY=python with capstone/unicorn/pillow/numpy]
# imports the releases into ../resources/original/ (checked against ../resources/inventory.tsv)
# and derives ../resources/derived/ (tools/gamedata.py derive; the parts that need a module
# DATA_PY lacks are skipped with a note).
# ---------------------------------------------------------------------------------------------
DATA_PY  ?=
.PHONY: data data-derive data-check
data:
	$(Q)test -n "$(SRC)" || { echo "data: set SRC=<your copies of the game> (../docs/game-data.md)"; exit 1; }
	$(Q)python3 -I tools/gamedata.py import $(SRC)
	$(Q)python3 -I tools/gamedata.py derive $(if $(DATA_PY),--python $(DATA_PY)) $(DATA_PARTS)
data-derive:
	$(Q)python3 -I tools/gamedata.py derive $(if $(DATA_PY),--python $(DATA_PY)) $(DATA_PARTS)
data-check:
	$(Q)python3 -I tools/gamedata.py check

# Everything made from the original game outside ../build/ (the ignored paths of ../.gitignore)
DATA_GENERATED := ../resources/original ../resources/derived
.PHONY: data-clean distclean
data-clean:
	rm -rf $(DATA_GENERATED)
distclean: clean data-clean

# ---------------------------------------------------------------------------------------------
# The pack: fonts (tools/xfont.py from the X11 bitmap fonts in fonts/x11) and everything the
# engine needs from the original game (tools/mkpack.py). The same for every target.
# ---------------------------------------------------------------------------------------------
X11FONTS ?= fonts/x11
ORIGINAL ?= ../resources/original
PAK      ?= $(BUILDROOT)/nova.pak
.PHONY: pack
pack:
	$(Q)mkdir -p $(BUILDROOT)/fonts
	$(Q)python3 -I tools/xfont.py --no-bold -o $(BUILDROOT)/fonts/ank8.xfnt $(X11FONTS)/8x16rk.bdf >/dev/null
	$(Q)python3 -I tools/xfont.py --no-bold -o $(BUILDROOT)/fonts/k16.xfnt $(X11FONTS)/jiskan16.bdf >/dev/null
	$(Q)python3 -I tools/mkpack.py --original $(ORIGINAL) --fonts $(BUILDROOT)/fonts -o $(PAK)

-include $(DEPS)
