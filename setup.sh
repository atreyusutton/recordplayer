#!/bin/bash
# =============================================================================
# Record Player - Raspotify Setup Script
# Turns the Raspberry Pi into a Spotify Connect audio device.
# =============================================================================

set -e

DEVICE_NAME="Record Player"
BITRATE="320"

# Detect boot config location (Bookworm uses /boot/firmware, older uses /boot)
if [ -f /boot/firmware/config.txt ]; then
    BOOT_CONFIG="/boot/firmware/config.txt"
else
    BOOT_CONFIG="/boot/config.txt"
fi

echo "=== Checking DAC overlay in ${BOOT_CONFIG} ==="
if grep -q "dtoverlay=hifiberry-dacplus" "${BOOT_CONFIG}"; then
    echo "    hifiberry-dacplus overlay already present, skipping."
    NEEDS_REBOOT=false
else
    echo "    Adding hifiberry-dacplus overlay..."
    sudo sed -i '/^\[all\]/a dtoverlay=hifiberry-dacplus' "${BOOT_CONFIG}" 2>/dev/null || \
        echo "dtoverlay=hifiberry-dacplus" | sudo tee -a "${BOOT_CONFIG}" > /dev/null
    NEEDS_REBOOT=true
fi

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

# InnoMaker PCM5122 DAC HAT (hifiberry-dacplus overlay)
LIBRESPOT_DEVICE="hw:sndrpihifiberry"
EOF

echo "=== Enabling and starting Raspotify service ==="
sudo systemctl enable raspotify
sudo systemctl restart raspotify

echo ""
echo "=== Done ==="
echo ""

if [ "${NEEDS_REBOOT}" = true ]; then
    echo "*** REBOOT REQUIRED ***"
    echo "The DAC overlay was just added. You must reboot for audio to work:"
    echo "  sudo reboot"
    echo ""
    echo "After rebooting, verify the DAC is detected with: aplay -l"
    echo "You should see 'sndrpihifiberry' in the list."
    echo ""
fi

echo "Open Spotify on your phone or desktop, tap the Connect icon,"
echo "and select '${DEVICE_NAME}' from the list."
echo ""
echo "If you hear no audio after rebooting, run: aplay -l"
echo "Then check /etc/raspotify/conf and restart: sudo systemctl restart raspotify"
