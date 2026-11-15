#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Runs AmigaDOS commands in hosted AROS (linux-x86_64, ABIv11), headless: the rig of
# tests/aros/check_aros.py (docs/amiga.md "Testing").
#
#   aros.sh RUNDIR [SECONDS] < commands
#
# AROS_HOSTED (environment) is the unpacked hosted system (AROS-202609-linux-x86_64-system).
# It is copied to RUNDIR/AROS (AROS writes into SYS:, so no two runs share a tree); the files
# listed in AROS_FILES="path ..." go to SYS:Work/, which is assigned Work: and is the current
# directory. The commands on stdin become S:User-Startup:
#   plain lines   run with their output appended to SYS:out.txt (RUNDIR/out.txt)
#   "!" lines     go in verbatim (without the "!")
# The run ends after the last command or after SECONDS (default 120); the AROS process, the
# X server and the sound sink are gone when this returns. Display: a headless X server
# (xwfb-run, from xwayland-run). Sound: hosted AHI plays through the host's ALSA, sent by
# RUNDIR/.asoundrc to a private PipeWire null sink that exists only during the run, recorded
# to RUNDIR/audio.wav (without pactl: no sink, and the program should be run with AUDIO=none).
set -u
die() { echo "aros.sh: $*" >&2; exit 2; }

# _inner RUNDIR SECONDS: inside the X session: boot, wait for the end marker, stop
if [ "${1:-}" = _inner ]; then
    R=$2 secs=$3 t=0
    cd "$R/AROS" || exit 1
    # its own process group: AROSBootstrap forks, and the whole group goes at the end
    setsid boot/linux/AROSBootstrap >"$R/boot.log" 2>&1 &
    AROS_PID=$!
    trap 'kill -- -$AROS_PID 2>/dev/null; sleep 1; kill -9 -- -$AROS_PID 2>/dev/null' EXIT INT TERM
    while [ $t -lt "$secs" ]; do
        sleep 1
        t=$((t + 1))
        kill -0 $AROS_PID 2>/dev/null || { echo "aros.sh: AROS ended by itself at ${t}s"; break; }
        [ -e "$R/AROS/done.marker" ] && { echo "aros.sh: done at ${t}s"; break; }
    done
    [ $t -ge "$secs" ] && echo "aros.sh: timeout at ${t}s"
    exit 0
fi

R=${1:?usage: aros.sh RUNDIR [SECONDS] < commands}
secs=${2:-120}
[ -n "${AROS_HOSTED:-}" ] || die "set AROS_HOSTED to the hosted AROS system directory"
[ -x "$AROS_HOSTED/boot/linux/AROSBootstrap" ] || die "no hosted AROS in $AROS_HOSTED"
command -v xwfb-run >/dev/null || die "xwfb-run is missing (xwayland-run)"
R=$(mkdir -p "$R" && cd "$R" && pwd) || die "cannot make $1"
rm -rf "$R/AROS" "$R/out.txt" "$R/run.log"
cp -a "$AROS_HOSTED" "$R/AROS" || die "cannot copy the hosted system"
mkdir -p "$R/AROS/Work"
for f in ${AROS_FILES:-}; do
    cp -a "$f" "$R/AROS/Work/" || die "cannot copy $f"
done
{
    echo 'Assign Work: SYS:Work'
    echo 'CD Work:'
    while IFS= read -r line; do
        case $line in
        '!'*) printf '%s\n' "${line#!}" ;;
        '') ;;
        *) printf 'Echo "%% %s" >>SYS:out.txt\n%s >>SYS:out.txt\n' "${line//\"/*\"}" "$line" ;;
        esac
    done
    echo 'Echo done >SYS:done.marker'
} >"$R/AROS/S/User-Startup"
ln -sf AROS/out.txt "$R/out.txt"

if command -v pactl >/dev/null && command -v pw-record >/dev/null; then
    sink=aros_rig_$$
    mod=$(pactl load-module module-null-sink sink_name="$sink" \
              sink_properties=device.description="$sink") || die "cannot create a null sink"
    printf 'pcm.!default {\n    type pipewire\n    playback_node "%s"\n}\n' "$sink" >"$R/.asoundrc"
    export HOME=$R
    pw-record --target "$sink" -P '{ stream.capture.sink=true }' "$R/audio.wav" \
        >"$R/record.log" 2>&1 &
    rec=$!
    trap 'kill $rec 2>/dev/null; wait $rec 2>/dev/null; pactl unload-module $mod' EXIT
fi
timeout -k 10 $((secs + 30)) xwfb-run -- "$0" _inner "$R" "$secs" >"$R/run.log" 2>&1
cat "$R/run.log"
