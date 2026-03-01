#!/bin/bash
# =============================================================================
# Audio Diagnostic Script for Record Player (HiFiBerry DAC+ / PCM5122)
# Run on the Pi: bash diagnose-audio.sh
# =============================================================================

BOOT_CONFIG="/boot/firmware/config.txt"
[ -f "$BOOT_CONFIG" ] || BOOT_CONFIG="/boot/config.txt"

sep() { echo ""; echo "=== $* ==="; }

# ── 1. Kernel overlay ──────────────────────────────────────────────────────────
sep "1. boot config overlay"
grep -E "dtoverlay|dtparam=audio|hifiberry" "$BOOT_CONFIG" || echo "(none found)"

sep "2. onboard audio disabled? (must be off when using DAC)"
grep "dtparam=audio" "$BOOT_CONFIG" || echo "  dtparam=audio line not present (good — default is off on Pi 4)"

# ── 2. ALSA card detection ─────────────────────────────────────────────────────
sep "3. ALSA playback devices (aplay -l)"
aplay -l 2>&1

sep "4. ALSA card name / index"
cat /proc/asound/cards 2>/dev/null || echo "(unavailable)"

# ── 3. Raspotify service ───────────────────────────────────────────────────────
sep "5. Raspotify service status"
systemctl status raspotify --no-pager -l 2>&1 | head -40

sep "6. Raspotify config (/etc/raspotify/conf)"
cat /etc/raspotify/conf 2>/dev/null || echo "(file not found)"

# ── 4. LIBRESPOT_DEVICE vs actual ALSA name ────────────────────────────────────
sep "7. Checking LIBRESPOT_DEVICE matches an actual ALSA card"
DEVICE=$(grep LIBRESPOT_DEVICE /etc/raspotify/conf 2>/dev/null | cut -d= -f2 | tr -d '"')
echo "  Configured device: '${DEVICE:-<not set>}'"
if [ -n "$DEVICE" ]; then
    CARD_NAME=$(echo "$DEVICE" | sed 's/hw://')
    if aplay -l 2>/dev/null | grep -qi "$CARD_NAME"; then
        echo "  -> Found in aplay -l (looks good)"
    else
        echo "  -> NOT found in aplay -l. Try using hw:0 or check aplay -l output above."
    fi
fi

# ── 5. Quick test tone ─────────────────────────────────────────────────────────
sep "8. Test tone through DAC (3 seconds of 440 Hz sine wave)"
if command -v speaker-test &>/dev/null; then
    CARD=$(aplay -l 2>/dev/null | grep -i hifiberry | head -1 | awk '{print $2}' | tr -d ':')
    if [ -n "$CARD" ]; then
        echo "  Running: speaker-test -D hw:${CARD} -t sine -f 440 -l 1 -s 1"
        timeout 5 speaker-test -D "hw:${CARD}" -t sine -f 440 -l 1 -s 1 2>&1 | tail -5
    else
        echo "  No HiFiBerry card detected — skipping test tone."
    fi
else
    echo "  speaker-test not found. Install with: sudo apt install alsa-utils"
fi

# ── 6. Recent librespot logs ───────────────────────────────────────────────────
sep "9. Recent raspotify journal (last 30 lines)"
journalctl -u raspotify -n 30 --no-pager 2>&1

sep "10. ALSA errors in kernel log"
dmesg | grep -iE "snd|hifiberry|pcm5122|i2s" | tail -20 || echo "(none)"

# ── Summary hint ──────────────────────────────────────────────────────────────
echo ""
echo "=== Quick fixes to try ==="
echo "  A) Wrong device name → change LIBRESPOT_DEVICE to hw:0 (or whatever card # aplay -l shows)"
echo "  B) onboard audio conflicts → ensure 'dtparam=audio=off' is in $BOOT_CONFIG, then reboot"
echo "  C) Overlay missing → ensure 'dtoverlay=hifiberry-dacplus' is in $BOOT_CONFIG, then reboot"
echo "  D) Raspotify not outputting → check 'LIBRESPOT_BACKEND=alsa' is set in /etc/raspotify/conf"
echo "  E) Volume is zero → run: amixer -c sndrpihifiberry sset 'Digital' 100%"
echo ""
