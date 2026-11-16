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
# The run ends after the last command: it writes a marker, which the host waits for (or for
# AROS to end). SECONDS (default 120) is the backstop for a run that is stuck, never the end of
# a normal one. The AROS process, the X server and the sound sink are gone when this returns.
# Exit status: 0 the commands finished; 3 AROS ended before they did; 4 the X server could not
# start; 124 the backstop ended the run (run.log says which). Display: a headless X server
# (xwfb-run, from xwayland-run). Sound: hosted AHI plays through the host's ALSA, sent by
# RUNDIR/.asoundrc to a private PipeWire null sink that exists only during the run, recorded
# to RUNDIR/audio.wav (without pactl: no sink, and the program should be run with AUDIO=none).
set -u
die() { echo "aros.sh: $*" >&2; exit 2; }

# _inner RUNDIR: inside the X session: boot, wait for the end, stop. The end is an event: the
# marker the last command writes, or AROS ending; the caller's `timeout` is the backstop.
# Exit status 0 / 3 as aros.sh's.
if [ "${1:-}" = _inner ]; then
    R=$2
    cd "$R/AROS" || exit 1
    # its own process group: AROSBootstrap forks, and the whole group goes at the end (TERM,
    # wait for the leader, KILL what is left)
    setsid boot/linux/AROSBootstrap >"$R/boot.log" 2>&1 &
    AROS_PID=$!
    echo $AROS_PID >"$R/aros.pgid"     # for the caller, should the backstop kill this shell
    trap 'kill -- -$AROS_PID 2>/dev/null; wait $AROS_PID 2>/dev/null; kill -9 -- -$AROS_PID 2>/dev/null' EXIT INT TERM
    while [ ! -e "$R/AROS/done.marker" ] && kill -0 $AROS_PID 2>/dev/null; do
        sleep 0.1
    done
    if [ -e "$R/AROS/done.marker" ]; then
        echo "aros.sh: done after ${SECONDS}s"
        exit 0
    fi
    echo "aros.sh: AROS ended after ${SECONDS}s before the commands were done"
    exit 3
fi

R=${1:?usage: aros.sh RUNDIR [SECONDS] < commands}
secs=${2:-120}
[ -n "${AROS_HOSTED:-}" ] || die "set AROS_HOSTED to the hosted AROS system directory"
[ -x "$AROS_HOSTED/boot/linux/AROSBootstrap" ] || die "no hosted AROS in $AROS_HOSTED"
command -v xwfb-run >/dev/null || die "xwfb-run is missing (xwayland-run)"
R=$(mkdir -p "$R" && cd "$R" && pwd) || die "cannot make $1"
rm -rf "$R/AROS" "$R/out.txt" "$R/run.log" "$R/aros.pgid"
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
timeout -k 10 "$secs" xwfb-run -- "$0" _inner "$R" >"$R/run.log" 2>&1
rc=$?
# after the backstop AROS's process group may outlive the X session `timeout` killed
[ -s "$R/aros.pgid" ] && kill -9 -- -"$(cat "$R/aros.pgid")" 2>/dev/null
case $rc in
0|3) ;;
124|137) echo "aros.sh: timeout (the backstop: ${secs}s), the run did not end" >>"$R/run.log"; rc=124 ;;
255) echo "aros.sh: the X server could not start (xwfb-run)" >>"$R/run.log"; rc=4 ;;
*) echo "aros.sh: exit status $rc" >>"$R/run.log" ;;
esac
cat "$R/run.log"
exit $rc
