#!/bin/sh
# Runs as an extra ExecStartPre of waydroid-container.service (after 'waydroid upgrade -o',
# which rewrites the container config on every start). Re-adds the Android Auto bits:
#   - MediaTek H.264/HEVC encoders disabled inside the container, so Android Auto uses the
#     software encoder (frames get stuck in c2.mtk.avc.encoder when called from Waydroid).
# The patched codec list is rebuilt from the host's file each time, so it follows OTA updates.
CFG=/var/lib/waydroid/lxc/waydroid/config
DIR=/var/lib/waydroid/android-auto
XML=$DIR/media_codecs_c2.xml
SRC=/vendor/etc/media_codecs_c2.xml
TAG="# android-auto: software video encoder"
[ -f "$CFG" ] && [ -f "$SRC" ] || exit 0
mkdir -p $DIR
sed -E 's|<MediaCodec name="(c2\.mtk\.(avc\|hevc)\.encoder)" type="([^"]*)" *>|<MediaCodec name="\1" type="\3" enabled="false" >|' "$SRC" > "$XML.new" \
    && grep -q 'c2.mtk.avc.encoder" type="video/avc" enabled="false"' "$XML.new" && mv "$XML.new" "$XML"
[ -f "$XML" ] || exit 0
grep -qF "$TAG" "$CFG" || printf '%s\nlxc.mount.entry = %s vendor_extra/etc/media_codecs_c2.xml none bind,ro 0 0\n' "$TAG" "$XML" >> "$CFG"
exit 0
