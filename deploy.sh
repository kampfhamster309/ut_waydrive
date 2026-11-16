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
# Launcher icon "Android": opens Android's screen through the relay (show-android.sh).
# The stock Waydroid icon stops working once its window has been swiped away.
ssh "$TARGET" 'mkdir -p ~/.local/share/applications && cat > ~/.local/share/applications/android-screen.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Android
Comment=Open the Android screen (Waydroid)
Exec=/bin/sh $HOME/android-auto/show-android.sh
Icon=/usr/share/icons/hicolor/512x512/apps/waydroid.png
Terminal=false
X-Lomiri-Touch=true
EOF'
echo "copied to $TARGET:~/android-auto"
