#!/bin/bash
# =============================================================================
# Record Player - Raspotify Setup Script
# Turns the Raspberry Pi into a Spotify Connect audio device.
# Audio output: Focusrite Scarlett Solo 4th Gen (USB)
# =============================================================================

set -e

DEVICE_NAME="Record Player"
BITRATE="320"

echo "=== Updating system packages ==="
sudo apt update && sudo apt upgrade -y

echo "=== Installing dependencies ==="
sudo apt install -y curl

echo "=== Installing Raspotify ==="
curl -sL https://dtcooper.github.io/raspotify/install.sh | sh

echo "=== Writing Raspotify config ==="
sudo tee /etc/raspotify/conf > /dev/null <<EOF
LIBRESPOT_NAME="${DEVICE_NAME}"
LIBRESPOT_BITRATE="${BITRATE}"
LIBRESPOT_BACKEND="alsa"

# Focusrite Scarlett Solo 4th Gen (USB audio, native S32/24-bit)
LIBRESPOT_DEVICE="hw:Gen"
LIBRESPOT_FORMAT="S32"
EOF

echo "=== Enabling and starting Raspotify service ==="
sudo systemctl enable raspotify
sudo systemctl restart raspotify

echo ""
echo "=== Done ==="
echo ""
echo "Open Spotify on your phone or desktop, tap the Connect icon,"
echo "and select '${DEVICE_NAME}' from the list."
echo ""
echo "If you hear no audio, run: aplay -l"
echo "Then check /etc/raspotify/conf and restart: sudo systemctl restart raspotify"
