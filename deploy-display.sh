#!/usr/bin/env bash
# deploy-display.sh
# Deploys the album art display to the Raspberry Pi.
# Run from the repo root on your development machine:
#   ./deploy-display.sh [pi-host]   (default: recordplayer.local)
#
# Or run directly on the Pi as admin:
#   sudo ./deploy-display.sh --local

set -euo pipefail

PI_HOST="${1:-recordplayer.local}"
APP_DIR="/home/admin/apps/recordplayer"

if [[ "${1:-}" == "--local" ]]; then
    # ── Running on the Pi itself ──────────────────────────────────────────────
    echo "=== Installing display dependencies ==="
    apt-get install -y python3-pygame python3-pil python3-requests \
        fonts-dejavu-core 2>/dev/null || true
    # If apt packages are too old, install via pip into a venv or system-wide:
    pip3 install --break-system-packages pygame pillow requests 2>/dev/null || \
    pip3 install pygame pillow requests || true

    echo "=== Creating app directory ==="
    mkdir -p "$APP_DIR"

    echo "=== Copying files ==="
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    # If running from a different directory (e.g. rsync'd temp copy), copy files in.
    # If already running from APP_DIR (git deploy puts files there directly), skip.
    if [[ "$SCRIPT_DIR" != "$APP_DIR" ]]; then
        cp "$SCRIPT_DIR/display.py"  "$APP_DIR/display.py"
        cp "$SCRIPT_DIR/onevent.sh"  "$APP_DIR/onevent.sh"
    fi
    chmod +x "$APP_DIR/onevent.sh" "$APP_DIR/display.py"

    echo "=== Installing systemd unit ==="
    cp "$SCRIPT_DIR/record-display.service" /etc/systemd/system/record-display.service
    systemctl daemon-reload
    systemctl enable record-display.service

    echo "=== Patching raspotify/conf ==="
    CONF=/etc/raspotify/conf
    # Always ensure LIBRESPOT_ONEVENT points to the correct script in APP_DIR.
    # We replace any existing value rather than skipping, so re-runs stay current.
    if grep -q "LIBRESPOT_ONEVENT" "$CONF" 2>/dev/null; then
        sed -i "s|^LIBRESPOT_ONEVENT=.*|LIBRESPOT_ONEVENT=\"$APP_DIR/onevent.sh\"|" "$CONF"
        echo "    Updated LIBRESPOT_ONEVENT in $CONF"
    else
        echo "" >> "$CONF"
        echo "LIBRESPOT_ONEVENT=\"$APP_DIR/onevent.sh\"" >> "$CONF"
        echo "    Added LIBRESPOT_ONEVENT to $CONF"
    fi

    echo "=== Restarting raspotify ==="
    systemctl restart raspotify

    echo "=== Starting record-display ==="
    systemctl restart record-display

    echo ""
    echo "Done! Check status with:"
    echo "  sudo systemctl status record-display"
    echo "  sudo journalctl -u record-display -f"
    echo ""
    echo "Play a track on Spotify to test."

else
    # ── Remote deploy via rsync + ssh ─────────────────────────────────────────
    echo "=== Deploying to ${PI_HOST} ==="
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    rsync -av \
        "$SCRIPT_DIR/display.py" \
        "$SCRIPT_DIR/onevent.sh" \
        "$SCRIPT_DIR/record-display.service" \
        "$SCRIPT_DIR/deploy-display.sh" \
        "admin@${PI_HOST}:~/apps/recordplayer/"

    echo "=== Running install on Pi (requires sudo) ==="
    ssh "admin@${PI_HOST}" \
        "sudo bash ~/apps/recordplayer/deploy-display.sh --local"
fi
