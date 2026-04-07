#!/usr/bin/env python3
"""Navigation rotary encoder — GPIO17/27/22 → nav events via file IPC.

Writes navigation events (next/prev/enter) to /tmp/recordplayer_nav
which the control.py SSE stream pushes to the UI instantly.
This bypasses Wayland keyboard focus issues entirely.
"""

import time
import json
from pathlib import Path
import RPi.GPIO as GPIO

WAKE_FILE = Path("/tmp/recordplayer_wake")
NAV_FILE  = Path("/tmp/recordplayer_nav")

CLK = 17
DT  = 27
SW  = 22

GPIO.setmode(GPIO.BCM)
GPIO.setup(CLK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(DT,  GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(SW,  GPIO.IN, pull_up_down=GPIO.PUD_UP)


def _wake():
    try:
        WAKE_FILE.write_text("")
    except OSError:
        pass


def send_event(action: str):
    _wake()
    try:
        NAV_FILE.write_text(json.dumps({"action": action, "t": time.monotonic()}))
    except OSError:
        pass


last_clk     = GPIO.input(CLK)
last_sw      = GPIO.input(SW)
last_tick    = 0.0
last_sw_time = 0.0

try:
    while True:
        now = time.monotonic()
        clk = GPIO.input(CLK)
        dt  = GPIO.input(DT)
        sw  = GPIO.input(SW)

        # Encoder rotation — falling edge on CLK, debounced 5 ms
        if clk != last_clk:
            last_clk = clk
            if clk == 0 and (now - last_tick) > 0.005:
                last_tick = now
                if dt != clk:
                    send_event("next")    # clockwise → next element
                else:
                    send_event("prev")    # counter-clockwise → prev element

        # Button press — falling edge on SW, debounced 300 ms
        # Also ignore presses within 200 ms of last rotation (prevents mechanical coupling)
        if sw != last_sw:
            last_sw = sw
            if sw == 0 and (now - last_sw_time) > 0.3 and (now - last_tick) > 0.2:
                last_sw_time = now
                send_event("enter")

        time.sleep(0.001)

finally:
    GPIO.cleanup()
