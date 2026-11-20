#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# stories.sh ADV98X PAK ORIGINAL LANG FILE:ITEM...: a fresh install played through the game's
# stories in turn by the exploring player (explore.py), in one run. FILE:ITEM is a story, in play
# order: the title menu's ITEM starts it, and it must end by writing the unlock file FILE (the
# game's tests/cases.py STORIES). An ending may loop for ever, as in the original; the player
# leaves it with the reset button, after which the title must offer the story just unlocked.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
exe=$1 pak=$2 original=$3 lang=$4
shift 4
chain=$(echo "$*" | tr ' ' ,)
S=$(mktemp -d)
PY=${PYTHON:-python3}
rc=0
out=$($PY -I "$HERE/explore.py" "$exe" "$pak" "$original" --lang "$lang" --storage "$S" \
      --frames 1800000 --chain "$chain") || rc=1
echo "$out" | head -1
files=
for story in "$@"; do
    f=${story%%:*}
    files="$files $f"
    [ -f "$S/$f" ] || { echo "stories: $f was not written"; rc=1; }
done
rm -rf "$S"
[ $rc -eq 0 ] && echo "stories ($lang):$files written in turn, reset after each ending: OK" || echo "stories ($lang): FAILED"
exit $rc
