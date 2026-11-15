#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Run the conformance tests. $1 = the build directory (../build/host), holding tests/ and the
# engine. The tests that need the imported game (make data) or the pack (make pack) are skipped
# with a note when those are missing.
# $2 = e2e: instead, play every story and ending through the engine and the original
# interpreter and compare (check_vm.py's routes; long).
set -u
BUILD=${1:-../build/host}
MODE=${2:-}
BIN=$BUILD/tests
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
PAK=${PAK:-$ROOT/build/adv98x.pak}
PY=${PYTHON:-python3}
# the emulation references (AdvBIOS's own code under unicorn) need a Python with unicorn:
# EMU_PYTHON, else the research venv when it exists (docs/re/README.md "Tools")
EMU_PY=${EMU_PYTHON:-python3}
ORIGINAL=$ROOT/resources/original
OV1=$ROOT/resources/derived/exe/NV.OV1
FONTS=$ROOT/build/fonts
rc=0

run() {
    echo "== $*"
    "$@" || rc=1
}

if [ "$MODE" = e2e ]; then
    if [ -x "$EMU_PY" ] && "$EMU_PY" -c 'import unicorn' 2>/dev/null && [ -f "$PAK" ] &&
       [ -f "$ROOT/resources/derived/exe/NV.OVL" ]; then
        run "$EMU_PY" -I "$HERE/check_vm.py" "$BIN/test_vm" "$PAK" "$ORIGINAL" "$FONTS" \
            route1 route2a route2b route2c route3 route1_en route2a_en route2b_en route2c_en route3_en
    else
        echo "e2e: needs a Python with unicorn (EMU_PYTHON), $PAK and the unpacked NV.OVL"
        rc=1
    fi
    if [ $rc -eq 0 ]; then echo "E2E PASSED"; else echo "E2E FAILED"; fi
    exit $rc
fi

skip() {
    echo "== $1: skipped ($2)"
}

# ---- with the imported game ----------------------------------------------------------------
if $PY -I "$HERE/../tools/gamedata.py" check >/dev/null 2>&1; then
    HAVE_GAME=1
else
    HAVE_GAME=
    echo "note: the original game is not imported (make data SRC=...): game tests skipped"
fi
if [ -n "$HAVE_GAME" ] && [ -f "$PAK" ]; then
    run $PY -I "$HERE/check_pack.py" "$BIN/test_pack" "$PAK"
else
    skip check_pack "needs the game and $PAK (make pack)"
fi
if [ -n "$HAVE_GAME" ]; then
    run $PY -I "$HERE/check_gpc.py" "$BIN/test_gpc" "$ORIGINAL"
    run $PY -I "$HERE/check_mes.py" "$BIN/test_mes" "$ORIGINAL"
    run $PY -I "$HERE/check_usd.py" "$BIN/test_usd" "$ORIGINAL"
else
    skip "check_gpc, check_mes" "need the game"
fi
if [ -n "$HAVE_GAME" ] && [ -f "$PAK" ]; then
    # the presentation test's frame sequence, through the headless backend's present path in
    # the video mode the engine opens (it opens the pack first: the window's title is the game's)
    echo "== adv98x --present-test"
    n=$("$BUILD/adv98x" --pak "$PAK" --present-test | grep -c '"ev":"snap"') || rc=1
    [ "${n:-0}" -gt 0 ] && echo "present-test: $n snapshots" || { echo "present-test: no snapshots"; rc=1; }
    run $PY -I "$HERE/check_run.py" "$BUILD/adv98x" "$PAK" "$ORIGINAL" --lang ja --frames 40000
    run $PY -I "$HERE/check_run.py" "$BUILD/adv98x" "$PAK" "$ORIGINAL" --lang en --frames 40000
    # the sound path end to end (service call, sequencer, OPN core): a song is heard
    echo "== render smoke: NV01 through the game's sound path"
    "$BUILD/adv98x" --pak "$PAK" --render-wav "$BIN/nv01.wav" --song NV01 --seconds 4 2>/dev/null &&
        $PY -I -c 'import sys,wave,struct; w=wave.open(sys.argv[1]); n=w.getnframes(); d=struct.unpack("<%dh"%n,w.readframes(n)); p=max(abs(x) for x in d); print("render: %d frames at %d Hz, peak %d" % (n, w.getframerate(), p)); sys.exit(0 if p > 1000 and n > 3*w.getframerate() else 1)' "$BIN/nv01.wav" || rc=1
    # --volume scales every sample by v/100 (as v*256/100 / 256, truncated toward zero)
    "$BUILD/adv98x" --pak "$PAK" --render-wav "$BIN/nv01-30.wav" --song NV01 --seconds 4 --volume 30 2>/dev/null &&
        $PY -I -c 'import sys,wave,struct
def rd(f):
    w=wave.open(f); n=w.getnframes(); return struct.unpack("<%dh"%n,w.readframes(n))
a,b=rd(sys.argv[1]),rd(sys.argv[2]); g=30*256//100
bad=sum(1 for x,y in zip(a,b) if y!=int(x*g/256))
print("render --volume 30: %d samples, %d not scaled by %d/256" % (len(b), bad, g)); sys.exit(0 if len(a)==len(b) and not bad else 1)' "$BIN/nv01.wav" "$BIN/nv01-30.wav" || rc=1
    run "$HERE/e2e/stories.sh" "$BUILD/adv98x" "$PAK" "$ORIGINAL" ja
    run "$HERE/e2e/stories.sh" "$BUILD/adv98x" "$PAK" "$ORIGINAL" en
    # the SDL3 backend's presentation, offscreen (when it is built: make TARGET=sdl3)
    SDL3=${SDL3_EXE:-$ROOT/build/sdl3/adv98x}
    if [ -x "$SDL3" ]; then
        run $PY -I "$HERE/e2e/present.py" "$SDL3" "$PAK"
    else
        skip present "needs the SDL3 build ($SDL3)"
    fi
else
    skip check_run "needs the game and $PAK"
fi

# ---- against AdvBIOS's own code under emulation --------------------------------------------
if [ -x "$EMU_PY" ] && "$EMU_PY" -c 'import unicorn' 2>/dev/null && [ -f "$OV1" ]; then
    if [ -f "$PAK" ] && [ -f "$FONTS/k16.xfnt" ]; then
        run "$EMU_PY" -I "$HERE/check_text.py" "$BIN/test_text" "$PAK" "$FONTS"
    else
        skip check_text "needs $PAK and its fonts (make pack)"
    fi
    run "$EMU_PY" -I "$HERE/check_palette.py" "$BIN/test_palette"
    if [ -f "$PAK" ] && [ -f "$FONTS/k16.xfnt" ] && [ -f "$ROOT/resources/derived/exe/NV.OVL" ]; then
        run "$EMU_PY" -I "$HERE/check_vm.py" "$BIN/test_vm" "$PAK" "$ORIGINAL" "$FONTS"
    else
        skip check_vm "needs $PAK, its fonts and the unpacked NV.OVL (make data, make pack)"
    fi
else
    skip "check_text, check_palette, check_vm" "need a Python with unicorn (EMU_PYTHON) and $OV1 (make data)"
fi

if [ $rc -eq 0 ]; then echo "ALL TESTS PASSED"; else echo "TESTS FAILED"; fi
exit $rc
