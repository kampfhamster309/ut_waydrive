#!/bin/sh
# Install a split APK set (base.apk + split_*.apk) into Waydroid.  sudo sh waydroid-install-splits.sh <dir>
set -eu
DIR=$(cd "$1" && pwd)
A="lxc-attach -P /var/lib/waydroid/lxc -n waydroid --clear-env --"
STAGE=/home/phablet/.local/share/waydroid/data/local/tmp/splits   # = /data/local/tmp/splits in Android
rm -rf $STAGE; mkdir -p $STAGE; cp $DIR/*.apk $STAGE/; chmod 644 $STAGE/*.apk; chmod 755 $STAGE
TOTAL=$(cat $STAGE/*.apk | wc -c)
SID=$($A /system/bin/pm install-create -S $TOTAL | sed -n 's/.*\[\([0-9]*\)\].*/\1/p')
echo "session $SID"
for f in $STAGE/*.apk; do
    n=$(basename $f); s=$(stat -c %s $f)
    $A /system/bin/pm install-write -S $s $SID $n /data/local/tmp/splits/$n
done
$A /system/bin/pm install-commit $SID
rm -rf $STAGE
