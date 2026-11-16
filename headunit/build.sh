#!/bin/bash
# Clone aasdk (newdev) + openauto (main) into ./src if missing, then build the image.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HERE/src"
[ -d "$HERE/src/aasdk" ]    || git clone --branch newdev https://github.com/opencardev/aasdk.git    "$HERE/src/aasdk"
[ -d "$HERE/src/openauto" ] || git clone --branch main   https://github.com/opencardev/openauto.git "$HERE/src/openauto"
# Local patches (idempotent: skipped when already applied).
for p in "$HERE"/patches/openauto-*.patch; do
    [ -f "$p" ] || continue
    git -C "$HERE/src/openauto" apply --reverse --check "$p" 2>/dev/null \
        || git -C "$HERE/src/openauto" apply "$p"
done
docker build --build-arg UID="$(id -u)" --build-arg GID="$(id -g)" -t "${IMAGE:-openauto-hu}" "$HERE"
