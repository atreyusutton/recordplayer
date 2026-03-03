#!/usr/bin/env python3
"""Physical volume knob — rotary encoder on GPIO, controls ALSA Digital mixer.

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

import signal
import subprocess
import logging

from gpiozero import RotaryEncoder, Button

# ── Config ────────────────────────────────────────────────────────────────────
CLK  = 17   # GPIO BCM number
DT   = 27
SW   = 22

CARD    = "sndrpihifiberry"
CONTROL = "Digital"
STEP    = 3  # percent per detent

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s knob %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ── ALSA helpers ──────────────────────────────────────────────────────────────
def _amixer(*args):
    subprocess.run(
        ["amixer", "-c", CARD, "-q", "sset", CONTROL, *args],
        check=False,
    )


_muted = False


def vol_up():
    if _muted:
        return
    _amixer(f"{STEP}%+")
    log.info("vol +%d%%", STEP)


def vol_down():
    if _muted:
        return
    _amixer(f"{STEP}%-")
    log.info("vol -%d%%", STEP)


def toggle_mute():
    global _muted
    _muted = not _muted
    _amixer("toggle")
    log.info("mute %s", "ON" if _muted else "off")


# ── GPIO ──────────────────────────────────────────────────────────────────────
rotor = RotaryEncoder(CLK, DT, wrap=False, max_steps=200)
rotor.when_rotated_clockwise         = vol_up
rotor.when_rotated_counter_clockwise = vol_down

button = Button(SW, pull_up=True, bounce_time=0.05)
button.when_pressed = toggle_mute

log.info(
    "ready  CLK=GPIO%d  DT=GPIO%d  SW=GPIO%d  card=%s  control=%s  step=%d%%",
    CLK, DT, SW, CARD, CONTROL, STEP,
)

signal.pause()
