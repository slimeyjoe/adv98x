#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# stories.sh ADV98X PAK ORIGINAL LANG: a fresh install played through the three stories in turn
# by the exploring player (explore.py), in one run: the 1st story must end by writing FLAG3 (the
# 2nd story unlocked), the 2nd story FLAG4, the 3rd story FLAG5 (docs/re/script-catalog.md §3).
# Each ending loops for ever, as in the original; the player leaves it with the reset button,
# after which the title must offer the story just unlocked.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
S=$(mktemp -d)
PY=${PYTHON:-python3}
rc=0
out=$($PY -I "$HERE/explore.py" "$1" "$2" "$3" --lang "$4" --storage "$S" --frames 1800000 \
      --chain FLAG3:0,FLAG4:1,FLAG5:2) || rc=1
echo "$out" | head -1
for f in FLAG3 FLAG4 FLAG5; do [ -f "$S/$f" ] || { echo "stories: $f was not written"; rc=1; }; done
rm -rf "$S"
[ $rc -eq 0 ] && echo "stories ($4): FLAG3, FLAG4, FLAG5 written in turn, reset after each ending: OK" || echo "stories ($4): FAILED"
exit $rc
