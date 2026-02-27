#!/usr/bin/env python3
import time
import sys

try:
    import RPi.GPIO as GPIO
except ImportError:
    print("RPi.GPIO not found. Install with: sudo apt update && sudo apt install -y python3-rpi.gpio")
    sys.exit(1)

# You said: Raspberry Pi physical pin 12 -> MOSFET signal
# Physical pin 12 is BCM GPIO18 (hardware PWM capable)
PWM_PIN_BCM = 18
PWM_FREQ_HZ = 2000  # 2 kHz is usually fine for motor PWM drivers

def main():
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PWM_PIN_BCM, GPIO.OUT)

    pwm = GPIO.PWM(PWM_PIN_BCM, PWM_FREQ_HZ)
    pwm.start(0)  # start stopped

    print("Motor PWM test on GPIO18 (physical pin 12)")
    print("Ctrl+C to stop. Ramping 0% -> 80% -> 0% repeatedly...")

    try:
        while True:
            # ramp up
            for duty in range(0, 81, 5):
                pwm.ChangeDutyCycle(duty)
                print(f"Duty: {duty:>3}%")
                time.sleep(0.5)

            time.sleep(1.0)

            # ramp down
            for duty in range(80, -1, -5):
                pwm.ChangeDutyCycle(duty)
                print(f"Duty: {duty:>3}%")
                time.sleep(0.5)

            time.sleep(1.0)

    except KeyboardInterrupt:
        print("\nStopping motor...")

    finally:
        pwm.ChangeDutyCycle(0)
        time.sleep(0.2)
        pwm.stop()
        GPIO.cleanup()
        print("Done.")

if __name__ == "__main__":
    main()
