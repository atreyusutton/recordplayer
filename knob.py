#!/usr/bin/env python3
"""Physical volume knob — rotary encoder on GPIO, controls ALSA mixer on Scarlett Solo.

Wiring (KY-040 style encoder):
  +   → 3.3V  (pin 1 or 17)
  GND → GND   (pin 9)
  CLK → GPIO17 (pin 11)
  DT  → GPIO27 (pin 13)
  SW  → GPIO22 (pin 15)

Behaviour:
  Rotate CW   → volume up   (3% per detent)
  Rotate CCW  → volume down (3% per detent)
  Press       → mute / unmute toggle
"""

import re
import signal
import subprocess
import logging

from gpiozero import RotaryEncoder, Button

# ── Config ────────────────────────────────────────────────────────────────────
CLK  = 17   # GPIO BCM number
DT   = 27
SW   = 22

CARD         = "Gen"  # Focusrite Scarlett Solo 4th Gen
CONTROLS     = ["Mix A Input 01", "Mix B Input 02"]  # L + R playback volume
STEP         = 3   # percent per detent
BOOT_VOLUME  = 65  # percent set on startup

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s knob %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── ALSA helpers ──────────────────────────────────────────────────────────────
def _amixer(control, *args):
    subprocess.run(
        ["amixer", "-c", CARD, "-q", "sset", control, *args],
        check=False,
    )


def _amixer_all(*args):
    for ctrl in CONTROLS:
        _amixer(ctrl, *args)


def _set_boot_volume():
    _amixer_all(f"{BOOT_VOLUME}%")
    log.info("boot volume set to %d%%", BOOT_VOLUME)


_muted = False
_pre_mute_vol = BOOT_VOLUME


def vol_up():
    if _muted:
        return
    _amixer_all(f"{STEP}%+")
    log.info("vol +%d%%", STEP)


def vol_down():
    if _muted:
        return
    _amixer_all(f"{STEP}%-")
    log.info("vol -%d%%", STEP)


def toggle_mute():
    global _muted, _pre_mute_vol
    _muted = not _muted
    if _muted:
        # Read current volume before muting
        try:
            out = subprocess.check_output(
                ["amixer", "-c", CARD, "sget", CONTROLS[0]], text=True
            )
            m = re.search(r"\[(\d+)%\]", out)
            if m:
                _pre_mute_vol = int(m.group(1))
        except Exception:
            pass
        _amixer_all("0%")
    else:
        _amixer_all(f"{_pre_mute_vol}%")
    log.info("mute %s", "ON" if _muted else "off")


# ── GPIO ──────────────────────────────────────────────────────────────────────
rotor = RotaryEncoder(CLK, DT, wrap=False, max_steps=200)
rotor.when_rotated_clockwise         = vol_up
rotor.when_rotated_counter_clockwise = vol_down

button = Button(SW, pull_up=True, bounce_time=0.05)
button.when_pressed = toggle_mute

_set_boot_volume()
log.info(
    "ready  CLK=GPIO%d  DT=GPIO%d  SW=GPIO%d  card=%s  controls=%s  step=%d%%",
    CLK, DT, SW, CARD, CONTROLS, STEP,
)

signal.pause()
