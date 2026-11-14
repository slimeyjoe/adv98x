#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# stories.sh ADV98X PAK ORIGINAL LANG: a fresh install played through the three stories in turn
# by the exploring player (explore.py): the 1st story must end by writing FLAG3 (the 2nd story
# unlocked), the 2nd story FLAG4, the 3rd story FLAG5 (docs/re/script-catalog.md §3).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
S=$(mktemp -d)
PY=${PYTHON:-python3}
e() { $PY -I "$HERE/explore.py" "$1" "$2" "$3" --lang "$4" --storage "$S" --frames 600000 "$5" "$6" "$7" "$8"; }
rc=0
e "$1" "$2" "$3" "$4" --until-save FLAG3 --title-pick 0 | head -1 || rc=1
e "$1" "$2" "$3" "$4" --until-save FLAG4 --title-pick 1 | head -1 || rc=1
e "$1" "$2" "$3" "$4" --until-save FLAG5 --title-pick 2 | head -1 || rc=1
for f in FLAG3 FLAG4 FLAG5; do [ -f "$S/$f" ] || { echo "stories: $f was not written"; rc=1; }; done
rm -rf "$S"
[ $rc -eq 0 ] && echo "stories ($4): FLAG3, FLAG4, FLAG5 written in turn: OK" || echo "stories ($4): FAILED"
exit $rc
