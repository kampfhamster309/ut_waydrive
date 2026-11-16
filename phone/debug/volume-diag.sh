#!/bin/sh
# Diagnostic for volume sync between Ubuntu Touch and Android (Waydroid). Run with sudo,
# with Android's screen open (sh ~/android-auto/show-android.sh) and the phone on a charger.
# Three phases: Android's ring/system volume at maximum, at 1, at 0. In each phase the
# script triggers Android's charging sound, and you tap around in Android (touch sounds).
# It records what Android and the host's PulseAudio report. Volumes are restored at the end.
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
A="lxc-attach -P /var/lib/waydroid/lxc -n waydroid --clear-env --"
U=${SUDO_USER:-phablet}
UIDN=$(id -u "$U")
OUT=/home/$U/android-auto/diag/volume-diag.txt
mkdir -p "$(dirname "$OUT")"
pa() { runuser -u "$U" -- env XDG_RUNTIME_DIR=/run/user/$UIDN "$@"; }
vol() { $A /system/bin/cmd media_session volume --stream "$1" "$2" $3 2>&1 | tail -1; }
num() { sed -n 's/.*volume is \([0-9]*\).*/\1/p'; }
say() { echo "$*"; echo "## $*" >> "$OUT"; }
watch_streams() {   # log Android's streams on the host while a phase runs
    end=$(( $(date +%s) + $1 ))
    while [ "$(date +%s)" -lt "$end" ]; do
        pa pactl list sink-inputs 2>/dev/null | grep -v -E "maliit|QtPulse|feedbacksound" \
            | grep -E "Sink Input|Volume:|Mute:|application.name|media.role|media.name|process.binary|stream-restore.id" \
            | sed "s/^/  [$(date +%T)] /" >> "$OUT.streams"
        sleep 0.4
    done
}
phase() {           # $1 = label, $2 = ring volume
    vol 2 --set "$2" >> "$OUT"; vol 5 --set "$2" >> "$OUT" 2>&1
    say "PHASE $1: ring/system volume $2 of 7. Charging sound in 2 s, then tap around in Android for 8 s."
    watch_streams 12 &
    sleep 2
    $A /system/bin/cmd battery unplug >> "$OUT" 2>&1
    sleep 1.5
    $A /system/bin/cmd battery reset >> "$OUT" 2>&1
    sleep 8.5
    wait
}
: > "$OUT"; : > "$OUT.streams"
echo "== $(date)" >> "$OUT"
for s in 1 2 3 4 5; do echo "stream $s: $(vol $s --get)" >> "$OUT"; done
OLD_RING=$(vol 2 --get | num); OLD_NOTI=$(vol 5 --get | num)
{
echo "sound settings: effects=$($A /system/bin/settings get system sound_effects_enabled) charging=$($A /system/bin/settings get secure charging_sounds_enabled) (global: $($A /system/bin/settings get global charging_sounds_enabled))"
echo "battery: $($A /system/bin/dumpsys battery 2>/dev/null | grep -E "powered|status|level" | tr -s ' \n' ' ')"
echo "ringer: $($A /system/bin/dumpsys audio 2>/dev/null | grep -A3 "^Ringer mode" | tr -s ' \n' ' ' | cut -c1-200)"
} >> "$OUT" 2>&1
phase "1 of 3 (should be LOUD)" 7
phase "2 of 3 (should be QUIET)" 1
phase "3 of 3 (should be SILENT)" 0
{
echo "== streams seen on the host"; sort -u -k3 "$OUT.streams" | head -40
echo "== events"; $A /system/bin/logcat -b events -d 2>/dev/null | grep -E "volume_changed" | tail -8
echo "== restore"
[ -n "$OLD_RING" ] && vol 2 --set "$OLD_RING"; [ -n "$OLD_NOTI" ] && vol 5 --set "$OLD_NOTI"
for s in 2 3 5; do echo "stream $s: $(vol $s --get)"; done
} >> "$OUT" 2>&1
rm -f "$OUT.streams"; chown "$U" "$OUT"
echo "done: $OUT"
echo "Please report for each phase: charging sound heard? touch sounds heard? how loud?"
