# Appended to /home/admin/.bash_profile by boot-optimize.sh
# Autostarts labwc on tty1 only. SSH / other TTYs get a normal shell.
if [ -z "$WAYLAND_DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
    export XDG_RUNTIME_DIR="/run/user/$(id -u)"
    export XDG_SESSION_TYPE=wayland
    export XDG_SESSION_DESKTOP=labwc
    export XDG_CURRENT_DESKTOP=labwc:wlroots
    exec labwc
fi
