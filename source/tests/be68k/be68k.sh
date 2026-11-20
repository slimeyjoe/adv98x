#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# The engine on a big-endian CPU: be68k.c (the whole engine and lrvne's library on a HAL of its
# own) built for m68k Linux and run under qemu's user-mode emulator as a 68040, against the same
# program built natively, which in turn must match the headless backend (compare.py).
#
#   tests/be68k/be68k.sh ADV98X PAK [BUILD-DIR]     (make TARGET=host be68k)
#
# ADV98X is the host build (build/host/adv98x), PAK the game pack. Needs a GNU cross compiler
# for m68k Linux and qemu-m68k (no C library for the 68k: rt.c is one); other names than the
# defaults go in M68K_CC and QEMU_M68K. BE68K_TICKS is the length of each run (default 30000
# frames), BE68K_TIMEOUT the seconds after which a run is stopped (default 600). Exits with 77
# when a tool or the pack is missing ("skipped"). About 20 s on a PC.
set -u
exe=${1:?usage: be68k.sh ADV98X PAK [BUILD-DIR]}
pak=${2:?usage: be68k.sh ADV98X PAK [BUILD-DIR]}
here=$(cd "$(dirname "$0")" && pwd)
src=$(cd "$here/../.." && pwd)
out=${3:-$src/../build/host/be68k}
M68K_CC=${M68K_CC:-m68k-linux-gnu-gcc}
QEMU_M68K=${QEMU_M68K:-qemu-m68k}
CC=${CC:-cc}
ticks=${BE68K_TICKS:-30000}
limit=${BE68K_TIMEOUT:-600}
rate=11025

for tool in "$M68K_CC" "$QEMU_M68K" "$CC"; do
    command -v "$tool" >/dev/null 2>&1 || { echo "be68k: $tool not found, skipped"; exit 77; }
done
[ -f "$pak" ] && [ -x "$exe" ] || { echo "be68k: no $exe or $pak, skipped"; exit 77; }
mkdir -p "$out"

lrvne=$src/lrvne
srcs=$(ls "$src"/engine/*.c "$src"/engine/*/*.c "$lrvne"/src/*/*.c "$lrvne"/src/*/*/*.c 2>/dev/null |
       grep -v '/engine/main\.c$')
srcs="$srcs $lrvne/backends/common/autoplay.c $here/be68k.c"
inc="-I$src/engine -I$lrvne/include -I$lrvne/backends/common -I$here"

# the m68k program: freestanding, its C library rt.c; objects one by one (an error names the file)
m68k_flags="-std=c99 -m68040 -O2 -ffreestanding -fno-builtin -fno-tree-loop-distribute-patterns
            -DBE68K_FREESTANDING -I$here/include $inc"
objs=
for f in $srcs $here/rt.c; do
    o=$out/m68k-$(basename "$(dirname "$f")")-$(basename "$f" .c).o
    $M68K_CC $m68k_flags -c -o "$o" "$f" || { echo "be68k: $f does not compile for m68k"; exit 1; }
    objs="$objs $o"
done
$M68K_CC -m68040 -nostdlib -static -o "$out/be68k-m68k" $objs -lgcc -Wl,-z,noexecstack ||
    { echo "be68k: link failed"; exit 1; }
# the same program natively, with the host's C library
$CC -std=c99 -O2 -D_POSIX_C_SOURCE=200809L $inc -o "$out/be68k-native" $srcs ||
    { echo "be68k: the native build failed"; exit 1; }

rc=0
snaps=$(i=500; while [ $i -le "$ticks" ]; do printf '%s,' $i; i=$((i + 500)); done)
langs=$(python3 -I "$here/../../tools/gamedir.py" get PACK.languages) || exit 1
first=${langs%% *}
for lang in $langs; do
    spec=$out/spec-$lang.txt
    # random presses of return, up, down and esc (menus, waits, the name entry), Shift held
    # to skip text after the opening, a cursor key held for a while (the mouse's key
    # emulation); the languages after the first with another seed
    seed=11; [ $lang = "$first" ] || seed=23
    printf 'rand:%s shift:2000-%s right:3000-3200 snap:%s\n' $seed "$ticks" "${snaps%,}" >"$spec"
    rm -rf "$out/storage-$lang" && mkdir -p "$out/storage-$lang"
    "$exe" --pak "$pak" --lang $lang --autoplay "@$spec" --max-ticks "$ticks" --opn lite \
        --rate $rate --wav "$out/host-$lang.wav" --storage "$out/storage-$lang" \
        >"$out/host-$lang.jsonl" 2>/dev/null
    timeout "$limit" "$out/be68k-native" "$pak" "$spec" "$ticks" $lang $rate >"$out/native-$lang.txt"
    timeout "$limit" "$QEMU_M68K" -cpu m68040 "$out/be68k-m68k" "$pak" "$spec" "$ticks" $lang $rate \
        >"$out/m68k-$lang.txt" 2>"$out/m68k-$lang.log"
    python3 -I "$here/compare.py" $lang "$out/m68k-$lang.txt" "$out/native-$lang.txt" \
        "$out/host-$lang.jsonl" "$out/host-$lang.wav" "$out/storage-$lang" || rc=1
done
exit $rc
