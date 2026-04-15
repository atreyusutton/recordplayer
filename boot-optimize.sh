#!/usr/bin/env bash
# boot-optimize.sh — strip boot time and all Pi branding.
# Idempotent: safe to re-run. Run on the Pi as admin with sudo:
#   sudo bash /home/admin/apps/recordplayer/boot-optimize.sh
#
# Changes:
#   1. /boot/firmware/config.txt      — disable rainbow splash, skip boot delay
#   2. /boot/firmware/cmdline.txt     — silence kernel, hide logos + cursor
#   3. Plymouth "recordplayer" theme  — black screen during userspace boot
#   4. Disable slow/unused systemd services
#
# Backups written to /boot/firmware/*.bak-recordplayer and /etc/*.bak-recordplayer

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Must run as root: sudo bash $0" >&2
    exit 1
fi

REPO="/home/admin/apps/recordplayer"
FIRMWARE="/boot/firmware"
CONFIG="$FIRMWARE/config.txt"
CMDLINE="$FIRMWARE/cmdline.txt"
THEME_DIR="/usr/share/plymouth/themes/recordplayer"

log() { echo "[boot-optimize] $*"; }

# ---------------------------------------------------------------------------
# 1. config.txt — firmware-level splash + delay removal
# ---------------------------------------------------------------------------
log "Patching $CONFIG"
[[ -f "$CONFIG.bak-recordplayer" ]] || cp "$CONFIG" "$CONFIG.bak-recordplayer"

ensure_line() {
    local file="$1" line="$2"
    grep -qxF "$line" "$file" || echo "$line" >> "$file"
}
ensure_line "$CONFIG" "disable_splash=1"
ensure_line "$CONFIG" "boot_delay=0"
ensure_line "$CONFIG" "initial_turbo=30"

# Comment out stale DAC overlays — Scarlett is USB, no I2C/I2S DAC attached.
# Each stale overlay costs ~60s at boot while udev probes a non-existent chip.
sed -i -E 's/^(dtoverlay=(hifiberry|iqaudio|allo|justboom|dacberry)[^ ]*)/#\1/' "$CONFIG"

# ---------------------------------------------------------------------------
# 2. cmdline.txt — single line, append silent flags once
# ---------------------------------------------------------------------------
log "Patching $CMDLINE"
[[ -f "$CMDLINE.bak-recordplayer" ]] || cp "$CMDLINE" "$CMDLINE.bak-recordplayer"

CMDLINE_ADDS=(
    "logo.nologo"
    "quiet"
    "loglevel=0"
    "vt.global_cursor_default=0"
    "plymouth.ignore-serial-consoles"
    "splash"
)
current="$(tr -d '\n' < "$CMDLINE")"
for flag in "${CMDLINE_ADDS[@]}"; do
    if ! grep -qw -- "$flag" <<< "$current"; then
        current="$current $flag"
    fi
done
# Normalize whitespace, write single line
echo "$current" | tr -s ' ' > "$CMDLINE"

# ---------------------------------------------------------------------------
# 3. Plymouth black theme
# ---------------------------------------------------------------------------
log "Installing Plymouth theme"
if ! dpkg -s plymouth >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y --no-install-recommends plymouth plymouth-themes
fi

install -d "$THEME_DIR"
install -m 0644 "$REPO/boot/plymouth/recordplayer/recordplayer.plymouth" "$THEME_DIR/recordplayer.plymouth"
install -m 0644 "$REPO/boot/plymouth/recordplayer/recordplayer.script"   "$THEME_DIR/recordplayer.script"

update-alternatives --install /usr/share/plymouth/themes/default.plymouth \
    default.plymouth "$THEME_DIR/recordplayer.plymouth" 100
update-alternatives --set default.plymouth "$THEME_DIR/recordplayer.plymouth"
update-initramfs -u

# ---------------------------------------------------------------------------
# 4. Disable slow/unused services
# ---------------------------------------------------------------------------
log "Disabling slow boot services"
DISABLE_SERVICES=(
    NetworkManager-wait-online.service
    ModemManager.service
    triggerhappy.service
    avahi-daemon.service
    bluetooth.service
    hciuart.service
    rpi-eeprom-update.service
    apt-daily.service
    apt-daily.timer
    apt-daily-upgrade.service
    apt-daily-upgrade.timer
    man-db.timer
)
for svc in "${DISABLE_SERVICES[@]}"; do
    if systemctl list-unit-files "$svc" >/dev/null 2>&1; then
        systemctl disable "$svc" 2>/dev/null || true
        systemctl mask    "$svc" 2>/dev/null || true
    fi
done

# ---------------------------------------------------------------------------
# 5. Replace lightdm with direct labwc systemd service.
#    lightdm blocks user session creation for ~33s waiting on WiFi/seat setup.
#    labwc.service runs as admin directly on tty1, no display manager.
# ---------------------------------------------------------------------------
log "Installing labwc.service"
install -m 0644 "$REPO/labwc.service" /etc/systemd/system/labwc.service
systemctl daemon-reload
systemctl enable labwc.service

if systemctl is-enabled lightdm.service >/dev/null 2>&1; then
    log "Disabling lightdm"
    systemctl disable lightdm.service
fi
# Default to multi-user target — labwc is WantedBy=multi-user.target so it starts there.
systemctl set-default multi-user.target

log "Done. Reboot required: sudo reboot"
log "After reboot, check: systemd-analyze"
