#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# check_kit.sh KIT.zip ORIGINAL PAK: the game's pack-building kit (tools/mkkit.py), unpacked in a
# directory of its own with nothing else, imports the game from ORIGINAL (the imported tree used
# as the player's copy) and builds a pack, which must be byte for byte PAK (`make pack`'s).
set -u
abs() { case "$1" in /*) echo "$1" ;; *) echo "$PWD/$1" ;; esac; }
kit=$(abs "$1") original=$(abs "$2") pak=$(abs "$3")
PY=${PYTHON:-python3}
d=$(mktemp -d)
trap 'rm -rf "$d"' EXIT
$PY -I -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$kit" "$d" || exit 1
top=$(ls "$d")
[ "$(echo "$top" | wc -l)" -eq 1 ] || { echo "check_kit: the kit is not one directory"; exit 1; }
(cd "$d/$top" && env -u GAME_DIR $PY -I makepak.py "$original" -o "$d/kit.pak" >"$d/log" 2>&1) ||
    { echo "check_kit: makepak failed:"; cat "$d/log"; exit 1; }
n=$($PY -I -c 'import sys, zipfile; print(len(zipfile.ZipFile(sys.argv[1]).namelist()))' "$kit")
if cmp -s "$d/kit.pak" "$pak"; then
    echo "check_kit: $(basename "$kit"): $n files; from the player's files alone, the same pack: OK"
else
    echo "check_kit: the kit's pack differs from $pak"
    exit 1
fi
