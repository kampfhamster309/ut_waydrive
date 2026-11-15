#!/bin/sh
# Copy the kernel's crash record of the last reboot (ramoops/pstore) to diag/. Run with sudo.
OUT=/home/phablet/android-auto/diag/pstore
rm -rf $OUT; mkdir -p $OUT
ls -la /sys/fs/pstore/
for f in /sys/fs/pstore/*; do
    [ -f "$f" ] || continue
    case "$f" in *.enc.z|*.z) cp "$f" $OUT/ ;; *) cp "$f" $OUT/ ;; esac
done
chown -R phablet:phablet /home/phablet/android-auto/diag
echo "saved $(ls $OUT | wc -l) file(s) to $OUT"
