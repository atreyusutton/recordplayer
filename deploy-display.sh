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
    apt-get install -y python3-pygame python3-pil python3-requests python3-flask \
        python3-gpiozero fonts-dejavu-core 2>/dev/null || true
    # If apt packages are too old, install via pip into a venv or system-wide:
    pip3 install --break-system-packages pygame pillow requests flask 2>/dev/null || \
    pip3 install pygame pillow requests flask || true

    echo "=== Creating app directory ==="
    mkdir -p "$APP_DIR"

    echo "=== Copying files ==="
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    # If running from a different directory (e.g. rsync'd temp copy), copy files in.
    # If already running from APP_DIR (git deploy puts files there directly), skip.
    if [[ "$SCRIPT_DIR" != "$APP_DIR" ]]; then
        cp "$SCRIPT_DIR/display.py"    "$APP_DIR/display.py"
        cp "$SCRIPT_DIR/onevent.sh"    "$APP_DIR/onevent.sh"
        cp "$SCRIPT_DIR/control.py"    "$APP_DIR/control.py"
        cp "$SCRIPT_DIR/knob.py"       "$APP_DIR/knob.py"
        cp "$SCRIPT_DIR/start-kiosk.sh" "$APP_DIR/start-kiosk.sh"
        mkdir -p "$APP_DIR/static"
        cp "$SCRIPT_DIR/static/index.html" "$APP_DIR/static/index.html"
    fi
    chmod +x "$APP_DIR/onevent.sh" "$APP_DIR/display.py" "$APP_DIR/control.py" \
             "$APP_DIR/knob.py" "$APP_DIR/start-kiosk.sh"

    echo "=== Installing systemd units ==="
    cp "$SCRIPT_DIR/record-display.service"  /etc/systemd/system/record-display.service
    cp "$SCRIPT_DIR/control.service"         /etc/systemd/system/control.service
    cp "$SCRIPT_DIR/knob.service"            /etc/systemd/system/knob.service
    cp "$SCRIPT_DIR/control-kiosk.service"   /etc/systemd/system/control-kiosk.service
    systemctl daemon-reload
    systemctl enable record-display.service
    systemctl enable control.service
    systemctl enable knob.service
    systemctl enable control-kiosk.service

    # labwc display layout (positions round HDMI at 0,0 and DSI at 720,120)
    echo "=== Configuring labwc display layout ==="
    LABWC_CFG=/home/admin/.config/labwc
    mkdir -p "$LABWC_CFG"
    if [[ ! -f "$LABWC_CFG/outputs.xml" ]]; then
        cp "$SCRIPT_DIR/labwc-outputs.xml" "$LABWC_CFG/outputs.xml"
        chown admin:admin "$LABWC_CFG/outputs.xml"
        echo "    Wrote $LABWC_CFG/outputs.xml"
    else
        echo "    $LABWC_CFG/outputs.xml already exists — skipping (edit manually if needed)"
    fi

    # Install Chromium if missing
    if ! command -v chromium-browser &>/dev/null && ! command -v chromium &>/dev/null; then
        echo "=== Installing Chromium ==="
        apt-get install -y chromium-browser
    fi

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

    echo "=== Starting services ==="
    systemctl restart record-display
    # Only start control if config.json exists (credentials written separately)
    if [ -f "$APP_DIR/config.json" ]; then
        systemctl restart control
    else
        echo "    Skipping control service start — config.json not yet created."
        echo "    Write credentials to $APP_DIR/config.json then: sudo systemctl start control"
    fi
    systemctl restart knob
    systemctl restart control-kiosk

    echo ""
    echo "Done! Check status with:"
    echo "  sudo systemctl status record-display"
    echo "  sudo systemctl status control"
    echo "  sudo systemctl status knob"
    echo "  sudo systemctl status control-kiosk"
    echo "  sudo journalctl -u record-display -f"
    echo "  sudo journalctl -u control -f"
    echo "  sudo journalctl -u control-kiosk -f"
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
