#!/usr/bin/env python3
"""Navigation rotary encoder — GPIO23/24/25 → Tab/Shift+Tab/Enter via uinput virtual keyboard."""

import time
import RPi.GPIO as GPIO
from evdev import UInput, ecodes as e

CLK = 23
DT  = 24
SW  = 25

GPIO.setmode(GPIO.BCM)
GPIO.setup(CLK, GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(DT,  GPIO.IN, pull_up_down=GPIO.PUD_UP)
GPIO.setup(SW,  GPIO.IN, pull_up_down=GPIO.PUD_UP)

ui = UInput()

def send_tab():
    ui.write(e.EV_KEY, e.KEY_TAB, 1)
    ui.write(e.EV_KEY, e.KEY_TAB, 0)
    ui.syn()

def send_shift_tab():
    ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 1)
    ui.write(e.EV_KEY, e.KEY_TAB, 1)
    ui.write(e.EV_KEY, e.KEY_TAB, 0)
    ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 0)
    ui.syn()

def send_enter():
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
                    send_tab()        # clockwise → next element
                else:
                    send_shift_tab()  # counter-clockwise → prev element

        # Button press — falling edge on SW, debounced 300 ms
        if sw != last_sw:
            last_sw = sw
            if sw == 0 and (now - last_sw_time) > 0.3:
                last_sw_time = now
                send_enter()

        time.sleep(0.001)

finally:
    GPIO.cleanup()
    ui.close()
