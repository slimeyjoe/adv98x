#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Run the conformance tests. $1 = the build directory (../build/host), holding tests/ and the
# engine. The data-free tests run first; the ones that need the imported game (make data) or
# the pack (make pack) are skipped with a note when those are missing.
set -u
BUILD=${1:-../build/host}
BIN=$BUILD/tests
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
PAK=${PAK:-$ROOT/build/nova.pak}
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

skip() {
    echo "== $1: skipped ($2)"
}

# ---- data-free -----------------------------------------------------------------------------
# the presentation test's frame sequence runs through the null backend's present path
echo "== adv98x --present-test"
n=$("$BUILD/adv98x" --present-test | grep -c '"ev":"snap"') || rc=1
[ "${n:-0}" -gt 0 ] && echo "present-test: $n snapshots" || { echo "present-test: no snapshots"; rc=1; }

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
else
    skip check_gpc "needs the game"
fi

# ---- against AdvBIOS's own code under emulation --------------------------------------------
if [ -x "$EMU_PY" ] && "$EMU_PY" -c 'import unicorn' 2>/dev/null && [ -f "$OV1" ]; then
    if [ -f "$PAK" ] && [ -f "$FONTS/k16.xfnt" ]; then
        run "$EMU_PY" -I "$HERE/check_text.py" "$BIN/test_text" "$PAK" "$FONTS"
    else
        skip check_text "needs $PAK and its fonts (make pack)"
    fi
    run "$EMU_PY" -I "$HERE/check_palette.py" "$BIN/test_palette"
else
    skip "check_text, check_palette" "need a Python with unicorn (EMU_PYTHON) and $OV1 (make data)"
fi

if [ $rc -eq 0 ]; then echo "ALL TESTS PASSED"; else echo "TESTS FAILED"; fi
exit $rc
