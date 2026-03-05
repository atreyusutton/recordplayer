#!/usr/bin/env bash
# start-kiosk.sh — launches Chromium kiosk on the DSI touchscreen (800×480)
# Called by control-kiosk.service.  Wayland only.

CHROMIUM=$(command -v chromium-browser 2>/dev/null || command -v chromium 2>/dev/null)
if [[ -z "$CHROMIUM" ]]; then
    echo "chromium not found — install with: sudo apt-get install -y chromium-browser" >&2
    exit 1
fi

# Wait for the Flask backend to be ready (up to 30 s)
for i in $(seq 1 30); do
    curl -s http://localhost:8080 >/dev/null 2>&1 && break
    sleep 1
done

# labwc window rule in rc.xml handles placing Chromium on DSI-1 —
# --window-position is ignored on Wayland so we don't pass it.
exec "$CHROMIUM" \
    --kiosk \
    --ozone-platform=wayland \
    --noerrdialogs \
    --disable-infobars \
    --no-first-run \
    --disable-session-crashed-bubble \
    --disable-component-update \
    --check-for-update-interval=31536000 \
    --disable-features=TranslateUI \
    --overscroll-history-navigation=0 \
    http://localhost:8080
