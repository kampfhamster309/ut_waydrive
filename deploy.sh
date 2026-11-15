#!/bin/sh
# Copy the phone-side files to ~/android-auto on the phone.
#   ./deploy.sh phablet@<phone>
# Then on the phone:  sudo sh ~/android-auto/aa-install.sh   (first time)
#                 or  sudo sh ~/android-auto/aa-update.sh    (relay changes only)
set -eu
TARGET="${1:?usage: $0 <ssh-target>}"
cd "$(dirname "$0")/phone"
ssh "$TARGET" 'mkdir -p ~/android-auto/gps ~/android-auto/debug'
scp -q ./*.py ./*.sh ./*.service "$TARGET:android-auto/"
scp -q gps/pos.qml "$TARGET:android-auto/gps/"
scp -q debug/* "$TARGET:android-auto/debug/"
echo "copied to $TARGET:~/android-auto"
