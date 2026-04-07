#!/usr/bin/env python3
"""Navigation rotary encoder — GPIO23/24/25 → Tab/Shift+Tab/Enter via uinput virtual keyboard."""

import time
from pathlib import Path
import RPi.GPIO as GPIO
from evdev import UInput, ecodes as e

WAKE_FILE = Path("/tmp/recordplayer_wake")

CLK = 23
DT  = 24
SW  = 25

GPIO.setmode(GPIO.BCM)
GPIO.setup(CLK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(DT,  GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(SW,  GPIO.IN, pull_up_down=GPIO.PUD_UP)

ui = UInput()

def _wake():
    try:
        WAKE_FILE.write_text("")
    except OSError:
        pass

def send_next():
    _wake()
    ui.write(e.EV_KEY, e.KEY_RIGHT, 1)
    ui.write(e.EV_KEY, e.KEY_RIGHT, 0)
    ui.syn()

def send_prev():
    _wake()
    ui.write(e.EV_KEY, e.KEY_LEFT, 1)
    ui.write(e.EV_KEY, e.KEY_LEFT, 0)
    ui.syn()

def send_enter():
    _wake()
    ui.write(e.EV_KEY, e.KEY_ENTER, 1)
    ui.write(e.EV_KEY, e.KEY_ENTER, 0)
    ui.syn()

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
                    send_next()   # clockwise → next element
                else:
                    send_prev()   # counter-clockwise → prev element

        # Button press — falling edge on SW, debounced 300 ms
        # Also ignore presses within 200 ms of last rotation (prevents mechanical coupling)
        if sw != last_sw:
            last_sw = sw
            if sw == 0 and (now - last_sw_time) > 0.3 and (now - last_tick) > 0.2:
                last_sw_time = now
                send_enter()

        time.sleep(0.001)

finally:
    GPIO.cleanup()
    ui.close()
