#!/bin/bash
# Container entrypoint: prepares the Crankshaft-style /tmp flag files that the
# OpenAuto UI checks, then starts autoapp from the config dir (its CWD).
set -e
cd /home/hu/openauto

# Show the "Wifi" (TCP) connect button on the main screen.
touch /tmp/mobile_hotspot_detected

# AA_HOST=<ip>: pre-fill the connect dialog with this address. Because it is the
# only entry, OpenAuto connects to <ip>:5277 as soon as the dialog is opened.
if [ -n "${AA_HOST:-}" ]; then
    printf '%s\n' "$AA_HOST" > /tmp/gateway_wlan0
fi

exec "$@"
