#!/bin/bash
# Start the OpenAuto head unit emulator in Docker.
#
#   ./run-openauto.sh                    # USB + TCP, window on host display
#   ./run-openauto.sh --host 192.168.1.50   # also pre-fill/auto-connect TCP to that IP:5277
#   ./run-openauto.sh --no-usb           # no /dev/bus/usb, not privileged (TCP only, safe)
#   ./run-openauto.sh --shell            # bash in the container instead of autoapp
#   ./run-openauto.sh -- <cmd...>        # run an arbitrary command in the container
#
# Config (openauto.ini, openauto_wifi_recent.ini) persists in ./config.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
IMAGE="${IMAGE:-openauto-hu}"
NAME="${NAME:-openauto-hu}"
USB=1
AA_HOST=""
CMD=()

while [ $# -gt 0 ]; do
    case "$1" in
        --host)   AA_HOST="$2"; shift 2 ;;
        --no-usb) USB=0; shift ;;
        --shell)  CMD=(bash); shift ;;
        --)       shift; CMD=("$@"); break ;;
        -h|--help) sed -n 2,11p "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

mkdir -p "$HERE/config"

ARGS=(--rm -it --name "$NAME" --network host --ipc host
      -e DISPLAY="${DISPLAY:-:0}" -v /tmp/.X11-unix:/tmp/.X11-unix:ro
      -e QT_X11_NO_MITSHM=1
      -v "$HERE/config:/home/hu/openauto"
      -e AA_HOST="$AA_HOST")
[ -t 0 ] || ARGS=("${ARGS[@]/-it/-i}")

# XWayland auth cookie
if [ -n "${XAUTHORITY:-}" ] && [ -f "$XAUTHORITY" ]; then
    ARGS+=(-e XAUTHORITY=/tmp/.xauth -v "$XAUTHORITY:/tmp/.xauth:ro")
fi

# Audio through PipeWire's PulseAudio socket (optional)
PULSE_SOCK="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/pulse/native"
if [ -S "$PULSE_SOCK" ]; then
    ARGS+=(-e PULSE_SERVER=unix:/run/pulse/native -v "$PULSE_SOCK:/run/pulse/native")
fi

# GPU (for video decode/rendering), harmless if absent
[ -d /dev/dri ] && ARGS+=(--device /dev/dri)

if [ "$USB" = 1 ]; then
    ARGS+=(--privileged -v /dev/bus/usb:/dev/bus/usb -v /run/udev:/run/udev:ro)
fi

exec docker run "${ARGS[@]}" "$IMAGE" "${CMD[@]}"
