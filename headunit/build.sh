#!/bin/bash
# Clone aasdk (newdev) + openauto (main) into ./src if missing, then build the image.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HERE/src"
[ -d "$HERE/src/aasdk" ]    || git clone --branch newdev https://github.com/opencardev/aasdk.git    "$HERE/src/aasdk"
[ -d "$HERE/src/openauto" ] || git clone --branch main   https://github.com/opencardev/openauto.git "$HERE/src/openauto"
docker build --build-arg UID="$(id -u)" --build-arg GID="$(id -g)" -t "${IMAGE:-openauto-hu}" "$HERE"
