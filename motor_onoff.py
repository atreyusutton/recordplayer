import RPi.GPIO as GPIO
import time

GPIO.setmode(GPIO.BCM)
GPIO.setup(18, GPIO.OUT)

print("Turning motor ON for 5 seconds...")

GPIO.output(18, GPIO.HIGH)
time.sleep(5)

print("Turning motor OFF")
GPIO.output(18, GPIO.LOW)

GPIO.cleanup()
